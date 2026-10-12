from pathlib import Path
from unittest.mock import Mock

import pytest

import browser_setup
import config
import launcher


def timeline(samples):
    state = launcher.WatchdogState(0)
    result = False
    for now, sessions, alive in samples:
        state, result = launcher.watchdog_decision(state, now, sessions, alive)
    return result


def test_disconnected_session_exits_after_idle_interval():
    assert not timeline([(1, 1, None), (2, 0, None), (16, 0, None)])
    assert timeline([(1, 1, None), (2, 0, None), (17, 0, None)])


def test_reload_resets_idle_timer():
    assert not timeline([(1, 1, None), (2, 0, None), (12, 1, None), (13, 0, None), (27, 0, None)])


def test_owned_process_exit_handles_stale_session_count():
    assert timeline([(1, 1, True), (6, 1, True), (7, 1, False), (22, 1, False)])


def test_short_lived_browser_handoff_is_not_a_window_close():
    assert not timeline([(1, 1, False), (6, 1, False), (130, 1, False)])
    assert timeline([(1, 1, False), (6, 0, False), (21, 0, False)])


@pytest.mark.parametrize("sessions", [0, None])
def test_no_session_ever_observed_times_out(sessions):
    assert not timeline([(119, sessions, None)])
    assert timeline([(120, sessions, None)])


def test_unknown_session_api_can_still_use_owned_process():
    assert timeline([(6, None, True), (7, None, False), (22, None, False)])


def test_active_sessions_do_not_time_out():
    assert not timeline([(1, 1, None), (121, 1, None)])


def browser_mocks(monkeypatch, edge):
    monkeypatch.setattr(config, "edge_path", lambda: edge)
    install = Mock(return_value=Path("chromium.exe"))
    popen = Mock(return_value=Mock())
    fallback = Mock(return_value=True)
    monkeypatch.setattr(browser_setup, "ensure_chromium", install)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher.webbrowser, "open", fallback)
    return install, popen, fallback


def test_edge_present_does_not_install_chromium(monkeypatch):
    install, popen, fallback = browser_mocks(monkeypatch, "edge.exe")
    assert launcher.open_browser("http://127.0.0.1:9999") is popen.return_value
    assert popen.call_args.args[0][0] == "edge.exe"
    install.assert_not_called()
    fallback.assert_not_called()


def test_edge_absent_installs_before_launching_chromium(monkeypatch):
    install, popen, fallback = browser_mocks(monkeypatch, None)
    calls = []
    install.side_effect = lambda: calls.append("install") or Path("chromium.exe")
    popen.side_effect = lambda command: calls.append(command) or popen.return_value
    launcher.open_browser("http://127.0.0.1:9999")
    assert calls == ["install", ["chromium.exe", "--app=http://127.0.0.1:9999", "--window-size=1280,900"]]
    fallback.assert_not_called()


@pytest.mark.parametrize("failure", ["install", "launch"])
def test_chromium_failure_uses_default_browser(monkeypatch, failure):
    install, popen, fallback = browser_mocks(monkeypatch, None)
    (install if failure == "install" else popen).side_effect = OSError("offline")
    assert launcher.open_browser("http://127.0.0.1:9999") is None
    fallback.assert_called_once_with("http://127.0.0.1:9999")


def test_edge_launch_failure_tries_chromium(monkeypatch):
    install, popen, fallback = browser_mocks(monkeypatch, "edge.exe")
    process = Mock()
    popen.side_effect = [OSError("unavailable"), process]
    assert launcher.open_browser("http://127.0.0.1:9999") is process
    install.assert_called_once()
    fallback.assert_not_called()


def test_partial_chromium_install_is_not_accepted(tmp_path):
    executable = tmp_path / "chromium-1" / "chrome-win64" / "chrome.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert not browser_setup.browsers_installed(executable)
    (executable.parents[1] / "INSTALLATION_COMPLETE").touch()
    assert browser_setup.browsers_installed(executable)


def chromium_mocks(monkeypatch, executable):
    from playwright import sync_api
    from playwright._impl import _driver
    playwright = Mock()
    playwright.chromium.executable_path = str(executable)
    context = Mock()
    context.__enter__ = Mock(return_value=playwright)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: context)
    monkeypatch.setattr(_driver, "compute_driver_executable", lambda: ("node", "cli.js"))
    monkeypatch.setattr(_driver, "get_driver_env", lambda: dict(browser_setup.os.environ))
    run = Mock()
    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    return run


def test_completed_chromium_install_is_reused(monkeypatch, tmp_path):
    executable = tmp_path / "chromium-1" / "chrome-win64" / "chrome.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    (executable.parents[1] / "INSTALLATION_COMPLETE").touch()
    run = chromium_mocks(monkeypatch, executable)
    assert browser_setup.ensure_chromium() == executable
    run.assert_not_called()


def test_frozen_install_uses_local_browser_path_before_discovery(monkeypatch, tmp_path):
    executable = tmp_path / "chromium-1" / "chrome-win64" / "chrome.exe"
    run = chromium_mocks(monkeypatch, executable)
    monkeypatch.setattr(browser_setup.sys, "frozen", True, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "other")
    from playwright import sync_api
    original_sync = sync_api.sync_playwright

    def sync_playwright():
        assert browser_setup.os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"
        return original_sync()

    monkeypatch.setattr(sync_api, "sync_playwright", sync_playwright)

    def install(command, **kwargs):
        assert command == ["node", "cli.js", "install", "chromium", "--no-shell"]
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "0"
        executable.parent.mkdir(parents=True)
        executable.touch()
        (executable.parents[1] / "INSTALLATION_COMPLETE").touch()
        return Mock(returncode=0)

    run.side_effect = install
    assert browser_setup.ensure_chromium() == executable


def test_failed_download_raises_without_accepting_missing_executable(monkeypatch, tmp_path):
    executable = tmp_path / "chromium-1" / "chrome-win64" / "chrome.exe"
    run = chromium_mocks(monkeypatch, executable)
    run.return_value.returncode = 1
    with pytest.raises(RuntimeError):
        browser_setup.ensure_chromium()
