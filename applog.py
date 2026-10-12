"""Nhật ký ứng dụng: mọi thông báo và lỗi của một lần mở app nằm trong data/app.log.

Bản exe không có cửa sổ console, nên stdout/stderr (Streamlit, thư viện) cũng ghi vào file này.
Mỗi lần mở app, file cũ đổi tên thành app.prev.log để vẫn xem được lỗi của lần trước.
API key không bao giờ được ghi nguyên văn: mọi đường ghi vào file đều đi qua `redact`.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import config
import keys

LOG_FILE = config.DATA_DIR / "app.log"
PREVIOUS_LOG_FILE = config.DATA_DIR / "app.prev.log"
# Streamlit dùng cùng định dạng (logger.messageFormat trong launcher) để bộ lọc đọc được mức lỗi.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
PROBLEM_LEVELS = ("WARNING", "ERROR", "CRITICAL")
_NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "urllib3")
_RECORD_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) ")

log = logging.getLogger("app")
_configured = False

_SECRET_NAMES = ("jev", "deepgram", "llm")
_SECRET_REFRESH_S = 10.0
_MIN_SECRET_LEN = 8
_secret_cache: tuple[float, tuple[str, ...]] = (float("-inf"), ())
_extra_secrets: set[str] = set()
_refreshing = threading.local()


def protect(values: Iterable[str | None]) -> None:
    """Che thêm các chuỗi bí mật chưa lưu vào kho (ví dụ key đang được kiểm tra trong Cài đặt)."""
    _extra_secrets.update(v.strip() for v in values if v and len(v.strip()) >= _MIN_SECRET_LEN)


def _secrets() -> tuple[str, ...]:
    global _secret_cache
    checked_at, stored = _secret_cache
    now = time.monotonic()
    if now - checked_at >= _SECRET_REFRESH_S and not getattr(_refreshing, "active", False):
        _refreshing.active = True  # keys có thể ghi log khi kho bảo mật lỗi: không đọc lồng nhau
        try:
            values = []
            for name in _SECRET_NAMES:
                try:
                    values.append(keys.get_key(name))
                except Exception:  # noqa: BLE001 - kho bảo mật lỗi không được làm hỏng việc ghi log
                    pass
            stored = tuple(v for v in values if v and len(v) >= _MIN_SECRET_LEN)
            _secret_cache = (now, stored)
        finally:
            _refreshing.active = False
    return stored + tuple(_extra_secrets)


def redact(text: str) -> str:
    """Thay mọi API key đã biết bằng dạng che (••••abcd) trước khi ghi ra file hoặc hiện lên."""
    for secret in _secrets():
        if secret in text:
            text = text.replace(secret, keys.mask(secret))
    return text


class _RedactingStream:
    """File nhật ký che API key ở mọi đường ghi: logging, handler của Streamlit, print của thư viện."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(redact(text))
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def __getattr__(self, name: str):
        return getattr(self._stream, name)  # flush, fileno (subprocess), encoding, isatty...


def use_utf8_console() -> None:
    """Thông báo tiếng Việt không được làm hỏng chương trình trên console mã cũ (cp1252)."""
    for console in (sys.stdout, sys.stderr):
        if console is not None and hasattr(console, "reconfigure"):
            console.reconfigure(encoding="utf-8", errors="replace")


def setup() -> None:
    """Bật ghi nhật ký một lần cho cả tiến trình; gọi lại không làm gì.

    Gọi trước khi import Streamlit để handler của Streamlit (ghi vào sys.stderr) cũng ghi vào file.
    """
    global _configured
    if _configured:
        return
    _configured = True
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LOG_FILE.replace(PREVIOUS_LOG_FILE)
    except OSError:
        pass  # chưa có file, hoặc bản khác đang mở: ghi tiếp vào file hiện tại
    stream = _RedactingStream(open(LOG_FILE, "a", encoding="utf-8", errors="replace", buffering=1))  # noqa: SIM115
    handlers: list[logging.Handler] = [logging.StreamHandler(stream)]
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = stream  # exe không có console
    else:
        use_utf8_console()
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=handlers, force=True)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_uncaught
    log.info("Mở Video Công Thức (Python %s)", sys.version.split()[0])


def _log_uncaught(exc_type, exc, tb) -> None:
    log.critical("Lỗi không xử lý được", exc_info=(exc_type, exc, tb))


def _log_thread_uncaught(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    log.error("Lỗi trong luồng %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def read_records(problems_only: bool = False, path: Path | None = None) -> list[str]:
    """Các bản ghi trong file nhật ký, cũ trước. Traceback nhiều dòng thuộc bản ghi đứng trước nó.

    `problems_only`: chỉ giữ cảnh báo và lỗi (WARNING, ERROR, CRITICAL).
    """
    target = path or LOG_FILE
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    records: list[str] = []
    for line in text.splitlines():
        if _RECORD_START.match(line) or not records:
            records.append(line)
        else:
            records[-1] += "\n" + line
    if problems_only:
        records = [record for record in records if record_level(record) in PROBLEM_LEVELS]
    return records


def record_level(record: str) -> str | None:
    match = _RECORD_START.match(record)
    return match.group(1) if match else None
