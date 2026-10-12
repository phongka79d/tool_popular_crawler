"""Retry policy for external API calls. Failures are mapped to ServiceError (PLAN-JEV.md §9, §11.5).

Adapted from videoanalyzer `scripts/whisper.py` (`_post_whisper`, `_retry_after`):
- Other 4xx (not 429/529): re-raise the original error at once; retrying cannot help.
- 429/529: honor `Retry-After`, otherwise double the delay. After `max_rate_retries` retries: QuotaError.
  A 429 whose body reports out-of-credit (e.g. `insufficient_quota`) is QuotaError at once.
- 5xx, lost connection, timeout: double the delay. After `max_net_retries` retries: NetworkError.

`max_*_retries` count retries after the first call, so one call makes at most 1 + max attempts.

Classification is duck-typed, so this module does not import requests, openai or typesafe_sdk:
- status: `.status_code` (openai, typesafe_sdk), else `.response.status_code` (requests), else the class name;
- connection/timeout: class names in the MRO (requests, openai, typesafe_sdk).
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

from errors import AuthError, NetworkError, NotFoundError, QuotaError, ServiceError

logger = logging.getLogger(__name__)

T = TypeVar("T")

RATE_LIMIT_STATUSES = frozenset({429, 529})  # 529: Jev overloaded

_SERVICE_LABELS = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM", "facebook": "Facebook"}

# SDK error classes (openai, typesafe_sdk use the same names) that may lack a status attribute.
_STATUS_BY_CLASS_NAME = {
    "BadRequestError": 400,
    "AuthenticationError": 401,
    "PermissionDeniedError": 403,
    "NotFoundError": 404,
    "RateLimitError": 429,
    "InternalServerError": 500,
}

# Connection and timeout classes: requests (ConnectionError, Timeout and subclasses),
# openai and typesafe_sdk (APIConnectionError, APITimeoutError). Matched by name in the MRO.
_NETWORK_CLASS_NAMES = frozenset(
    {"ConnectionError", "APIConnectionError", "Timeout", "APITimeoutError", "TimeoutError"}
)

# Body markers of a 429 caused by an empty credit balance: retrying will not help.
_OUT_OF_CREDIT_MARKERS = ("insufficient_quota", "billing_hard_limit_reached", "credit balance")


def with_retry(
    fn: Callable[[], T],
    *,
    service: str,
    max_rate_retries: int = 5,
    max_net_retries: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn()`, retry transient failures, and raise ServiceError for persistent ones.

    Non-transient errors are re-raised unchanged, and so is any ServiceError raised by `fn`.
    """
    rate_retries = 0
    net_retries = 0
    while True:
        try:
            return fn()
        except ServiceError:
            raise
        except Exception as exc:
            status = _status_of(exc)
            body = _body_of(exc)
            kind = _transient_kind(exc, status, body)
            if kind == "rate":
                if rate_retries >= max_rate_retries:
                    raise QuotaError(service, _quota_message(service)) from exc
                delay = _retry_after(exc)
                if delay is None:
                    delay = base_delay * 2**rate_retries
                rate_retries += 1
                logger.warning(
                    "%s: HTTP %s, thử lại sau %.1f giây (lần %d/%d)",
                    service, status, delay, rate_retries, max_rate_retries,
                )
                sleep(delay)
            elif kind == "net":
                if net_retries >= max_net_retries:
                    raise NetworkError(service, _network_message(service)) from exc
                delay = base_delay * 2**net_retries
                net_retries += 1
                logger.warning(
                    "%s: lỗi %s, thử lại sau %.1f giây (lần %d/%d)",
                    service, status or type(exc).__name__, delay, net_retries, max_net_retries,
                )
                sleep(delay)
            else:
                mapped = classify_status(service, status, body) if status is not None else None
                if mapped is None:
                    raise
                raise mapped from exc


def classify_status(service: str, status: int, body: str = "") -> ServiceError | None:
    """Map a final HTTP status to a ServiceError, or None when the status should not be converted.

    Plain 429/529 return None because they are transient; `with_retry` retries them.
    A 429 whose body reports out-of-credit is QuotaError.
    """
    if status in (401, 403):
        return AuthError(service, _auth_message(service))
    if status == 402 or (status in RATE_LIMIT_STATUSES and _is_out_of_credit(body)):
        return QuotaError(service, _quota_message(service))
    if status == 404:
        return NotFoundError(service, _not_found_message(service))
    if 500 <= status < 600 and status not in RATE_LIMIT_STATUSES:
        return NetworkError(service, _network_message(service))
    return None


def parse_retry_after(value: str) -> float | None:
    """Seconds to wait from a Retry-After value (delta-seconds or HTTP-date). None if unreadable."""
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def _status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)  # typesafe_sdk TypeSafeAPIError
    if status is None:
        return _STATUS_BY_CLASS_NAME.get(type(exc).__name__)
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _body_of(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    if body is None:
        try:
            body = getattr(getattr(exc, "response", None), "text", None)
        except Exception:  # e.g. httpx ResponseNotRead: the body simply isn't available
            body = None
    return "" if body is None else str(body)


def _retry_after(exc: BaseException) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(exc, "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    return parse_retry_after(str(value)) if value else None


def _is_out_of_credit(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in _OUT_OF_CREDIT_MARKERS)


def _is_network_error(exc: BaseException) -> bool:
    return any(cls.__name__ in _NETWORK_CLASS_NAMES for cls in type(exc).__mro__)


def _transient_kind(exc: BaseException, status: int | None, body: str) -> str | None:
    """'rate' (429/529 with retry budget left), 'net' (5xx, lost connection, timeout), or None."""
    if status is None:
        return "net" if _is_network_error(exc) else None
    if status in RATE_LIMIT_STATUSES:
        return None if _is_out_of_credit(body) else "rate"
    if status >= 500:
        return "net"
    return None


def _label(service: str) -> str:
    return _SERVICE_LABELS.get(service, service)


def _auth_message(service: str) -> str:
    if service == "facebook":
        return "Phiên Facebook không hợp lệ hoặc đã hết hạn. Vào Cài đặt để đăng nhập lại."
    return f"API key [{_label(service)}] không hợp lệ. Vào Cài đặt để nhập lại."


def _quota_message(service: str) -> str:
    return f"Tài khoản [{_label(service)}] đã hết credit/hạn mức."


def _not_found_message(service: str) -> str:
    return (
        f"Không tìm thấy endpoint hoặc model {_label(service)}. "
        "Kiểm tra lại địa chỉ và tên model."
    )


def _network_message(service: str) -> str:
    return f"Không kết nối được tới [{_label(service)}]."
