"""Điểm vào Windows: chạy Streamlit cục bộ và mở trình duyệt."""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


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


def _open_when_ready(port: int, stopped: threading.Event) -> None:
    deadline = time.monotonic() + 60
    while not stopped.is_set() and time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                pass
        except OSError:
            stopped.wait(0.2)
            continue
        if not stopped.is_set():
            webbrowser.open(f"http://127.0.0.1:{port}")
        return


def main() -> None:
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
             "client.toolbarMode": "minimal"}
    bootstrap.load_config_options(flags)
    stopped = threading.Event()
    opener = threading.Thread(target=_open_when_ready, args=(port, stopped),
                              daemon=True, name="open-app-browser")
    opener.start()
    try:
        bootstrap.run(str(app_path), False, [], flags)
    finally:
        stopped.set()
        opener.join(timeout=1)


if __name__ == "__main__":
    main()
