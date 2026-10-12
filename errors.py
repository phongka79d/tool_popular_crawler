"""Business error types shared by all modules.

`message` is the Vietnamese text shown to the user (PLAN-JEV.md §9).
`service` is one of "jev", "deepgram", "llm", "facebook".
"""
from __future__ import annotations


class ServiceError(Exception):
    """Base class for failures caused by an external service."""

    def __init__(self, service: str, message: str) -> None:
        super().__init__(service, message)
        self.service = service
        self.message = message

    def __str__(self) -> str:
        return self.message


class AuthError(ServiceError):
    """Key is wrong, expired or revoked (HTTP 401/403)."""


class QuotaError(ServiceError):
    """Out of credit (HTTP 402 or out-of-credit 429), or rate limit still hit after all retries."""


class NotFoundError(ServiceError):
    """Endpoint or model name is wrong (HTTP 404)."""


class NetworkError(ServiceError):
    """Connection lost, timeout, or 5xx still failing after all retries."""


class LoginRequired(ServiceError):
    """Facebook: checkpoint, login page, or missing c_user/xs cookies."""


class BrowserUnavailable(ServiceError):
    """Facebook: the tool's browser profile is already open in another window or process."""
