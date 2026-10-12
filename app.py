"""Giao diện cục bộ của Video Công Thức; worker không truy cập Streamlit."""
from __future__ import annotations

import copy
import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

import config
import filters
import jev_client
import keys
import llm_client
import pipeline
from collectors import facebook, transcript
from errors import ServiceError


SERVICE_LABELS = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM"}
DEFAULT_SETTINGS = {
    "jev": {"model": "jev-1.13", "yes_threshold": 0.5, "min_confidence": 0.6},
    "llm": {"base_url": "", "model": "", "temperature": 0.4},
    "stt": {"provider": "deepgram", "model": "nova-3", "language": "vi",
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

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if executable.is_file():
        return
    driver = compute_driver_executable()
    command = list(driver) if isinstance(driver, tuple) else [str(driver)]
    result = subprocess.run(
        [*command, "install", "chromium"], env=get_driver_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not executable.is_file():
        raise RuntimeError("Không thể tải Chromium. Kiểm tra mạng và dung lượng ổ đĩa rồi thử lại.")


@st.cache_resource(show_spinner=False)
def ensure_browser() -> bool:
    """Kiểm tra/tải Chromium một lần; Playwright chạy ngoài thread giao diện."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(_install_chromium).result()
    return True


def _scan_worker(params, settings: dict, events: queue.Queue, stop: threading.Event) -> None:
    try:
        result = pipeline.run(params, settings, events.put, stop)
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
                "key_status": None, "login_message": None, "notice": None}
    for name, value in defaults.items():
        if name not in st.session_state:
            st.session_state[name] = value


def _busy() -> bool:
    return st.session_state.running or st.session_state.logging_in


def _saved_key(name: str) -> None:
    value = keys.get_key(name)
    st.caption("Key hiện tại: " + (keys.mask(value) if value else "Chưa lưu"))


def _save_service(name: str, candidate: str, settings: dict,
                  base_url: str = "", model: str = "") -> None:
    if not keys.storage_secure():
        st.error("Không thể lưu API key: kho bảo mật chưa khả dụng. Hãy bật Windows Credential Manager.")
        return
    candidate = candidate.strip() or keys.get_key(name) or ""
    if not candidate:
        st.error("Vui lòng nhập API key trước khi kiểm tra.")
        return
    if name == "llm" and (not base_url.strip() or not model.strip()):
        st.error("Vui lòng nhập địa chỉ endpoint và tên model LLM.")
        return
    try:
        with st.spinner("Đang kiểm tra kết nối..."):
            if name == "jev":
                jev_client.check_key(candidate, settings["jev"]["model"])
            elif name == "deepgram":
                transcript.check_key(candidate)
            else:
                llm_client.check_key(base_url.strip(), candidate, model.strip())
            keys.set_key(name, candidate)
            if name == "llm":
                updated = copy.deepcopy(settings)
                updated["llm"].update(base_url=base_url.strip(), model=model.strip())
                config.save_settings(updated)
        st.session_state.key_status = None
        # Widget state can only be cleared before it is instantiated on the next run.
        st.session_state["clear_key_input"] = f"input_{name}"
        st.session_state.notice = f"Đã kiểm tra và lưu cấu hình {SERVICE_LABELS[name]}."
        st.rerun()
    except Exception as exc:
        st.error(_error_message(exc, (candidate,)))


def _reset_configuration() -> None:
    for name in SERVICE_LABELS:
        keys.delete_key(name)
    config.save_settings(copy.deepcopy(DEFAULT_SETTINGS))
    (config.CONFIG_DIR / "channels.txt").write_text("", encoding="utf-8")
    for name in ("input_jev", "input_deepgram", "input_llm", "llm_base_url",
                 "llm_model", "channels_editor", "min_followers", "confirm_reset"):
        st.session_state.pop(name, None)
    st.session_state.key_status = None
    st.session_state.notice = "Đã đặt lại API key, cài đặt và danh sách kênh. Dữ liệu và phiên Facebook được giữ nguyên."


def _settings_tab(settings: dict) -> None:
    st.subheader("1. Kết nối dịch vụ")
    st.caption("Nhập key một lần. Chỉ lưu vào Windows Credential Manager sau khi kiểm tra thành công.")
    if not keys.storage_secure():
        st.warning("Máy này chưa có kho lưu key an toàn. Không lưu key vào file chữ thường; hãy bật Windows Credential Manager.")
    locked = _busy()
    for name in ("jev", "deepgram"):
        with st.container(border=True):
            st.markdown(f"**{SERVICE_LABELS[name]}**")
            _saved_key(name)
            with st.form(f"form_{name}"):
                value = st.text_input("API key", type="password", key=f"input_{name}", disabled=locked)
                if st.form_submit_button("Kiểm tra và lưu", disabled=locked):
                    _save_service(name, value, settings)
    with st.container(border=True):
        st.markdown("**LLM · endpoint tương thích OpenAI**")
        _saved_key("llm")
        with st.form("form_llm"):
            base_url = st.text_input("Địa chỉ endpoint (base_url)", value=settings["llm"]["base_url"],
                                     key="llm_base_url", disabled=locked)
            value = st.text_input("API key LLM", type="password", key="input_llm", disabled=locked)
            model = st.text_input("Tên model", value=settings["llm"]["model"], key="llm_model", disabled=locked)
            if st.form_submit_button("Kiểm tra và lưu", disabled=locked):
                _save_service("llm", value, settings, base_url, model)
    st.subheader("2. Kênh tham khảo và Facebook")
    channels_file = config.CONFIG_DIR / "channels.txt"
    with st.form("channels_form"):
        channels = st.text_area("Danh sách kênh (mỗi dòng một URL Facebook)",
                                value=channels_file.read_text(encoding="utf-8") if channels_file.exists() else "",
                                height=180, key="channels_editor", disabled=locked)
        if st.form_submit_button("Lưu danh sách kênh", disabled=locked):
            try:
                channels_file.write_text(channels.strip() + "\n", encoding="utf-8")
                st.success("Đã lưu danh sách kênh.")
            except OSError:
                st.error("Không thể lưu danh sách kênh. Kiểm tra quyền ghi thư mục config.")
    if st.button("Đăng nhập Facebook", disabled=locked):
        events = queue.Queue()
        worker = threading.Thread(target=_login_worker, args=(events,), daemon=True, name="facebook-login")
        st.session_state.login_queue = events
        st.session_state.login_thread = worker
        st.session_state.logging_in = True
        st.session_state.login_message = None
        worker.start()
        st.rerun()
    _login_status()
    st.warning("Không chia sẻ thư mục profile/ và file data/fb_cookies.txt: chúng chứa phiên đăng nhập Facebook của bạn.")
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
            st.markdown(f"{'🔴' if reason else '🟢'} **{SERVICE_LABELS[name]}**")
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
                                    progress=None, scan_result=None)
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
                elif kind == "finished":
                    st.session_state.running = False
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
            st.rerun()
        if st.session_state.stop_event.is_set():
            st.info("Đã yêu cầu dừng. Đang hoàn tất bước hiện tại và lưu kết quả đã xử lý.")
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
        missing = keys.missing_keys()
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
        st.warning("Hoàn tất Cài đặt trước khi sử dụng. Còn thiếu key: " + ", ".join(SERVICE_LABELS[name] for name in missing))
    settings_tab, scan_tab, results_tab = st.tabs(["Cài đặt", "Chạy quét", "Kết quả"])
    with settings_tab:
        _settings_tab(settings)
    with scan_tab:
        if missing:
            st.warning("Chạy quét đang bị khóa. Vui lòng kiểm tra và lưu đủ 3 API key trong Cài đặt.")
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
