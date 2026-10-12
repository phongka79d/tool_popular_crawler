"""Điểm vào Windows: chạy Streamlit cục bộ và mở giao diện trong cửa sổ ứng dụng riêng.

Ưu tiên Microsoft Edge chế độ app (có sẵn trên Windows 10/11, không thêm thư viện): cửa sổ riêng,
không thanh địa chỉ. Không có Edge thì chuẩn bị và mở Chromium. Đóng cửa sổ (hoặc tab) thì ứng dụng
tự tắt sau ít giây, không để tiến trình chạy ngầm.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from dataclasses import dataclass, replace

import applog

# Không còn cửa sổ nào kết nối trong khoảng này thì tắt. Đủ dài để tải lại trang (F5) không làm tắt app.
IDLE_EXIT_SECONDS = 15
POLL_SECONDS = 1.0
STARTUP_EXIT_SECONDS = 120
PROCESS_HANDOFF_SECONDS = 5


@dataclass(frozen=True)
class WatchdogState:
    opened_at: float
    seen_session: bool = False
    idle_since: float | None = None
    owned_process: bool = False


def watchdog_decision(state: WatchdogState, now: float, sessions: int | None,
                      process_alive: bool | None) -> tuple[WatchdogState, bool]:
    """Pure timeline step; a short-lived browser starter may have handed off."""
    owned = state.owned_process or (
        process_alive is True and now - state.opened_at >= PROCESS_HANDOFF_SECONDS)
    seen = state.seen_session or (sessions is not None and sessions > 0)
    closed = (owned and process_alive is False) or (seen and sessions == 0)
    idle = (state.idle_since if state.idle_since is not None else now) if closed else None
    updated = replace(state, seen_session=seen, owned_process=owned, idle_since=idle)
    return updated, (
        (idle is not None and now - idle >= IDLE_EXIT_SECONDS)
        or (not seen and now - state.opened_at >= STARTUP_EXIT_SECONDS)
    )


@dataclass
class BrowserWindow:
    ready: threading.Event
    process: subprocess.Popen | None = None
    opened_at: float | None = None


def find_free_port(start: int = 8501) -> int:
    """Chọn cổng trống đầu tiên trên địa chỉ loopback."""
    for port in range(start, 65536):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Không tìm được cổng trống để mở ứng dụng.")


def resolve_app_path() -> Path:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    path = root / "app.py"
    if not path.is_file():
        raise FileNotFoundError("Không tìm thấy app.py trong bộ cài Video Công Thức.")
    return path


def _wait_for_port(port: int, stopped: threading.Event) -> bool:
    deadline = time.monotonic() + 60
    while not stopped.is_set() and time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            stopped.wait(0.2)
    return False


def _active_sessions() -> int | None:
    """Số cửa sổ/tab đang kết nối; None nếu Streamlit chưa sẵn sàng hoặc đổi API nội bộ."""
    from streamlit.runtime import Runtime

    if not Runtime.exists():
        return None
    manager = getattr(Runtime.instance(), "_session_mgr", None)
    count = getattr(manager, "num_active_sessions", None)
    return count() if callable(count) else None


def _shutdown(stopped: threading.Event) -> None:
    """Stop the runtime, then bound shutdown even without a Windows console."""
    from streamlit.runtime import Runtime

    applog.log.info("Đã đóng cửa sổ ứng dụng, đang tắt Video Công Thức...")
    try:
        if Runtime.exists():
            Runtime.instance().stop()
    except Exception:
        applog.log.exception("Không dừng được Streamlit")
    # Runtime.stop alone does not stop uvicorn. A worker-thread SIGINT on Windows
    # can remain pending while the main thread waits inside the asyncio loop.
    if not stopped.wait(1):
        logging.shutdown()
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                try:
                    stream.flush()
                except (OSError, ValueError):
                    pass
        os._exit(0)


def _exit_when_window_closed(stopped: threading.Event, window: BrowserWindow) -> None:
    state = None
    failed_count = False
    while not stopped.wait(POLL_SECONDS):
        if not window.ready.is_set():
            continue  # Chromium may still be downloading on first launch.
        if state is None:
            state = WatchdogState(window.opened_at)
        try:
            sessions = _active_sessions()
        except Exception:
            if not failed_count:
                applog.log.exception("Không đọc được số phiên Streamlit")
                failed_count = True
            sessions = None
        alive = window.process.poll() is None if window.process is not None else None
        state, should_exit = watchdog_decision(state, time.monotonic(), sessions, alive)
        if should_exit:
            _shutdown(stopped)
            return


def open_browser(url: str) -> subprocess.Popen | None:
    """Prefer Edge, then installed Chromium; default browser is the last resort."""
    import config
    from browser_setup import ensure_chromium

    edge = config.edge_path()
    if edge:
        try:
            return subprocess.Popen([edge, f"--app={url}", "--window-size=1280,900"])
        except OSError:
            applog.log.exception("Không mở được Edge; thử Chromium")
    try:
        chromium = ensure_chromium()
        return subprocess.Popen([str(chromium), f"--app={url}", "--window-size=1280,900"])
    except Exception:
        applog.log.exception("Không mở được Chromium; mở trình duyệt mặc định")
        if not webbrowser.open(url):
            applog.log.error("Không mở được trình duyệt mặc định")
        return None


def _open_window(port: int, stopped: threading.Event, window: BrowserWindow) -> None:
    if not _wait_for_port(port, stopped):
        applog.log.error("Máy chủ không khởi động trong 60 giây")
        _shutdown(stopped)
        return
    try:
        window.process = open_browser(f"http://127.0.0.1:{port}")
    finally:
        window.opened_at = time.monotonic()
        window.ready.set()


def _show_fatal_error(exc: BaseException) -> None:
    """Không có console thì lỗi khởi động phải hiện bằng hộp thoại, không im lặng."""
    import ctypes

    message = ("Video Công Thức không khởi động được.\n\n"
               f"{type(exc).__name__}: {exc}\n\nChi tiết trong data\\app.log.")
    ctypes.windll.user32.MessageBoxW(None, message, "Video Công Thức", 0x10)


def main() -> None:
    # Trước khi import Streamlit: handler của Streamlit ghi vào sys.stderr, tức là vào data/app.log.
    applog.setup()
    try:
        _serve()
    except Exception as exc:
        applog.log.exception("Không khởi động được ứng dụng")
        _show_fatal_error(exc)
        raise


def _serve() -> None:
    from streamlit.web import bootstrap

    app_path = resolve_app_path()
    port = find_free_port()
    # Frozen builds keep app.py in _MEIPASS; writable config/data stay beside the exe.
    app_dir = str(app_path.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    sys.argv = ["streamlit", "run", str(app_path), "--server.headless=true",
                "--server.port", str(port), "--global.developmentMode=false",
                "--server.address=127.0.0.1", "--client.toolbarMode=minimal"]
    flags = {"server.headless": True, "server.port": port,
             "server.address": "127.0.0.1", "global.developmentMode": False,
             "browser.gatherUsageStats": False, "server.fileWatcherType": "none",
             "client.toolbarMode": "minimal", "logger.messageFormat": applog.LOG_FORMAT}
    # A force-killed browser cannot send a websocket close frame. Detect a
    # broken local connection promptly instead of waiting default ping timeouts.
    flags["server.websocketPingInterval"] = 1
    bootstrap.load_config_options(flags)
    stopped = threading.Event()
    window = BrowserWindow(threading.Event())
    helpers = [threading.Thread(target=_open_window, args=(port, stopped, window), daemon=True, name="open-app-window"),
               threading.Thread(target=_exit_when_window_closed, args=(stopped, window), daemon=True,
                                name="exit-when-closed")]
    for thread in helpers:
        thread.start()
    try:
        bootstrap.run(str(app_path), False, [], flags)
    finally:
        stopped.set()
        for thread in helpers:
            thread.join(timeout=1)


if __name__ == "__main__":
    main()
