"""API key storage in the OS credential store, through `keyring`. Keys are never written to plaintext files."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "VideoCongThuc"
KEY_NAMES: tuple[str, ...] = ("jev", "deepgram", "llm")

_MASK_PREFIX = "••••"
_MASK_MAX_HIDDEN_LENGTH = 8  # keys this short show no characters at all
_INSECURE_BACKEND_MARKERS = ("fail", "null", "plaintext")


def _keyring():
    # Imported lazily so the module loads without a live backend; tests stub this module.
    import keyring

    return keyring


def _check_name(name: str) -> None:
    if name not in KEY_NAMES:
        raise ValueError(f"Tên key không hợp lệ: {name!r}")


def get_key(name: str) -> str | None:
    """Return the stored key, or None if it is absent or the backend cannot be read."""
    _check_name(name)
    try:
        value = _keyring().get_password(SERVICE_NAME, name)
    except Exception as exc:
        # Treated as missing, so the UI asks for the key and storage_secure() warns the user.
        logger.warning("Không đọc được key [%s] từ kho bảo mật: %s", name, type(exc).__name__)
        return None
    return value or None


def set_key(name: str, value: str) -> None:
    """Store a key after trimming whitespace. Refuses insecure backends (never plaintext); backend errors propagate."""
    _check_name(name)
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"API key [{name}] đang trống.")
    if not storage_secure():
        raise RuntimeError(
            "Kho bảo mật của hệ điều hành không an toàn hoặc không khả dụng. "
            "Không lưu key dạng chữ thường."
        )
    _keyring().set_password(SERVICE_NAME, name, cleaned)
    logger.info("Đã lưu key [%s]: %s", name, mask(cleaned))


def delete_key(name: str) -> None:
    """Remove a stored key. Does nothing if it is absent."""
    _check_name(name)
    kr = _keyring()
    if kr.get_password(SERVICE_NAME, name) is not None:
        kr.delete_password(SERVICE_NAME, name)


def missing_keys() -> list[str]:
    """Names of the keys that are not stored yet, in KEY_NAMES order."""
    return [name for name in KEY_NAMES if not get_key(name)]


def mask(key: str | None) -> str:
    """Display form of a key: '••••' plus its last 4 characters, e.g. '••••a91f'.

    Empty input gives ''. Keys of 8 characters or fewer show only '••••'.
    """
    cleaned = (key or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= _MASK_MAX_HIDDEN_LENGTH:
        return _MASK_PREFIX
    return _MASK_PREFIX + cleaned[-4:]


def storage_secure() -> bool:
    """False when keyring has no real secure backend (fail, null or plaintext).

    The UI shows a warning in that case. Keys are never saved to a file as a fallback.
    """
    try:
        backend = _keyring().get_keyring()
    except Exception as exc:
        logger.warning("Không xác định được kho bảo mật của keyring: %s", type(exc).__name__)
        return False
    qualified = f"{type(backend).__module__}.{type(backend).__qualname__}".lower()
    return not any(marker in qualified for marker in _INSECURE_BACKEND_MARKERS)
