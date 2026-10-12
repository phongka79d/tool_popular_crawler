"""Điểm vào Windows: chạy Streamlit cục bộ và mở giao diện trong cửa sổ ứng dụng riêng.

Ưu tiên Microsoft Edge chế độ app (có sẵn trên Windows 10/11, không thêm thư viện): cửa sổ riêng,
không thanh địa chỉ. Không có Edge thì mở trình duyệt mặc định. Đóng cửa sổ (hoặc tab) thì ứng dụng
tự tắt sau ít giây, không để tiến trình chạy ngầm.
"""
from __future__ import annotations

import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import applog

# Không còn cửa sổ nào kết nối trong khoảng này thì tắt. Đủ dài để tải lại trang (F5) không làm tắt app.
IDLE_EXIT_SECONDS = 15
POLL_SECONDS = 1.0


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


def _exit_when_window_closed(stopped: threading.Event) -> None:
    """Sau khi giao diện đã mở, tắt server khi không còn cửa sổ nào kết nối trong IDLE_EXIT_SECONDS."""
    seen = False
    idle_since: float | None = None
    while not stopped.wait(POLL_SECONDS):
        sessions = _active_sessions()
        if sessions is None:
            if seen:
                return  # API nội bộ không còn: giữ hành vi cũ, không tự tắt
            continue
        if sessions > 0:
            seen, idle_since = True, None
        elif seen:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since >= IDLE_EXIT_SECONDS:
                print("Đã đóng cửa sổ ứng dụng, đang tắt Video Công Thức...", flush=True)
                # Như bấm Ctrl+C: đi qua bộ xử lý tín hiệu của Streamlit để dừng cả web server.
                # Runtime.stop() một mình không dừng được uvicorn.
                signal.raise_signal(signal.SIGINT)
                return


def _open_window(port: int, stopped: threading.Event) -> None:
    if not _wait_for_port(port, stopped):
        return
    url = f"http://127.0.0.1:{port}"
    import config  # main() đã thêm thư mục app vào sys.path

    edge = config.edge_path()
    try:
        if edge is None:
            raise OSError("không có Edge")
        # Profile Edge mặc định của người dùng: không hiện màn hình chào/đồng bộ như profile mới.
        subprocess.Popen([edge, f"--app={url}", "--window-size=1280,900"])
    except OSError:
        webbrowser.open(url)


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
    bootstrap.load_config_options(flags)
    stopped = threading.Event()
    helpers = [threading.Thread(target=_open_window, args=(port, stopped), daemon=True, name="open-app-window"),
               threading.Thread(target=_exit_when_window_closed, args=(stopped,), daemon=True,
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
