from backend.collectors import facebook


def _position(options):
    return next(arg for arg in options["args"] if arg.startswith("--window-position="))


def test_hidden_scan_window_sits_just_right_of_all_screens(monkeypatch):
    monkeypatch.setattr(facebook, "_hidden_position", lambda: (1536, -120))
    options = facebook._launch_options(hidden=True)
    assert _position(options) == "--window-position=1536,-120"
    assert set(facebook.BACKGROUND_ARGS) <= set(options["args"])
    assert options["headless"] is False


def test_login_window_is_normal_and_language_is_never_forced(monkeypatch):
    monkeypatch.setattr(facebook, "_hidden_position", lambda: (1536, 0))
    login, scan = facebook._launch_options(hidden=False), facebook._launch_options(hidden=True)
    assert not any(arg.startswith("--window-position=") for arg in login["args"])
    assert "locale" not in login and "locale" not in scan


def test_hidden_position_falls_back_when_windows_api_is_unavailable(monkeypatch):
    import ctypes
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert facebook._hidden_position() == facebook.FALLBACK_HIDDEN_POSITION
