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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st
from openpyxl import load_workbook

import config
import export_excel
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
PAGE_SETTINGS = "Cài đặt"
PAGE_SCAN = "Chạy quét"
PAGE_RESULTS = "Kết quả"
PAGES = [PAGE_SETTINGS, PAGE_SCAN, PAGE_RESULTS]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
                "scan_errors": [], "progress": None, "scan_result": None, "scan_started": None,
                "key_status": None, "login_message": None, "notice": None, "question": None,
                "svc_models": {}, "page": PAGE_SETTINGS}
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
                          placeholder="Để trống để dùng key đã lưu" if saved else "Dán API key vào đây")
    candidate = typed.strip() or saved or ""
    connected = _cached_entry(name, candidate, base_url) is not None
    if st.button("Kết nối", key=f"svc_connect_{name}", disabled=locked,
                 type="secondary" if connected else "primary",
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
    imported = False
    try:
        path.write_bytes(upload.getvalue())
        with st.spinner("Đang nạp cookie..."):
            with ThreadPoolExecutor(max_workers=1) as executor:
                imported = executor.submit(facebook.import_cookies, path).result()
    except Exception as exc:
        st.error(_error_message(exc))
        return
    finally:
        path.unlink(missing_ok=True)
    if not imported:
        st.error("Không tìm thấy cookie đăng nhập Facebook trong file. Hãy xuất cookie khi đã đăng nhập tài khoản phụ rồi thử lại.")
        return
    st.session_state.notice = "Đã nạp cookie và lưu phiên Facebook."
    st.rerun()


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


_STEP_STATES = {"done": ":green[✓ Xong]", "current": ":blue[● Đang làm]", "pending": ":gray[○ Chưa làm]"}


@dataclass(frozen=True)
class _Guide:
    """Trạng thái để vẽ thanh 3 bước và việc tiếp theo; được tính lại mỗi lần giao diện chạy."""

    configured: dict[str, bool]
    channel_count: int
    fb_ready: bool
    running: bool
    has_result: bool
    question: bool

    @property
    def missing(self) -> list[str]:
        """Tên các dịch vụ AI chưa kết nối xong."""
        return [SERVICE_LABELS[name] for name in SERVICE_LABELS if not self.configured[name]]

    @property
    def setup_done(self) -> bool:
        return self.channel_count > 0 and self.fb_ready


def _journey(guide: _Guide) -> list[tuple[str, str]]:
    """Trạng thái từng bước: done, current hoặc pending."""
    ai = "done" if not guide.missing else "current"
    setup = "done" if guide.setup_done else ("current" if ai == "done" else "pending")
    if guide.running:
        scan = "current"
    elif guide.has_result:
        scan = "done"
    else:
        scan = "current" if ai == "done" and setup == "done" else "pending"
    return [("1 · Dịch vụ AI", ai), ("2 · Kênh & Facebook", setup), ("3 · Chạy quét", scan)]


def _next_step(guide: _Guide) -> tuple[str, str]:
    """Việc nên làm tiếp theo: (hướng dẫn, trang cần mở)."""
    if guide.question:
        return "Quét đang chờ bạn chọn cách xử lý ở tab Chạy quét.", PAGE_SCAN
    if guide.running:
        return "Đang quét. Theo dõi tiến độ ở tab Chạy quét.", PAGE_SCAN
    if guide.missing:
        return f"Kết nối đủ 3 dịch vụ AI. Còn thiếu: {', '.join(guide.missing)}.", PAGE_SETTINGS
    if not guide.setup_done:
        todo = [text for text, done in (("thêm kênh cần quét", guide.channel_count > 0),
                                        ("đăng nhập Facebook", guide.fb_ready)) if not done]
        return f"Hoàn tất bước 2: {' và '.join(todo)}.", PAGE_SETTINGS
    if guide.has_result:
        return "Đã có file Excel mới. Xem và tải về ở tab Kết quả.", PAGE_RESULTS
    return "Mọi thứ đã sẵn sàng. Chọn bộ lọc rồi bấm Bắt đầu quét.", PAGE_SCAN


def _open_page(page: str) -> None:
    """Callback của nút chuyển trang; chạy trước khi giao diện được dựng lại."""
    st.session_state.page = page


def _render_journey(guide: _Guide) -> None:
    for column, (title, state) in zip(st.columns(3), _journey(guide)):
        with column, st.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown(_STEP_STATES[state])


def _render_next_step(page: str, guide: _Guide) -> None:
    text, target = _next_step(guide)
    with st.container(border=True):
        message, action = st.columns([3, 1], vertical_alignment="center")
        message.markdown(f"**Việc tiếp theo:** {text}")
        if target != page:
            action.button(f"Đi tới {target}", type="primary", width="stretch", on_click=_open_page, args=(target,))


def _render_locked(page: str, guide: _Guide) -> None:
    """Chạy quét và Kết quả chỉ mở khi đã kết nối đủ dịch vụ AI."""
    status = "  ·  ".join(f"{'✓' if guide.configured[name] else '✗'} {SERVICE_LABELS[name]}" for name in SERVICE_LABELS)
    with st.container(border=True):
        st.markdown(f"**🔒 {page} đang khóa**")
        st.caption(f"Cần kết nối đủ 3 dịch vụ AI trước: {status}")
        st.button("Mở Cài đặt", type="primary", on_click=_open_page, args=(PAGE_SETTINGS,))


def _service_card(name: str, settings: dict, locked: bool, *, configured: bool, expanded: bool) -> None:
    label = SERVICE_LABELS[name]
    saved = keys.get_key(name)
    title = f"✓ {label} · model {_saved_model(name, settings)}" if configured else f"○ {label} · chưa cấu hình"
    # Key đổi theo trạng thái để mục vừa xong tự thu gọn và mục kế tiếp tự mở.
    with st.expander(title, expanded=expanded, key=f"svc_card_{name}_{configured}"):
        st.caption(f"{SERVICE_ROLES[name]} {KEY_HELP[name]}")
        if saved and not configured:
            st.warning("Đã có key nhưng còn thiếu model. Làm tiếp hai bước dưới đây.")
        _service_flow(name, settings, saved, locked)


def _channels_section(locked: bool) -> None:
    channels_file = config.CONFIG_DIR / "channels.txt"
    with st.container(border=True):
        st.markdown("**Kênh cần quét**")
        with st.form("channels_form", border=False):
            st.caption("Mỗi dòng là một link trang Facebook, bắt đầu bằng https://. Dòng bắt đầu bằng # là ghi chú và bị bỏ qua.")
            channels = st.text_area(
                "Danh sách link kênh", height=160, key="channels_editor", disabled=locked,
                value=channels_file.read_text(encoding="utf-8") if channels_file.exists() else "")
            if st.form_submit_button("Lưu danh sách kênh", type="primary", disabled=locked):
                problems = _channel_problems(channels)
                if problems:
                    more = " ..." if len(problems) > 5 else ""
                    st.error("Chưa lưu. Các dòng sau không phải link bắt đầu bằng https://: " + "; ".join(problems[:5]) + more)
                else:
                    lines = [raw.strip() for raw in channels.splitlines() if raw.strip()]
                    try:
                        channels_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    except OSError:
                        st.error("Không thể lưu danh sách kênh. Kiểm tra quyền ghi thư mục config.")
                    else:
                        st.session_state.notice = f"Đã lưu {len(lines)} kênh cần quét."
                        st.rerun()


def _facebook_section(fb_ready: bool, locked: bool) -> None:
    with st.container(border=True):
        st.markdown("**Đăng nhập Facebook**")
        st.markdown(":green[✓ Đã đăng nhập]" if fb_ready else ":orange[✗ Chưa đăng nhập]")
        st.caption("Dùng tài khoản Facebook phụ để app quét được video. Cửa sổ trình duyệt sẽ mở để bạn tự đăng nhập; phiên được lưu cho lần quét sau.")
        st.caption("Không chia sẻ thư mục profile/ và file data/fb_cookies.txt: chúng chứa phiên đăng nhập Facebook của bạn.")
        if st.button("Đăng nhập lại" if fb_ready else "Đăng nhập Facebook", type="secondary" if fb_ready else "primary",
                     disabled=locked, icon=":material/login:"):
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
            if uploaded is not None and st.button("Nạp cookie", type="primary", disabled=locked):
                _import_cookie_file(uploaded)


def _settings_page(settings: dict, guide: _Guide) -> None:
    locked = _busy()
    st.caption("🔒 Key chỉ được lưu trong Windows Credential Manager, không ghi ra file.")
    if not keys.storage_secure():
        st.warning("Máy này chưa có kho lưu key an toàn. Hãy bật Windows Credential Manager trước khi lưu key.")
    st.subheader("1 · Dịch vụ AI")
    st.caption("Làm lần lượt: nhập key → Kết nối → chọn model → Kiểm tra và lưu.")
    first_open = next((name for name in SERVICE_LABELS if not guide.configured[name]), None)
    for name in SERVICE_LABELS:
        _service_card(name, settings, locked, configured=guide.configured[name], expanded=name == first_open)
    st.subheader("2 · Kênh & Facebook")
    _channels_section(locked)
    _facebook_section(guide.fb_ready, locked)
    with st.expander("⚠️ Đặt lại cấu hình"):
        st.caption("Xóa 3 API key, khôi phục settings.json mặc định và xóa danh sách kênh. Không xóa Excel, cache hay phiên Facebook.")
        confirmed = st.checkbox("Tôi xác nhận đặt lại toàn bộ cấu hình trên", key="confirm_reset", disabled=locked)
        if st.button("Đặt lại toàn bộ cấu hình", disabled=locked or not confirmed, icon=":material/restart_alt:"):
            # Defer widget-state deletion until before widgets are built again.
            st.session_state.reset_requested = True
            st.rerun()


def _render_login_status() -> None:
    if st.session_state.logging_in:
        st.info("Đang chờ đăng nhập trong cửa sổ Facebook. Hoàn tất các bước xác minh nếu có.")
    if st.session_state.login_message:
        st.error(st.session_state.login_message)


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


def _key_status_panel(settings: dict, locked: bool) -> None:
    status = st.session_state.key_status
    if status is None:
        status = _refresh_keys(settings)
    failed = [SERVICE_LABELS[name] for name in SERVICE_LABELS if status[name]]
    with st.expander("Trạng thái API key", expanded=bool(failed)):
        if failed:
            st.error(f"Chưa thể chạy quét vì lỗi key ở: {', '.join(failed)}. Sửa trong mục Dịch vụ AI rồi kiểm tra lại.")
        for column, name in zip(st.columns(3), SERVICE_LABELS):
            with column:
                reason = status[name]
                st.markdown(f"{':orange[✗]' if reason else ':green[✓]'} **{SERVICE_LABELS[name]}**")
                st.caption(reason or "Key hợp lệ")
        if st.button("Kiểm tra lại", icon=":material/refresh:", disabled=locked):
            _refresh_keys(settings)
            st.rerun()


def _scan_options(settings: dict, locked: bool) -> pipeline.RunParams:
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True):
        st.markdown("**Video nào được quét?**")
        days_choice = st.radio(
            "Video đăng trong", ["7", "14", "30", "Tự nhập"], horizontal=True, disabled=locked,
            format_func=lambda choice: choice if choice == "Tự nhập" else f"{choice} ngày",
            help="Chỉ lấy video đăng trong khoảng này, tính đến hôm nay.")
        days = int(st.number_input("Số ngày", min_value=1, value=7, step=1, disabled=locked)) if days_choice == "Tự nhập" else int(days_choice)
        format_choice = st.selectbox("Loại video", ["Reels", "Video", "Tất cả"], index=2, disabled=locked,
                                     help="Reels là video dọc ngắn, Video là video thường. Tất cả là lấy cả hai loại.")
    with right, st.container(border=True):
        st.markdown("**Lọc video nổi bật**")
        min_followers = int(st.number_input(
            "Follower tối thiểu của page", min_value=0, value=int(settings["scan"].get("min_page_followers", 100000)),
            step=10000, key="min_followers", disabled=locked,
            help="Page có ít follower hơn mức này sẽ bị bỏ qua. Đặt 0 để không giới hạn."))
        preset_names = list(filters.PRESETS)
        preset = st.selectbox("Cách lọc", preset_names, index=preset_names.index("no_bat_thuong"), disabled=locked,
                              format_func=lambda name: filters.PRESETS[name]["label"],
                              help="Cách xác định video nổi bật. Có thể giữ mặc định nếu chưa rõ.")
    rules = dict(filters.PRESETS[preset]["rules"])
    if preset == "tu_nhap":
        with st.container(border=True):
            st.markdown("**Ngưỡng tự nhập**")
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
    formats = {"reel", "video"} if format_choice == "Tất cả" else {"reel" if format_choice == "Reels" else "video"}
    return pipeline.RunParams(days=days, formats=formats, min_page_followers=min_followers, rules=rules, preset=preset)


def _start_scan(settings: dict, params: pipeline.RunParams) -> None:
    if any(_refresh_keys(settings).values()):
        st.rerun()  # Panel Trạng thái API key sẽ hiện lỗi sau khi làm mới.
    if not config.load_lines("config/channels.txt"):
        st.error("Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét.")
        return
    events, stop = queue.Queue(), threading.Event()
    worker = threading.Thread(target=_scan_worker, args=(params, copy.deepcopy(settings), events, stop),
                              daemon=True, name="video-scan")
    st.session_state.update(running=True, scan_queue=events, stop_event=stop, scan_thread=worker,
                            scan_started=time.monotonic(), scan_log=[], scan_errors=[], progress=None,
                            scan_result=None, question=None)
    worker.start()
    st.rerun()


def _scan_page(settings: dict) -> None:
    _scan_status()
    locked = _busy()
    _key_status_panel(settings, locked)
    params = _scan_options(settings, locked)
    if st.button("Bắt đầu quét", type="primary", width="stretch", disabled=locked, icon=":material/play_arrow:"):
        _start_scan(settings, params)


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _format_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


def _exported_video_count(path: Path) -> int | None:
    """Số video trong sheet chi tiết (dòng đầu là tiêu đề). None nếu không đọc được file."""
    try:
        workbook = load_workbook(path, read_only=True)
        try:
            return max(0, (workbook[export_excel.SHEET_DETAIL].max_row or 1) - 1)
        finally:
            workbook.close()
    except Exception:  # chỉ là thông tin phụ: file lỗi không được làm hỏng giao diện
        return None


def _download_button(path: Path) -> None:
    try:
        with path.open("rb") as data:
            st.download_button("Tải file Excel", data=data, file_name=path.name, mime=XLSX_MIME,
                               type="primary", icon=":material/download:", key=f"download_{path.name}")
    except OSError:
        st.error("Không đọc được file Excel. Kiểm tra quyền truy cập thư mục output.")


def _render_running_scan() -> None:
    progress = st.session_state.progress
    with st.container(border=True):
        elapsed = _format_duration(time.monotonic() - st.session_state.scan_started)
        st.markdown(f"**Đang quét** · đã chạy {elapsed}")
        if progress is not None:
            total = max(0, progress.page_total)
            index = max(0, progress.page_index)
            fraction = min(1.0, index / total) if total else 0.0
            st.progress(fraction, text=f"Kênh {index}/{total} · {_redact(progress.message)}")
            if progress.page_url:
                st.caption(_redact(progress.page_url))
        else:
            st.progress(0.0, text="Đang chuẩn bị quét...")
        stopping = st.session_state.stop_event.is_set()
        if st.button("Dừng quét", icon=":material/stop_circle:", key="stop_scan", disabled=stopping):
            st.session_state.stop_event.set()
            st.session_state.question = None
            st.rerun()
        if stopping:
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


def _render_scan_result(path: Path) -> None:
    count = _exported_video_count(path)
    with st.container(border=True):
        st.markdown(f"**✅ Quét xong · {count} video**" if count is not None else "**✅ Quét xong**")
        st.caption(f"File: {path.name}")
        _download_button(path)


def _render_scan_status() -> None:
    if st.session_state.running:
        _render_running_scan()
    elif st.session_state.scan_result:
        _render_scan_result(Path(st.session_state.scan_result))
    elif st.session_state.scan_log and not st.session_state.scan_errors:
        st.info("Đã kết thúc quét; không có file Excel mới.")
    for message in dict.fromkeys(st.session_state.scan_errors):
        st.error(message)
    if st.session_state.scan_log:
        with st.expander("Nhật ký quét"):
            st.text("\n".join(st.session_state.scan_log))


def _drain_scan_queue() -> bool:
    """Nhận sự kiện từ luồng quét. Trả về True khi luồng đã kết thúc."""
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
    return finished


def _drain_login_queue() -> bool:
    """Nhận sự kiện đăng nhập Facebook. Trả về True khi cửa sổ đăng nhập đã đóng."""
    finished = False
    if st.session_state.logging_in:
        while True:
            try:
                kind, value = st.session_state.login_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "login":
                if value:
                    st.session_state.login_message = None
                    st.session_state.notice = "Đã đăng nhập Facebook và lưu phiên."
                else:
                    st.session_state.login_message = "Chưa đăng nhập Facebook thành công. Vui lòng thử lại."
            elif kind == "failure":
                st.session_state.login_message = value
            elif kind == "finished":
                st.session_state.logging_in = False
                finished = True
    return finished


def _poll_workers() -> None:
    """Nhận sự kiện của luồng quét và đăng nhập ở mọi trang; làm mới giao diện khi một trong hai vừa xong."""
    scan_done = _drain_scan_queue()
    login_done = _drain_login_queue()
    if scan_done or login_done:
        st.rerun()


def _results_page() -> None:
    files = sorted(config.OUTPUT_DIR.glob("*.xlsx"), key=lambda path: path.stat().st_mtime, reverse=True)
    title, folder = st.columns([3, 1], vertical_alignment="center")
    title.markdown("**File Excel đã xuất** · mới nhất trước")
    if folder.button("Mở thư mục", icon=":material/folder_open:", width="stretch"):
        try:
            os.startfile(config.OUTPUT_DIR)
        except (OSError, AttributeError):
            st.error("Không thể mở thư mục kết quả trên máy này.")
    if not files:
        st.info("Chưa có file Excel nào. Kết quả sẽ hiện ở đây sau mỗi lần quét.")
        return
    for path in files:
        stat = path.stat()
        with st.container(border=True):
            info, action = st.columns([3, 1], vertical_alignment="center")
            info.markdown(f"**{path.name}**")
            info.caption(f"{datetime.fromtimestamp(stat.st_mtime):%d/%m/%Y %H:%M} · {_format_size(stat.st_size)}")
            with action:
                _download_button(path)


# Fragments refresh only their own part every second; workers communicate solely through queues.
if callable(getattr(st, "fragment", None)):
    _poll = st.fragment(run_every=1)(_poll_workers)
    _scan_status = st.fragment(run_every=1)(_render_scan_status)
    _login_status = st.fragment(run_every=1)(_render_login_status)
else:
    _poll = _poll_workers
    _scan_status = _render_scan_status
    _login_status = _render_login_status


def main() -> None:
    st.set_page_config(page_title="Video Công Thức", page_icon="🎬", layout="wide")
    config.ensure_dirs()
    _init_state()
    # Cửa sổ ứng dụng riêng không có thanh công cụ Streamlit: bỏ khoảng trống mặc định ở đầu trang.
    st.markdown("<style>.block-container{padding-top:1.5rem}</style>", unsafe_allow_html=True)
    st.markdown("### 🎬 Video Công Thức")
    st.caption("Tìm video nổi bật trên các kênh Facebook để học công thức nội dung, rồi xuất kết quả ra Excel.")
    try:
        if st.session_state.pop("reset_requested", False):
            _reset_configuration()
        clear_input = st.session_state.pop("clear_key_input", None)
        if clear_input:
            st.session_state[clear_input] = ""
        settings = config.load_settings()
        configured = {name: _configured(name, settings, keys.get_key(name)) for name in SERVICE_LABELS}
    except Exception as exc:
        st.error(_error_message(exc))
        return
    if st.session_state.notice:
        st.toast(st.session_state.notice, icon="✅")
        st.session_state.notice = None
    try:
        with st.spinner("Đang tải trình duyệt (~150 MB)..."):
            ensure_browser()
    except Exception:
        st.error("Không thể tải trình duyệt Chromium. Kiểm tra mạng, dung lượng ổ đĩa và mở lại ứng dụng.")
        return
    guide = _Guide(configured=configured, channel_count=len(_saved_channels()), fb_ready=_facebook_logged_in(),
                   running=st.session_state.running, has_result=bool(st.session_state.scan_result),
                   question=st.session_state.question is not None)
    _render_journey(guide)
    page = st.segmented_control("Trang", PAGES, key="page", required=True, width="stretch",
                                label_visibility="collapsed") or PAGE_SETTINGS
    if guide.missing and page == PAGE_SCAN:
        _render_locked(page, guide)
    else:
        _render_next_step(page, guide)
        if page == PAGE_SETTINGS:
            _settings_page(settings, guide)
        elif page == PAGE_SCAN:
            _scan_page(settings)
        else:
            _results_page()
    _poll()
    if not callable(getattr(st, "fragment", None)) and _busy():
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
