"""Điểm vào cửa sổ Windows của Video Công Thức."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import applog, config


_REQUIRED_BUNDLE_FILES = ("base_library.zip", "ffmpeg.exe", "frontend/index.html")
_ARCHIVE_TEMP_MARKERS = ("\\temp1_", "\\rar$", "\\7zo")


class BundleIncomplete(RuntimeError):
    """Bộ cài thiếu tệp hoặc chưa được giải nén."""


class WebViewUnavailable(RuntimeError):
    """Không khởi động được bộ máy hiển thị Edge WebView2."""


def bundle_problems(bundle_dir: Path, exe_path: Path) -> list[str]:
    problems: list[str] = []
    if any(marker in str(exe_path).replace("/", "\\").lower() for marker in _ARCHIVE_TEMP_MARKERS):
        problems.append("đang chạy trực tiếp bên trong file ZIP")
    try:
        os.listdir(bundle_dir)
    except OSError as exc:
        return problems + [f"không đọc được thư mục {bundle_dir} ({exc.strerror or exc})"]
    for name in _REQUIRED_BUNDLE_FILES:
        if not (bundle_dir / name).is_file():
            display_name = name.replace("/", "\\")
            problems.append(f"thiếu app\\{display_name}")
    return problems


def _check_bundle() -> None:
    if not getattr(sys, "frozen", False):
        return
    bundle_dir, exe_path = Path(sys._MEIPASS), Path(sys.executable)
    applog.log.info("Bản exe: %s · thư mục chương trình: %s", exe_path, bundle_dir)
    problems = bundle_problems(bundle_dir, exe_path)
    if problems:
        applog.log.error("Bộ cài chưa đầy đủ: %s", "; ".join(problems))
        raise BundleIncomplete("; ".join(problems))


def _show_fatal_error(exc: BaseException) -> None:
    import ctypes

    if isinstance(exc, BundleIncomplete):
        message = (
            "Video Công Thức chưa được giải nén đầy đủ nên không chạy được.\n\n"
            f"Lý do: {exc}.\n\n"
            "Cách sửa:\n"
            "1. Đóng cửa sổ này. Bấm chuột phải vào file VideoCongThuc.zip → Extract All (Giải nén tất cả).\n"
            "2. Giải nén vào thư mục ngắn, ví dụ C:\\VideoCongThuc hoặc D:\\VideoCongThuc.\n"
            "3. Mở thư mục vừa giải nén và chạy VideoCongThuc.exe. Không chạy exe khi đang xem bên trong file ZIP, "
            "không chép riêng file exe ra chỗ khác (dùng Send to → Desktop (create shortcut)).\n"
            "4. Nếu vẫn lỗi, phần mềm diệt virus có thể đã xóa tệp: cho phép thư mục này rồi giải nén lại.\n\n"
            "Tool đã có sẵn mọi thư viện cần thiết, không cần cài thêm Python.\n"
            "Chi tiết trong data\\app.log."
        )
    elif isinstance(exc, WebViewUnavailable):
        message = (
            "Không khởi động được Microsoft Edge WebView2.\n\n"
            "Hãy cài Microsoft Edge WebView2 Runtime rồi mở lại Video Công Thức:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            f"{exc}\n\nChi tiết trong data\\app.log."
        )
    else:
        message = (
            "Video Công Thức không khởi động được.\n\n"
            f"{type(exc).__name__}: {exc}\n\nChi tiết trong data\\app.log."
        )
    ctypes.windll.user32.MessageBoxW(None, message, "Video Công Thức", 0x10)


def _serve() -> None:
    import webview

    from backend.api import Bridge, app_state, scan

    threading.Thread(target=app_state.prepare_browser, daemon=True, name="prepare-browser").start()
    bridge = Bridge()
    window = webview.create_window(
        "Video Công Thức",
        url=str(config.FRONTEND_DIR / "index.html"),
        js_api=bridge,
        width=1280,
        height=860,
        min_size=(1100, 720),
        background_color="#F6F7FB",
    )
    if window is None:
        raise RuntimeError("Không tạo được cửa sổ ứng dụng.")
    bridge.attach(window)

    def on_closing():
        try:
            if scan.get_scan_state(0).get("running"):
                if not window.create_confirmation_dialog(
                    "Video Công Thức", "Đang quét. Đóng ứng dụng sẽ dừng quét. Vẫn đóng?"
                ):
                    return False
                scan.stop_scan()
            return True
        except Exception:
            applog.log.exception("Không kiểm tra hoặc dừng được phiên quét khi đóng cửa sổ")
            return False

    window.events.closing += on_closing
    renderer_errors = []

    def check_renderer():
        # pywebview 6.2.1 có thể âm thầm dùng MSHTML khi máy thiếu WebView2.
        if webview.renderer != "edgechromium":
            renderer_errors.append(WebViewUnavailable("Máy chưa có bộ máy hiển thị Edge WebView2 phù hợp."))
            window.destroy()

    try:
        webview.start(
            check_renderer,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(config.DATA_DIR / "webview"),
        )
    except Exception as exc:
        raise WebViewUnavailable(str(exc)) from exc
    if renderer_errors:
        raise renderer_errors[0]


def main() -> None:
    try:
        applog.setup()
        config.ensure_dirs()
        _check_bundle()
        _serve()
    except Exception as exc:
        applog.log.exception("Không khởi động được ứng dụng")
        _show_fatal_error(exc)
        raise


if __name__ == "__main__":
    main()
