"""Giao diện cục bộ của Video Công Thức; worker không truy cập Streamlit."""
from __future__ import annotations

import copy
import hashlib
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

import config
import filters
import jev_client
import keys
import llm_client
import pipeline
from collectors import cookies, facebook, transcript
from errors import ServiceError


SERVICE_LABELS = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM"}
DEFAULT_SETTINGS = {
    "jev": {"model": "", "yes_threshold": 0.5, "min_confidence": 0.6},
    "llm": {"base_url": "", "model": "", "temperature": 0.4},
    "stt": {"provider": "deepgram", "model": "", "language": "vi",
            "keyterms_file": "config/keyterms.txt", "fallback": "local_whisper",
            "whisper_model": "small"},
    "scan": {"min_page_followers": 100000, "delay_min_s": 3, "delay_max_s": 8,
             "page_delay_min_s": 30, "page_delay_max_s": 60,
             "max_videos_per_page": 200, "max_scroll_rounds": 60, "stall_rounds": 4},
    "score_weights": {"ratio_median": 40, "ratio_median_cap": 5, "replicable": 25,
                      "hook_strength": 20, "relevant": 15},
    "my_page": {"name": "Thế Thảo Pharma", "audience": "Chủ nhà thuốc, dược sĩ"},
}
METRICS = {
    "views": "Lượt xem", "ratio_follow": "View / follower",
    "ratio_median": "View / trung vị kênh", "share_rate": "Tỷ lệ chia sẻ",
    "engagement": "Tỷ lệ tương tác", "shares": "Lượt chia sẻ",
    "comments": "Bình luận", "reactions": "Cảm xúc",
}

SERVICE_ROLES = {
    "jev": "Gắn nhãn chủ đề, kiểu hook và cấu trúc cho từng video.",
    "deepgram": "Chuyển lời nói trong video thành chữ.",
    "llm": "Viết phân tích và gợi ý nhân bản. Dùng endpoint tương thích OpenAI.",
}
KEY_HELP = {
    "jev": "Key lấy từ tài khoản Jev. Key chỉ được lưu sau khi kiểm tra thành công.",
    "deepgram": "Key lấy từ trang quản lý API key của Deepgram. Key chỉ được lưu sau khi kiểm tra thành công.",
    "llm": "API key của nhà cung cấp đã chọn. Key chỉ được lưu sau khi kiểm tra thành công.",
}
LLM_PRESETS = {
    "OpenRouter": "https://openrouter.ai/api/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
LLM_CUSTOM = "Khác (tự nhập)"


def _redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, keys.mask(secret))
    for name in SERVICE_LABELS:
        secret = keys.get_key(name)
        if secret:
            text = text.replace(secret, keys.mask(secret))
    return text


def _error_message(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    if isinstance(exc, ServiceError):
        return _redact(str(exc), secrets)
    return "Không thể hoàn tất thao tác. Kiểm tra kết nối, quyền truy cập và cấu hình rồi thử lại."


def _install_chromium() -> None:
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    from playwright.sync_api import sync_playwright

    if config.edge_path():
        return  # quét bằng Edge có sẵn của Windows (collectors.facebook): không cần tải trình duyệt
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if _browsers_installed(executable):
        return  # đã tải ở lần mở trước: không tải lại
    driver = compute_driver_executable()
    command = list(driver) if isinstance(driver, tuple) else [str(driver)]
    env = get_driver_env()
    if getattr(sys, "frozen", False):
        # Giống playwright/_impl/_transport.py: bản đóng gói tìm Chromium trong chính thư mục ứng dụng.
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    print("Đang tải Chromium lần đầu (~150 MB), vui lòng chờ...", flush=True)
    # Kế thừa cửa sổ console để người dùng thấy tiến độ và lỗi tải.
    # --no-shell: tool luôn chạy trình duyệt có cửa sổ, không dùng Headless Shell.
    result = subprocess.run([*command, "install", "chromium", "--no-shell"], env=env)
    if result.returncode or not _browsers_installed(executable):
        print(f"Tải Chromium thất bại (mã {result.returncode}); thiếu {executable}", flush=True)
        raise RuntimeError("Không thể tải Chromium. Kiểm tra mạng và dung lượng ổ đĩa rồi thử lại.")


def _browsers_installed(chromium_exe: Path) -> bool:
    """Chromium đã tải xong.

    Playwright chỉ ghi INSTALLATION_COMPLETE khi giải nén xong, nên lần tải bị ngắt giữa chừng sẽ được tải tiếp.
    """
    chromium_dir = chromium_exe.parents[1]  # .../chromium-<rev>/chrome-win64/chrome.exe
    return chromium_exe.is_file() and (chromium_dir / "INSTALLATION_COMPLETE").is_file()


@st.cache_resource(show_spinner=False)
def ensure_browser() -> bool:
    """Kiểm tra/tải Chromium một lần; Playwright chạy ngoài thread giao diện."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            executor.submit(_install_chromium).result()
        except Exception:
            traceback.print_exc()  # chẩn đoán trên cửa sổ console; giao diện chỉ hiện thông báo ngắn
            raise
    return True


def _scan_worker(params, settings: dict, events: queue.Queue, stop: threading.Event) -> None:
    def ask_user(kind: str, message: str, options: list[tuple[str, str]]) -> str:
        """Chạy trên thread worker: chờ người dùng chọn; Dừng thì trả về "pause"."""
        question = {"kind": kind, "message": message, "options": options,
                    "answer_event": threading.Event(), "answer": None}
        events.put(("question", question))
        while not question["answer_event"].wait(0.5):
            if stop.is_set():
                return "pause"
        return question["answer"]

    try:
        result = pipeline.run(params, settings, events.put, stop, ask_user=ask_user)
        events.put(("result", result))
    except Exception as exc:
        events.put(("failure", _error_message(exc)))
    finally:
        events.put(("finished", None))


def _login_worker(events: queue.Queue) -> None:
    try:
        success = facebook.login_interactive()
        events.put(("login", success))
    except Exception as exc:
        events.put(("failure", _error_message(exc)))
    finally:
        events.put(("finished", None))


def _init_state() -> None:
    defaults = {"running": False, "logging_in": False, "scan_log": [],
                "scan_errors": [], "progress": None, "scan_result": None,
                "key_status": None, "login_message": None, "notice": None, "question": None,
                "svc_models": {}}
    for name, value in defaults.items():
        if name not in st.session_state:
            st.session_state[name] = value


def _busy() -> bool:
    return st.session_state.running or st.session_state.logging_in


def _model_tag(name: str, key: str, base_url: str = "") -> str:
    """Dấu vân tay của key và endpoint: danh sách model chỉ dùng lại khi cả hai không đổi."""
    return hashlib.sha256("\n".join((name, base_url, key)).encode("utf-8")).hexdigest()


def _is_http_url(value: str) -> bool:
    parts = urlsplit(value.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _configured(name: str, settings: dict, saved: str | None) -> bool:
    """Đã kết nối khi có key đã lưu và đã chọn đủ model (Deepgram thêm ngôn ngữ, LLM thêm endpoint)."""
    if not saved:
        return False
    if name == "jev":
        return bool(settings["jev"]["model"])
    if name == "deepgram":
        return bool(settings["stt"]["model"] and settings["stt"]["language"])
    return bool(settings["llm"]["base_url"] and settings["llm"]["model"])


def _saved_model(name: str, settings: dict) -> str:
    if name == "jev":
        return settings["jev"]["model"]
    if name == "deepgram":
        return settings["stt"]["model"]
    return settings["llm"]["model"]


def _fetch_models(name: str, candidate: str, base_url: str) -> list[dict]:
    if name == "jev":
        return jev_client.list_models(candidate)
    if name == "deepgram":
        return transcript.list_deepgram_models(candidate)
    return llm_client.list_models(base_url, candidate)


def _connect(name: str, candidate: str, base_url: str) -> None:
    """Tải danh sách model vào session. Không ghi gì vào settings hay kho key."""
    cache = st.session_state.svc_models
    if not candidate:
        cache.pop(name, None)
        st.error("Vui lòng nhập API key trước khi kết nối.")
        return
    if name == "llm" and not _is_http_url(base_url):
        cache.pop(name, None)
        st.error("Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://.")
        return
    try:
        with st.spinner("Đang kết nối..."):
            items = _fetch_models(name, candidate, base_url)
    except Exception as exc:
        cache.pop(name, None)
        st.error(_error_message(exc, (candidate,)))
        return
    if not items:
        cache.pop(name, None)
        st.error("Dịch vụ không trả về model nào. Kiểm tra lại " + ("key và endpoint." if name == "llm" else "key."))
        return
    cache[name] = {"tag": _model_tag(name, candidate, base_url), "items": items}


def _cached_entry(name: str, candidate: str, base_url: str) -> dict | None:
    entry = st.session_state.svc_models.get(name)
    if entry and candidate and entry["tag"] == _model_tag(name, candidate, base_url):
        return entry
    return None


def _index_of(options: list[str], value: str) -> int:
    return options.index(value) if value in options else 0


def _deepgram_index(items: list[dict], saved: str) -> int:
    names = [item["name"] for item in items]
    if saved in names:
        return names.index(saved)
    # Giá trị cũ như "nova-3" là tên kiến trúc: chọn model đầu tiên thuộc kiến trúc đó.
    for index, item in enumerate(items):
        if saved and item["architecture"] == saved:
            return index
    return 0


def _format_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _llm_option_label(item: dict) -> str:
    if item["price_in"] is None and item["price_out"] is None:
        price = "giá: nhà cung cấp không công bố qua API"
    else:
        price_in = "không rõ" if item["price_in"] is None else _format_number(item["price_in"])
        price_out = "không rõ" if item["price_out"] is None else _format_number(item["price_out"])
        price = f"giá vào {price_in} · ra {price_out} USD / 1 triệu token"
    parts = [item["id"], price]
    context = item.get("context_length")
    if isinstance(context, (int, float)) and context > 0:
        parts.append(f"ngữ cảnh {int(context):,} token".replace(",", "."))
    return " · ".join(parts)


def _render_jev_model(items: list[dict], settings: dict, tag: str, locked: bool) -> dict:
    names = [item["name"] for item in items]
    model = st.selectbox("Model Jev", names, index=_index_of(names, settings["jev"]["model"]),
                         key=f"svc_model_jev_{tag[:12]}", disabled=locked,
                         help="Model dùng để gắn nhãn video. Mô tả và ngày phát hành hiển thị bên dưới.")
    chosen = next(item for item in items if item["name"] == model)
    details = [chosen["description"], f"phát hành {chosen['release_date']}" if chosen["release_date"] else ""]
    text = " · ".join(part for part in details if part)
    if text:
        st.caption(text)
    return {"model": model}


def _render_deepgram_model(items: list[dict], settings: dict, tag: str, locked: bool) -> dict | None:
    names = [item["name"] for item in items]
    model = st.selectbox("Model Deepgram", names, index=_deepgram_index(items, settings["stt"]["model"]),
                         key=f"svc_model_deepgram_{tag[:12]}", disabled=locked,
                         help="Model chuyển lời nói thành chữ, chỉ gồm model xử lý file ghi sẵn.")
    chosen = next(item for item in items if item["name"] == model)
    if chosen["architecture"]:
        st.caption(f"Kiến trúc: {chosen['architecture']}")
    languages = chosen["languages"]
    if not languages:
        st.error("Model này không có ngôn ngữ nào. Hãy chọn model khác.")
        return None
    codes = [lang["code"] for lang in languages]
    labels = {lang["code"]: f"{lang['label']} ({lang['code']})" for lang in languages}
    saved_language = settings["stt"]["language"]
    if "vi" in codes:
        index = codes.index("vi")
    elif saved_language in codes:
        index = codes.index(saved_language)
    else:
        index = 0
    language = st.selectbox("Ngôn ngữ thoại", codes, index=index, format_func=labels.__getitem__,
                            key=f"svc_lang_{tag[:12]}_{model}", disabled=locked,
                            help="Ngôn ngữ của video. Ưu tiên tiếng Việt (vi) khi model hỗ trợ.")
    return {"model": model, "language": language}


def _render_llm_model(items: list[dict], settings: dict, tag: str, locked: bool, base_url: str) -> dict:
    ids = [item["id"] for item in items]
    by_id = {item["id"]: item for item in items}
    st.caption("Một số nhà cung cấp liệt kê model mà không kiểm tra key. Key chỉ được xác nhận khi bấm Kiểm tra và lưu.")
    model = st.selectbox("Model", ids, index=_index_of(ids, settings["llm"]["model"]),
                         format_func=lambda model_id: _llm_option_label(by_id[model_id]),
                         key=f"svc_model_llm_{tag[:12]}", disabled=locked,
                         help="Gõ tên model vào ô để lọc danh sách. Giá tính bằng USD cho 1 triệu token.")
    return {"model": model, "base_url": base_url}


def _render_selection(name: str, entry: dict, settings: dict, locked: bool, base_url: str) -> dict | None:
    if name == "jev":
        return _render_jev_model(entry["items"], settings, entry["tag"], locked)
    if name == "deepgram":
        return _render_deepgram_model(entry["items"], settings, entry["tag"], locked)
    return _render_llm_model(entry["items"], settings, entry["tag"], locked, base_url)


def _llm_endpoint_input(settings: dict, locked: bool) -> str:
    saved_url = settings["llm"]["base_url"].strip()
    presets = [*LLM_PRESETS, LLM_CUSTOM]
    matched = next((label for label, url in LLM_PRESETS.items() if url.rstrip("/") == saved_url.rstrip("/")), None)
    default = matched or (LLM_CUSTOM if saved_url else presets[0])
    choice = st.selectbox("Nhà cung cấp", presets, index=presets.index(default), key="svc_llm_preset",
                          disabled=locked,
                          help="Chọn nhà cung cấp có API tương thích OpenAI. Chọn Khác để nhập địa chỉ endpoint riêng.")
    if choice != LLM_CUSTOM:
        st.caption(f"Endpoint: {LLM_PRESETS[choice]}")
        return LLM_PRESETS[choice]
    custom = st.text_input("Địa chỉ endpoint", value=saved_url if default == LLM_CUSTOM else "",
                           key="svc_llm_custom_url", disabled=locked, placeholder="https://.../v1",
                           help="Đường dẫn API của nhà cung cấp, thường kết thúc bằng /v1.")
    return custom.strip()


def _service_flow(name: str, settings: dict, saved: str | None, locked: bool) -> None:
    st.markdown("**Bước 1 · Kết nối**")
    base_url = _llm_endpoint_input(settings, locked) if name == "llm" else ""
    if saved:
        st.caption(f"Đang lưu key: {keys.mask(saved)}. Để trống ô dưới để kết nối bằng key này.")
    typed = st.text_input("API key", type="password", key=f"svc_key_{name}", disabled=locked,
                          placeholder="Để trống để dùng key đã lưu" if saved else "Dán API key vào đây",
                          help=KEY_HELP[name])
    candidate = typed.strip() or saved or ""
    if st.button("Kết nối", key=f"svc_connect_{name}", disabled=locked,
                 help="Kiểm tra key và tải danh sách model. Bước này chưa lưu gì vào máy."):
        _connect(name, candidate, base_url)
    entry = _cached_entry(name, candidate, base_url)
    if entry is None:
        st.caption("Bấm Kết nối để tải danh sách model. Chưa có gì được lưu cho đến bước 2.")
        return
    st.markdown("**Bước 2 · Chọn model**")
    if st.button("Tải lại danh sách", key=f"svc_refresh_{name}", disabled=locked,
                 help="Tải lại danh sách model từ dịch vụ."):
        _connect(name, candidate, base_url)
        entry = _cached_entry(name, candidate, base_url)
        if entry is None:
            return
    st.caption(f"Đã kết nối · {len(entry['items'])} model khả dụng.")
    selection = _render_selection(name, entry, settings, locked, base_url)
    if selection is None:
        return
    if st.button("Kiểm tra và lưu", type="primary", key=f"svc_save_{name}", disabled=locked,
                 help="Gọi thử model đã chọn một lần. Nếu thành công mới lưu key và model vào máy."):
        _save_service(name, candidate, settings, selection)


def _check_selection(name: str, candidate: str, settings: dict, selection: dict) -> None:
    if name == "jev":
        jev_client.check_key(candidate, selection["model"])
    elif name == "deepgram":
        transcript.check_key(candidate, {**settings["stt"], "model": selection["model"], "language": selection["language"]})
    else:
        llm_client.check_key(selection["base_url"], candidate, selection["model"])


def _apply_selection(settings: dict, name: str, selection: dict) -> None:
    if name == "jev":
        settings["jev"]["model"] = selection["model"]
    elif name == "deepgram":
        settings["stt"].update(model=selection["model"], language=selection["language"])
    else:
        settings["llm"].update(base_url=selection["base_url"], model=selection["model"])


def _save_service(name: str, candidate: str, settings: dict, selection: dict) -> None:
    if not keys.storage_secure():
        st.error("Không thể lưu API key: kho bảo mật chưa khả dụng. Hãy bật Windows Credential Manager.")
        return
    if not candidate:
        st.error("Vui lòng nhập API key trước khi kiểm tra.")
        return
    if name == "llm" and not _is_http_url(selection["base_url"]):
        st.error("Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://.")
        return
    try:
        with st.spinner("Đang kiểm tra model đã chọn..."):
            _check_selection(name, candidate, settings, selection)
            keys.set_key(name, candidate)
            updated = copy.deepcopy(settings)
            _apply_selection(updated, name, selection)
            config.save_settings(updated)
    except Exception as exc:
        st.error(_error_message(exc, (candidate,)))
        return
    st.session_state.key_status = None
    # Widget state can only be cleared before it is instantiated on the next run.
    st.session_state["clear_key_input"] = f"svc_key_{name}"
    st.session_state.notice = f"Đã kiểm tra và lưu cấu hình {SERVICE_LABELS[name]}."
    st.rerun()


def _reset_configuration() -> None:
    for name in SERVICE_LABELS:
        keys.delete_key(name)
    config.save_settings(copy.deepcopy(DEFAULT_SETTINGS))
    (config.CONFIG_DIR / "channels.txt").write_text("", encoding="utf-8")
    # Mọi khóa session_state của mục Cài đặt có tiền tố svc_ (ô nhập, nút, danh sách model đã tải).
    for key in [key for key in st.session_state.keys() if key.startswith("svc_")]:
        st.session_state.pop(key, None)
    st.session_state.svc_models = {}
    for key in ("channels_editor", "min_followers", "confirm_reset"):
        st.session_state.pop(key, None)
    st.session_state.key_status = None
    st.session_state.notice = "Đã đặt lại API key, cài đặt và danh sách kênh. Dữ liệu và phiên Facebook được giữ nguyên."


def _import_cookie_file(upload) -> None:
    fd, name = tempfile.mkstemp(dir=config.DATA_DIR, prefix="cookie_", suffix=Path(upload.name).suffix)
    os.close(fd)
    path = Path(name)
    try:
        path.write_bytes(upload.getvalue())
        with st.spinner("Đang nạp cookie..."):
            with ThreadPoolExecutor(max_workers=1) as executor:
                imported = executor.submit(facebook.import_cookies, path).result()
        if imported:
            st.success("Đã nạp cookie và lưu phiên Facebook.")
        else:
            st.error("Không tìm thấy cookie đăng nhập Facebook trong file. Hãy xuất cookie khi đã đăng nhập tài khoản phụ rồi thử lại.")
    except Exception as exc:
        st.error(_error_message(exc))
    finally:
        path.unlink(missing_ok=True)


def _saved_channels() -> list[str]:
    path = config.CONFIG_DIR / "channels.txt"
    if not path.exists():
        return []
    lines = (raw.strip() for raw in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#") and _is_http_url(line)]


def _channel_problems(text: str) -> list[str]:
    problems = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#") and not _is_http_url(line):
            problems.append(f"dòng {number}: {line[:60]}")
    return problems


def _facebook_logged_in() -> bool:
    if not config.COOKIE_FILE.exists():
        return False
    try:
        return cookies.has_login_cookies(cookies.read_netscape(config.COOKIE_FILE))
    except (OSError, ValueError):
        return False


def _progress_checklist(settings: dict) -> None:
    ai_ready = all(_configured(name, settings, keys.get_key(name)) for name in SERVICE_LABELS)
    channels = _saved_channels()
    steps = [
        ("Kết nối 3 dịch vụ AI", ai_ready),
        (f"Có {len(channels)} kênh để quét" if channels else "Có kênh để quét", bool(channels)),
        ("Đăng nhập Facebook", _facebook_logged_in()),
    ]
    for column, (text, done) in zip(st.columns(3), steps):
        with column:
            st.markdown(f"✓ **{text}**" if done else f"✗ **{text}** · chưa xong")


def _service_card(name: str, settings: dict, locked: bool) -> None:
    label = SERVICE_LABELS[name]
    saved = keys.get_key(name)
    if _configured(name, settings, saved):
        with st.expander(f"{label} · ✓ Đã kết nối · model {_saved_model(name, settings)}"):
            st.caption(f"{SERVICE_ROLES[name]} Muốn đổi key hoặc model, làm lại hai bước dưới đây.")
            _service_flow(name, settings, saved, locked)
        return
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.caption(SERVICE_ROLES[name])
        st.warning("✗ Chưa cấu hình · đã có key, còn thiếu model" if saved else "✗ Chưa cấu hình")
        _service_flow(name, settings, saved, locked)


def _channels_section(locked: bool) -> None:
    channels_file = config.CONFIG_DIR / "channels.txt"
    with st.form("channels_form"):
        channels = st.text_area(
            "Danh sách kênh (mỗi dòng một link Facebook)",
            value=channels_file.read_text(encoding="utf-8") if channels_file.exists() else "",
            height=180, key="channels_editor", disabled=locked,
            help="Mỗi dòng là một link trang Facebook, bắt đầu bằng https://. Dòng bắt đầu bằng # là ghi chú và bị bỏ qua.")
        if st.form_submit_button("Lưu danh sách kênh", disabled=locked):
            problems = _channel_problems(channels)
            if problems:
                more = " ..." if len(problems) > 5 else ""
                st.error("Chưa lưu. Các dòng sau không phải link bắt đầu bằng https://: " + "; ".join(problems[:5]) + more)
            else:
                lines = [raw.strip() for raw in channels.splitlines() if raw.strip()]
                try:
                    channels_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    st.success("Đã lưu danh sách kênh.")
                except OSError:
                    st.error("Không thể lưu danh sách kênh. Kiểm tra quyền ghi thư mục config.")


def _settings_tab(settings: dict) -> None:
    locked = _busy()
    _progress_checklist(settings)
    st.caption("Bảo mật: key chỉ được lưu trong Windows Credential Manager, không ghi ra file. "
               "Không chia sẻ thư mục profile/ và file data/fb_cookies.txt vì chúng chứa phiên đăng nhập Facebook của bạn.")
    if not keys.storage_secure():
        st.warning("Máy này chưa có kho lưu key an toàn. Hãy bật Windows Credential Manager trước khi lưu key.")
    st.subheader("1. Dịch vụ AI")
    for name in SERVICE_LABELS:
        _service_card(name, settings, locked)
    st.subheader("2. Kênh Facebook")
    _channels_section(locked)
    st.subheader("3. Đăng nhập Facebook")
    st.caption("Đăng nhập bằng tài khoản Facebook phụ để app quét được video.")
    if st.button("Đăng nhập Facebook", disabled=locked,
                 help="Mở cửa sổ Chromium để bạn tự đăng nhập. Phiên đăng nhập được lưu cho lần quét sau."):
        events = queue.Queue()
        worker = threading.Thread(target=_login_worker, args=(events,), daemon=True, name="facebook-login")
        st.session_state.login_queue = events
        st.session_state.login_thread = worker
        st.session_state.logging_in = True
        st.session_state.login_message = None
        worker.start()
        st.rerun()
    _login_status()
    with st.expander("Không đăng nhập được? Nạp file cookie"):
        st.caption("Đăng nhập tài khoản Facebook phụ trên trình duyệt, dùng tiện ích Cookie-Editor để xuất cookie của facebook.com ra file JSON rồi tải lên đây. Không chia sẻ file cookie cho người khác.")
        uploaded = st.file_uploader("File cookie (.json hoặc .txt)", type=["json", "txt"], key="cookie_upload", disabled=locked)
        if uploaded is not None and st.button("Nạp cookie", disabled=locked):
            _import_cookie_file(uploaded)
    st.subheader("4. Nâng cao")
    with st.expander("Đặt lại cấu hình"):
        st.caption("Xóa 3 API key, khôi phục settings.json mặc định và xóa danh sách kênh. Không xóa Excel, cache hay phiên Facebook.")
        confirmed = st.checkbox("Tôi xác nhận đặt lại toàn bộ cấu hình trên", key="confirm_reset", disabled=locked)
        if st.button("Đặt lại toàn bộ cấu hình", disabled=locked or not confirmed):
            # Defer widget-state deletion until before widgets are built again.
            st.session_state.reset_requested = True
            st.rerun()


def _render_login_status() -> None:
    finished = False
    if st.session_state.logging_in:
        while True:
            try:
                kind, value = st.session_state.login_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "login":
                st.session_state.login_message = (
                    "success", "Đã đăng nhập Facebook và lưu phiên." ) if value else (
                    "error", "Chưa đăng nhập Facebook thành công. Vui lòng thử lại.")
            elif kind == "failure":
                st.session_state.login_message = ("error", value)
            elif kind == "finished":
                st.session_state.logging_in = False
                finished = True
        if st.session_state.logging_in:
            st.info("Đang chờ đăng nhập trong cửa sổ Facebook. Hoàn tất cả bước xác minh nếu có.")
    if st.session_state.login_message:
        kind, text = st.session_state.login_message
        (st.success if kind == "success" else st.error)(text)
    if finished:
        st.rerun()


def _refresh_keys(settings: dict) -> dict:
    try:
        with st.spinner("Đang kiểm tra 3 API key..."):
            result = pipeline.check_all_keys(settings)
        result = {name: _redact(str(result[name])) if result[name] else None for name in SERVICE_LABELS}
    except Exception as exc:
        message = _error_message(exc)
        result = {name: message for name in SERVICE_LABELS}
    st.session_state.key_status = result
    return result


def _scan_tab(settings: dict) -> None:
    status = st.session_state.key_status
    if status is None:
        status = _refresh_keys(settings)
    for column, name in zip(st.columns(3), SERVICE_LABELS):
        with column:
            reason = status[name]
            st.markdown(f"{'✗' if reason else '✓'} **{SERVICE_LABELS[name]}**")
            st.caption(reason or "Key hợp lệ")
    if st.button("Kiểm tra lại trạng thái key", disabled=_busy()):
        _refresh_keys(settings)
        st.rerun()
    locked = _busy()
    left, right = st.columns(2)
    with left:
        days_choice = st.radio("Khoảng thời gian (ngày)", ["7", "14", "30", "Tự nhập"], horizontal=True, disabled=locked)
        days = int(st.number_input("Số ngày", min_value=1, value=7, step=1, disabled=locked)) if days_choice == "Tự nhập" else int(days_choice)
        format_choice = st.selectbox("Định dạng", ["Reels", "Video", "Tất cả"], index=2, disabled=locked)
    with right:
        min_followers = int(st.number_input(
            "Follower tối thiểu của page (0 = không giới hạn)", min_value=0,
            value=int(settings["scan"].get("min_page_followers", 100000)), step=10000,
            key="min_followers", disabled=locked))
        preset_names = list(filters.PRESETS)
        preset = st.selectbox("Bộ lọc video", preset_names,
                              index=preset_names.index("no_bat_thuong"),
                              format_func=lambda name: filters.PRESETS[name]["label"], disabled=locked)
    rules = dict(filters.PRESETS[preset]["rules"])
    if preset == "tu_nhap":
        st.caption("Các ngưỡng bật được kết hợp bằng AND. Đặt 0 để không lọc chỉ số đó; tỷ lệ 0,01 = 1%.")
        columns = st.columns(2)
        for index, (metric, label) in enumerate(METRICS.items()):
            with columns[index % 2]:
                if metric in {"views", "shares", "comments", "reactions"}:
                    value = st.number_input(label, min_value=0, value=0, step=1, key=f"metric_{metric}", disabled=locked)
                else:
                    value = st.number_input(label, min_value=0.0, value=0.0, step=0.01, format="%.4f", key=f"metric_{metric}", disabled=locked)
                if value > 0:
                    rules[metric] = value
    if st.button("Chạy", type="primary", disabled=locked):
        # Check afresh for every run, even when the cached indicators are green.
        checked = _refresh_keys(settings)
        if any(checked.values()):
            st.error("Chưa thể chạy: hãy sửa các lỗi API key ở tab Cài đặt.")
        elif not config.load_lines("config/channels.txt"):
            st.error("Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét.")
        else:
            params = pipeline.RunParams(days=days, formats={"reel", "video"} if format_choice == "Tất cả" else {"reel" if format_choice == "Reels" else "video"},
                                        min_page_followers=min_followers, rules=rules, preset=preset)
            events, stop = queue.Queue(), threading.Event()
            worker = threading.Thread(target=_scan_worker,
                                      args=(params, copy.deepcopy(settings), events, stop),
                                      daemon=True, name="video-scan")
            st.session_state.update(running=True, scan_queue=events, stop_event=stop,
                                    scan_thread=worker, scan_log=[], scan_errors=[],
                                    progress=None, scan_result=None, question=None)
            worker.start()
            st.rerun()
    _scan_status()


def _render_scan_status() -> None:
    finished = False
    if "scan_queue" in st.session_state:
        while True:
            try:
                event = st.session_state.scan_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, tuple):
                kind, value = event
                if kind == "result":
                    st.session_state.scan_result = str(value) if value else None
                elif kind == "failure":
                    st.session_state.scan_errors.append(value)
                elif kind == "question":
                    st.session_state.question = value
                elif kind == "finished":
                    st.session_state.running = False
                    st.session_state.question = None
                    finished = True
            else:
                st.session_state.progress = event
                if event.message:
                    st.session_state.scan_log.append(_redact(event.message))
                if event.error:
                    st.session_state.scan_errors.append(_redact(event.error))
    progress = st.session_state.progress
    if progress is not None:
        total = max(0, progress.page_total)
        index = max(0, progress.page_index)
        fraction = min(1.0, index / total) if total else 0.0
        st.progress(fraction, text=f"Kênh {index}/{total} · {_redact(progress.message)}")
        if progress.page_url:
            st.caption(_redact(progress.page_url))
    elif st.session_state.running:
        st.progress(0.0, text="Đang chuẩn bị quét...")
    if st.session_state.running:
        if st.button("Dừng", disabled=st.session_state.stop_event.is_set(), key="stop_scan"):
            st.session_state.stop_event.set()
            st.session_state.question = None
            st.rerun()
        if st.session_state.stop_event.is_set():
            st.info("Đã yêu cầu dừng. Đang hoàn tất bước hiện tại và lưu kết quả đã xử lý.")
        question = st.session_state.question
        if question is not None:
            st.warning(question["message"])
            for column, (option_id, label) in zip(st.columns(len(question["options"])), question["options"]):
                with column:
                    if st.button(label, key=f"answer_{question['kind']}_{option_id}"):
                        question["answer"] = option_id
                        question["answer_event"].set()
                        st.session_state.question = None
                        st.rerun()
    elif st.session_state.scan_result:
        st.success(f"Đã xuất {Path(st.session_state.scan_result).name}. Vào tab Kết quả để tải file.")
    elif st.session_state.scan_log and not st.session_state.scan_errors:
        st.info("Đã kết thúc quét; không có file Excel mới.")
    for message in dict.fromkeys(st.session_state.scan_errors):
        st.error(message)
    if st.session_state.scan_log:
        with st.expander("Nhật ký quét", expanded=True):
            st.text("\n".join(st.session_state.scan_log))
    if finished:
        st.rerun()


# Fragments poll only their own controls; workers communicate solely through queues.
if callable(getattr(st, "fragment", None)):
    _scan_status = st.fragment(run_every=1)(_render_scan_status)
    _login_status = st.fragment(run_every=1)(_render_login_status)
else:
    _scan_status = _render_scan_status
    _login_status = _render_login_status


def _results_tab() -> None:
    st.subheader("File Excel đã xuất")
    if st.button("Mở thư mục"):
        try:
            os.startfile(config.OUTPUT_DIR)
        except (OSError, AttributeError):
            st.error("Không thể mở thư mục kết quả trên máy này.")
    files = sorted(config.OUTPUT_DIR.glob("*.xlsx"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        st.info("Chưa có kết quả. Chạy quét để tạo file Excel đầu tiên.")
    for path in files:
        with st.container(border=True):
            st.write(path.name)
            try:
                with path.open("rb") as data:
                    st.download_button("Tải Excel", data=data, file_name=path.name,
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       key=f"download_{path.name}")
            except OSError:
                st.error("Không đọc được file Excel. Kiểm tra quyền truy cập thư mục output.")


def main() -> None:
    st.set_page_config(page_title="Video Công Thức", page_icon="🎬", layout="wide")
    config.ensure_dirs()
    _init_state()
    st.title("Video Công Thức")
    st.caption("Quét kênh Facebook · tìm video nổi bật · nghiên cứu công thức nội dung")
    try:
        if st.session_state.pop("reset_requested", False):
            _reset_configuration()
        clear_input = st.session_state.pop("clear_key_input", None)
        if clear_input:
            st.session_state[clear_input] = ""
        settings = config.load_settings()
        missing = [name for name in SERVICE_LABELS if not _configured(name, settings, keys.get_key(name))]
    except Exception as exc:
        st.error(_error_message(exc))
        return
    if st.session_state.notice:
        st.success(st.session_state.notice)
        st.session_state.notice = None
    try:
        with st.spinner("Đang tải trình duyệt (~150 MB)..."):
            ensure_browser()
    except Exception:
        st.error("Không thể tải trình duyệt Chromium. Kiểm tra mạng, dung lượng ổ đĩa và mở lại ứng dụng.")
        return
    if missing:
        st.warning("Hoàn tất mục 1 · Dịch vụ AI trong Cài đặt trước khi sử dụng. Còn thiếu: " + ", ".join(SERVICE_LABELS[name] for name in missing))
    settings_tab, scan_tab, results_tab = st.tabs(["Cài đặt", "Chạy quét", "Kết quả"])
    with settings_tab:
        _settings_tab(settings)
    with scan_tab:
        if missing:
            st.warning("Chạy quét đang bị khóa. Vui lòng hoàn tất mục 1 · Dịch vụ AI trong Cài đặt.")
        else:
            _scan_tab(settings)
    with results_tab:
        if missing:
            st.warning("Kết quả đang bị khóa. Vui lòng hoàn tất Cài đặt trước.")
        else:
            _results_tab()
    if not callable(getattr(st, "fragment", None)) and _busy():
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
