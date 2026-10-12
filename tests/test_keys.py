"""Offline tests for keys.py. The keyring module is replaced by an in-memory stub."""
from __future__ import annotations

import sys
import types

import pytest

import keys

SERVICE = "VideoCongThuc"


def _backend(module_name: str, class_name: str = "Keyring") -> object:
    backend_cls = type(class_name, (), {"__module__": module_name})
    return backend_cls()


@pytest.fixture
def stub(monkeypatch) -> dict[tuple[str, str], str]:
    """Install an in-memory `keyring` module and return the dict that backs it."""
    store: dict[tuple[str, str], str] = {}
    module = types.ModuleType("keyring")

    def get_password(service: str, name: str) -> str | None:
        return store.get((service, name))

    def set_password(service: str, name: str, value: str) -> None:
        store[(service, name)] = value

    def delete_password(service: str, name: str) -> None:
        if (service, name) not in store:
            raise RuntimeError("không có key")
        del store[(service, name)]

    module.get_password = get_password
    module.set_password = set_password
    module.delete_password = delete_password
    module.get_keyring = lambda: _backend("keyring.backends.Windows", "WinVaultKeyring")
    monkeypatch.setitem(sys.modules, "keyring", module)
    return store


def test_set_then_get_round_trip_stores_trimmed_key(stub):
    keys.set_key("jev", "  sk-jev-test-a91f  ")
    assert keys.get_key("jev") == "sk-jev-test-a91f"
    assert stub[(SERVICE, "jev")] == "sk-jev-test-a91f"


def test_get_missing_key_returns_none(stub):
    assert keys.get_key("deepgram") is None


def test_missing_keys_tracks_saved_names(stub):
    assert keys.missing_keys() == ["jev", "deepgram", "llm"]
    keys.set_key("deepgram", "dg-secret-0001")
    assert keys.missing_keys() == ["jev", "llm"]


def test_delete_key_removes_value_and_tolerates_absent_key(stub):
    keys.set_key("llm", "llm-key-9999")
    keys.delete_key("llm")
    assert keys.get_key("llm") is None
    keys.delete_key("llm")  # already absent: no error


def test_blank_value_is_rejected_and_not_stored(stub):
    with pytest.raises(ValueError):
        keys.set_key("llm", "   ")
    assert stub == {}


def test_unknown_key_name_is_rejected(stub):
    with pytest.raises(ValueError):
        keys.get_key("facebook")
    with pytest.raises(ValueError):
        keys.set_key("facebook", "value")


def test_backend_read_failure_is_treated_as_missing(stub, monkeypatch):
    def broken(service: str, name: str) -> str:
        raise RuntimeError("no backend")

    monkeypatch.setattr(sys.modules["keyring"], "get_password", broken)
    assert keys.get_key("jev") is None
    assert keys.missing_keys() == ["jev", "deepgram", "llm"]


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("keyring.backends.fail", "Keyring"),
        ("keyring.backends.null", "Keyring"),
        ("keyring.backends.file", "PlaintextKeyring"),
    ],
    ids=["fail", "null", "plaintext"],
)
def test_storage_is_not_secure_for_fail_null_plaintext_backends(stub, monkeypatch, module_name, class_name):
    monkeypatch.setattr(
        sys.modules["keyring"], "get_keyring", lambda: _backend(module_name, class_name)
    )
    assert keys.storage_secure() is False


def test_storage_is_secure_for_windows_credential_manager(stub):
    assert keys.storage_secure() is True


def test_storage_is_not_secure_when_backend_lookup_fails(stub, monkeypatch):
    def broken() -> object:
        raise RuntimeError("no backend")

    monkeypatch.setattr(sys.modules["keyring"], "get_keyring", broken)
    assert keys.storage_secure() is False


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sk-proj-abcdefgh1234", "••••1234"),
        ("  sk-abc1234567  ", "••••4567"),
        ("12345678", "••••"),
        ("abc", "••••"),
        ("", ""),
        (None, ""),
    ],
)
def test_mask_shows_only_last_four_characters_of_long_keys(key, expected):
    assert keys.mask(key) == expected


def test_set_key_refuses_plaintext_backend_and_stores_nothing(stub, monkeypatch):
    monkeypatch.setattr(
        sys.modules["keyring"], "get_keyring", lambda: _backend("keyring.backends.file", "PlaintextKeyring")
    )
    with pytest.raises(RuntimeError):
        keys.set_key("jev", "sk-jev-test-a91f")
    assert stub == {}
