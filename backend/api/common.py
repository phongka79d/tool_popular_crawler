"""Shared formatting and safe error messages for the desktop bridge."""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

from backend.core import applog, keys
from backend.core.errors import ServiceError

logger = logging.getLogger("app.api")
SERVICE_LABELS = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM"}


def format_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def int_text(value: float | None) -> str:
    return "—" if value is None else f"{round(value):,}".replace(",", ".")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    values = {*secrets, *(keys.get_key(name) for name in SERVICE_LABELS)}
    for secret in sorted((value for value in values if value), key=len, reverse=True):
        text = text.replace(secret, keys.mask(secret))
    return text


def error_message(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    applog.protect(secrets)
    if isinstance(exc, ServiceError):
        message = redact(str(exc), secrets)
        logger.warning("%s", message)
        return message
    logger.error("Lỗi không mong đợi: %s", type(exc).__name__, exc_info=exc)
    return ("Không thể hoàn tất thao tác. Kiểm tra kết nối, quyền truy cập và cấu hình rồi thử lại. "
            "Chi tiết trong Nhật ký.")


def is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value.strip())
        return parts.scheme in ("http", "https") and bool(parts.netloc)
    except ValueError:
        return False


def fail(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}
