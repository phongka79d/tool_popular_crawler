from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.collectors import browser_setup


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


def test_frozen_install_keeps_browsers_in_data_dir_before_discovery(monkeypatch, tmp_path):
    executable = tmp_path / "chromium-1" / "chrome-win64" / "chrome.exe"
    run = chromium_mocks(monkeypatch, executable)
    monkeypatch.setattr(browser_setup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(browser_setup.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "other")
    expected = str(tmp_path / "data" / "browsers")
    from playwright import sync_api
    original_sync = sync_api.sync_playwright

    def sync_playwright():
        assert browser_setup.os.environ["PLAYWRIGHT_BROWSERS_PATH"] == expected
        return original_sync()

    monkeypatch.setattr(sync_api, "sync_playwright", sync_playwright)

    def install(command, **kwargs):
        assert command == ["node", "cli.js", "install", "chromium", "--no-shell"]
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == expected
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
