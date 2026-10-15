"""Channel persistence and serialized Facebook session operations."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.core import config
from backend.collectors import cookies, facebook
from backend.api.common import error_message, fail

logger = logging.getLogger("app.api.channels")
_lock = threading.RLock()
_logging_in = False
_message: str | None = None
_notice: str | None = None


def _channel_problems(text: str) -> list[str]:
    problems = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            problem = facebook.page_url_problem(line)
            if problem:
                problems.append(f"Dòng {number} ({line[:50]}): {problem}")
    return problems


def saved_channels() -> list[str]:
    path = config.CONFIG_DIR / "channels.txt"
    if not path.exists():
        return []
    lines = (raw.strip() for raw in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#") and facebook.page_url_problem(line) is None]


def get_channels() -> dict:
    path = config.CONFIG_DIR / "channels.txt"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = (line.strip() for line in text.splitlines())
    count = sum(1 for line in lines if line and not line.startswith("#") and facebook.page_url_problem(line) is None)
    return {"ok": True, "text": text, "count": count, "problems": _channel_problems(text)}


def save_channels(text: str) -> dict:
    problems = _channel_problems(text)
    if problems:
        return fail("Chưa lưu. Sửa các dòng sau:\n\n" + "\n".join(f"- {problem}" for problem in problems), problems=problems)
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    try:
        (config.CONFIG_DIR / "channels.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        message = "Không thể lưu danh sách kênh. Kiểm tra quyền ghi thư mục config."
        logger.warning("%s", message, exc_info=exc)
        return fail(message)
    count = sum(1 for line in lines if not line.startswith("#"))
    return {"ok": True, "count": count, "message": f"Đã lưu {count} kênh cần quét."}


def facebook_logged_in() -> bool:
    if not config.COOKIE_FILE.exists():
        return False
    try:
        return cookies.has_login_cookies(cookies.read_netscape(config.COOKIE_FILE))
    except (OSError, ValueError):
        return False


def is_logging_in() -> bool:
    with _lock:
        return _logging_in


def _login_worker() -> None:
    global _logging_in, _message, _notice
    message = None
    notice = None
    try:
        if facebook.login_interactive():
            notice = "Đã đăng nhập Facebook và lưu phiên."
        else:
            message = "Chưa đăng nhập Facebook thành công. Vui lòng thử lại."
            logger.warning("%s", message)
    except Exception as exc:
        message = error_message(exc)
    finally:
        with _lock:
            _message, _notice = message, notice
            _logging_in = False


def start_login() -> dict:
    global _logging_in, _message, _notice
    from backend.api import scan

    with _lock:
        if _logging_in:
            return fail("Đang đăng nhập Facebook. Vui lòng chờ hoàn tất.")
        if scan.is_running():
            return fail("Đang quét. Hãy dừng quét trước khi đăng nhập Facebook.")
        _logging_in = True
        _message = _notice = None
        try:
            threading.Thread(target=_login_worker, daemon=True, name="facebook-login").start()
        except Exception as exc:
            _logging_in = False
            _message = error_message(exc)
            return fail(_message)
    return {"ok": True}


def get_login_state() -> dict:
    global _notice
    with _lock:
        result = {"ok": True, "logging_in": _logging_in, "fb_ready": facebook_logged_in(),
                  "message": _message, "notice": _notice}
        _notice = None
        return result


def import_cookies(path: str | Path) -> dict:
    global _logging_in, _message
    from backend.api import scan

    with _lock:
        if _logging_in:
            return fail("Đang đăng nhập Facebook. Vui lòng chờ hoàn tất.")
        if scan.is_running():
            return fail("Đang quét. Hãy dừng quét trước khi nạp cookie Facebook.")
        _logging_in = True
        _message = None
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="facebook-cookie") as executor:
            imported = executor.submit(facebook.import_cookies, Path(path)).result()
        if not imported:
            message = "Không tìm thấy cookie đăng nhập Facebook trong file. Hãy xuất cookie khi đã đăng nhập tài khoản phụ rồi thử lại."
            logger.warning("%s", message)
            return fail(message)
        return {"ok": True, "message": "Đã nạp cookie và lưu phiên Facebook."}
    except Exception as exc:
        return fail(error_message(exc))
    finally:
        with _lock:
            _logging_in = False
