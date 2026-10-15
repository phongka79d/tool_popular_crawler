from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.api import app_state, channels, common, logs, services, taxonomy
from backend.core import config
from backend.core.errors import ServiceError


@pytest.fixture(autouse=True)
def settings_environment(monkeypatch, tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "CONFIG_DIR", directory)
    monkeypatch.setattr(config, "SETTINGS_FILE", directory / "settings.json")
    monkeypatch.setattr(config, "COOKIE_FILE", tmp_path / "fb_cookies.txt")
    config.save_settings(deepcopy(services.DEFAULT_SETTINGS))
    stored = {}
    monkeypatch.setattr(services.keys, "get_key", stored.get)
    monkeypatch.setattr(services.keys, "set_key", lambda name, value: stored.__setitem__(name, value))
    monkeypatch.setattr(services.keys, "delete_key", lambda name: stored.pop(name, None))
    monkeypatch.setattr(services.keys, "storage_secure", lambda: True)
    return stored


def test_channels_save_preserves_comments_and_reload():
    text = "# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\n\nhttps://www.facebook.com/another.page\n"
    result = channels.save_channels(text)
    expected = "# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\nhttps://www.facebook.com/another.page\n"
    assert result["ok"] and result["count"] == 2
    assert (config.CONFIG_DIR / "channels.txt").read_text(encoding="utf-8") == expected
    assert config.load_lines("config/channels.txt") == [
        "https://www.facebook.com/pharmacy.page", "https://www.facebook.com/another.page"]
    assert channels.get_channels() == {"ok": True, "text": expected, "count": 2, "problems": []}
    assert channels.saved_channels() == config.load_lines("config/channels.txt")


def test_channels_reject_group_without_writing():
    path = config.CONFIG_DIR / "channels.txt"
    original = "# Giữ lại\nhttps://www.facebook.com/pharmacy.page\n"
    path.write_text(original, encoding="utf-8")
    result = channels.save_channels("https://www.facebook.com/groups/123456")
    assert not result["ok"] and result["problems"]
    assert path.read_text(encoding="utf-8") == original


def test_saved_channels_skip_invalid_and_comments():
    (config.CONFIG_DIR / "channels.txt").write_text(
        "# note\nhttps://www.facebook.com/groups/123\nhttps://www.facebook.com/page\n", encoding="utf-8")
    assert channels.saved_channels() == ["https://www.facebook.com/page"]
    assert channels.get_channels()["problems"]


def test_service_settings_write_failure_never_changes_key(monkeypatch):
    monkeypatch.setattr(services, "_check_selection", lambda *args: None)
    writes = []
    monkeypatch.setattr(services.keys, "set_key", lambda *args: writes.append(args))
    settings = deepcopy(services.DEFAULT_SETTINGS)
    original = deepcopy(settings)
    monkeypatch.setattr(config, "load_settings", lambda: settings)

    def fail_save(value):
        raise OSError("disk full")

    monkeypatch.setattr(config, "save_settings", fail_save)
    result = services.save_service("llm", "test-secret", {"model": "m-1", "base_url": "https://llm.test/v1"})
    assert not result["ok"]
    assert writes == []
    assert settings == original


def test_service_saves_settings_before_key(monkeypatch):
    events = []
    monkeypatch.setattr(services, "_check_selection", lambda *args: events.append(("check", None)))
    monkeypatch.setattr(config, "save_settings", lambda value: events.append(("settings", deepcopy(value))))
    monkeypatch.setattr(services.keys, "set_key", lambda *args: events.append(("key", args)))
    result = services.save_service("llm", "test-secret", {"model": "m-1", "base_url": "https://llm.test/v1"})
    assert result["ok"]
    assert [event[0] for event in events] == ["check", "settings", "key"]
    assert events[1][1]["llm"]["model"] == "m-1"


def test_empty_key_uses_saved_key_for_connect_and_save(monkeypatch, settings_environment):
    settings_environment["jev"] = "saved-test-secret"
    calls = []
    monkeypatch.setattr(services.jev_client, "list_models", lambda key: calls.append(key) or [
        {"name": "jev-model", "description": "", "release_date": ""}])
    monkeypatch.setattr(services.jev_client, "check_key", lambda *args: calls.append(args))
    assert services.connect_service("jev", "", "")["ok"]
    assert services.save_service("jev", "", {"model": "jev-model"})["ok"]
    assert calls == ["saved-test-secret", ("saved-test-secret", "jev-model")]


@pytest.mark.parametrize("secure,key,selection", [
    (False, "candidate", {"model": "m", "base_url": "https://test/v1"}),
    (True, "", {"model": "m", "base_url": "https://test/v1"}),
    (True, "candidate", {"model": "m", "base_url": "file:///test"}),
])
def test_save_validation_precedes_service_call(monkeypatch, secure, key, selection):
    monkeypatch.setattr(services.keys, "storage_secure", lambda: secure)
    monkeypatch.setattr(services, "_check_selection", lambda *args: pytest.fail("must not check"))
    assert not services.save_service("llm", key, selection)["ok"]


@pytest.mark.parametrize("key,url", [("", "https://test/v1"), ("candidate", "file:///test")])
def test_connect_validates_before_fetch(monkeypatch, key, url):
    monkeypatch.setattr(services, "_fetch_models", lambda *args: pytest.fail("must not fetch"))
    assert not services.connect_service("llm", key, url)["ok"]


def test_connect_rejects_empty_models(monkeypatch):
    monkeypatch.setattr(services, "_fetch_models", lambda *args: [])
    assert not services.connect_service("jev", "candidate", "")["ok"]


@pytest.mark.parametrize("saved,index", [("nova-3-b", 1), ("nova-3", 1), ("missing", 0), ("", 0)])
def test_deepgram_default_index_legacy_architecture(saved, index):
    items = [{"name": "nova-2-a", "architecture": "nova-2"},
             {"name": "nova-3-b", "architecture": "nova-3"},
             {"name": "nova-3-c", "architecture": "nova-3"}]
    assert services._deepgram_index(items, saved) == index


@pytest.mark.parametrize("codes,saved,expected", [
    (["en", "vi"], "en", "vi"), (["en", "fr"], "fr", "fr"), (["en", "fr"], "de", "en"),
])
def test_connect_deepgram_language_and_legacy_default(monkeypatch, codes, saved, expected):
    settings = config.load_settings()
    settings["stt"].update(model="nova-3", language=saved)
    config.save_settings(settings)
    monkeypatch.setattr(services.transcript, "list_deepgram_models", lambda key: [
        {"name": "nova-2-a", "architecture": "nova-2", "languages": [{"code": "en", "label": "English"}]},
        {"name": "nova-3-b", "architecture": "nova-3", "languages": [{"code": code, "label": code} for code in codes]}])
    result = services.connect_service("deepgram", "candidate", "")
    assert result["ok"] and result["count"] == 2
    assert result["default_id"] == "nova-3-b"
    assert result["default_language"] == expected


def test_llm_option_label_includes_prices_and_context():
    label = services._llm_option_label({"id": "m", "price_in": 0.125, "price_out": None, "context_length": 200000})
    assert "0,125" in label and "200.000" in label and "không rõ" in label
    unknown = services._llm_option_label({"id": "m", "price_in": None, "price_out": None})
    assert "nhà cung cấp không công bố" in unknown


def test_get_services_masks_keys_and_reports_configuration(settings_environment):
    settings_environment.update(jev="jev-secret-long", deepgram="deepgram-secret-long", llm="llm-secret-long")
    settings = config.load_settings()
    settings["jev"]["model"] = "jev-model"
    settings["llm"].update(model="llm-model", base_url=services.LLM_PROVIDERS["OpenAI"])
    config.save_settings(settings)
    result = services.get_services()
    rows = {row["name"]: row for row in result["services"]}
    assert rows["jev"]["configured"] and rows["llm"]["configured"]
    assert rows["deepgram"]["needs_model"] and not rows["deepgram"]["configured"]
    assert rows["llm"]["llm"]["provider_label"] == "OpenAI"
    assert rows["deepgram"]["deepgram"]["auto_language"] is True
    for key in settings_environment.values():
        assert key not in str(result)


def test_check_keys_redacts_reasons_and_optional_deepgram(monkeypatch, settings_environment):
    settings_environment["llm"] = "private-test-key"
    calls = []

    def check(settings, *, require_deepgram):
        calls.append(require_deepgram)
        return {"jev": None, "llm": "failed private-test-key"}

    monkeypatch.setattr(services.pipeline, "check_all_keys", check)
    result = services.check_keys(False)
    assert result["ok"] and calls == [False]
    assert set(result["status"]) == {"jev", "llm"}
    assert "private-test-key" not in str(result)
    assert result["status"]["jev"] is None


def test_reset_clears_keys_settings_channels_but_preserves_other_data(settings_environment, tmp_path):
    settings_environment.update({name: "saved-secret" for name in common.SERVICE_LABELS})
    cookie = config.COOKIE_FILE
    cookie.write_text("session", encoding="utf-8")
    output = tmp_path / "kept.xlsx"
    output.write_bytes(b"result")
    (config.CONFIG_DIR / "channels.txt").write_text("page", encoding="utf-8")
    settings = config.load_settings()
    settings["llm"]["model"] = "old-model"
    config.save_settings(settings)
    assert services.reset_configuration()["ok"]
    assert settings_environment == {}
    assert config.load_settings() == services.DEFAULT_SETTINGS
    assert (config.CONFIG_DIR / "channels.txt").read_text(encoding="utf-8") == ""
    assert cookie.read_text(encoding="utf-8") == "session"
    assert output.read_bytes() == b"result"


def _guide(**kwargs):
    values = dict(configured={"jev": False, "deepgram": False, "llm": False},
                  channel_count=0, fb_ready=False, running=False, has_result=False, question=False)
    values.update(kwargs)
    return app_state._Guide(**values)


@pytest.mark.parametrize("guide,states,page", [
    (_guide(), ["current", "pending", "pending"], "settings"),
    (_guide(configured={"jev": True, "llm": True, "deepgram": False}), ["done", "current", "pending"], "settings"),
    (_guide(configured={"jev": True, "llm": True, "deepgram": False}, channel_count=1, fb_ready=True), ["done", "done", "current"], "scan"),
    (_guide(configured={"jev": True, "llm": True, "deepgram": False}, channel_count=1, fb_ready=True, has_result=True), ["done", "done", "done"], "results"),
    (_guide(running=True), ["current", "pending", "current"], "scan"),
    (_guide(question=True), ["current", "pending", "pending"], "scan"),
])
def test_journey_and_next_step_states(guide, states, page):
    assert [step["state"] for step in app_state._journey(guide)] == states
    assert app_state._next_step(guide)["page"] == page


def test_question_takes_precedence_over_running_and_missing():
    guide = _guide(question=True, running=True)
    assert app_state._next_step(guide)["page"] == "scan"
    assert guide.missing == ["Jev", "LLM"]
    assert not guide.setup_done


def test_get_app_state_combines_scan_login_and_setup(monkeypatch, settings_environment):
    from backend.api import scan

    settings_environment.update(jev="saved-jev", llm="saved-llm")
    settings = config.load_settings()
    settings["jev"]["model"] = "jev-model"
    settings["llm"].update(model="llm-model", base_url="https://test/v1")
    config.save_settings(settings)
    monkeypatch.setattr(channels, "saved_channels", lambda: ["page"])
    monkeypatch.setattr(channels, "facebook_logged_in", lambda: True)
    monkeypatch.setattr(channels, "is_logging_in", lambda: True)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    monkeypatch.setattr(scan, "has_question", lambda: False)
    monkeypatch.setattr(scan, "has_result", lambda: False)
    result = app_state.get_app_state()
    assert result["ok"] and result["busy"] and result["logging_in"]
    assert result["guide"]["setup_done"] and not result["scan_locked"]
    assert not app_state.scan_locked()


def test_prepare_browser_uses_edge_or_download_and_records_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "edge_path", lambda: "edge.exe")
    monkeypatch.setattr(app_state.browser_setup, "ensure_chromium", lambda: calls.append(True))
    app_state.prepare_browser()
    assert app_state._browser_ready and not calls
    monkeypatch.setattr(config, "edge_path", lambda: None)
    app_state.prepare_browser()
    assert app_state._browser_ready and calls == [True]

    def fail_download():
        raise OSError("offline")

    monkeypatch.setattr(app_state.browser_setup, "ensure_chromium", fail_download)
    app_state.prepare_browser()
    assert not app_state._browser_ready and app_state._browser_error


def test_get_logs_ordering_redaction_limit_and_sessions(monkeypatch, tmp_path):
    current, previous = tmp_path / "app.log", tmp_path / "app.prev.log"
    previous.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(logs.applog, "LOG_FILE", current)
    monkeypatch.setattr(logs.applog, "PREVIOUS_LOG_FILE", previous)
    calls = []

    def records(problems_only, path):
        calls.append((problems_only, path))
        return [f"{index}: secret" for index in range(510)]

    monkeypatch.setattr(logs.applog, "read_records", records)
    monkeypatch.setattr(logs.applog, "redact", lambda value: value.replace("secret", "masked"))
    result = logs.get_logs("previous", False)
    assert result["ok"] and result["session"] == "previous"
    assert calls == [(False, previous)]
    assert [entry["id"] for entry in result["sessions"]] == ["current", "previous"]
    assert len(result["records"]) == 500
    assert result["records"][0] == "509: masked"
    assert result["records"][-1] == "10: masked"
    assert "secret" not in str(result)


def test_get_logs_missing_previous_falls_back_to_current(monkeypatch, tmp_path):
    monkeypatch.setattr(logs.applog, "LOG_FILE", tmp_path / "app.log")
    monkeypatch.setattr(logs.applog, "PREVIOUS_LOG_FILE", tmp_path / "absent.log")
    result = logs.get_logs("previous")
    assert result["session"] == "current" and result["records"] == []
    assert len(result["sessions"]) == 1


def test_redact_replaces_overlapping_keys_longest_first(settings_environment):
    settings_environment["jev"] = "abcdefghi"
    settings_environment["llm"] = "abcdefghi-longer"
    result = common.redact("abcdefghi-longer abcdefghi candidate-secret", ("candidate-secret",))
    assert "abcdefghi" not in result and "candidate-secret" not in result and "-longer" not in result


def test_error_message_redacts_expected_errors_and_hides_unexpected(monkeypatch):
    monkeypatch.setattr(common.applog, "protect", lambda values: None)
    assert "candidate-secret" not in common.error_message(ServiceError("llm", "candidate-secret"), ("candidate-secret",))
    assert "private detail" not in common.error_message(RuntimeError("private detail"))


@pytest.mark.parametrize("url,valid", [("https://example.com/v1", True), ("http://localhost:123/v1", True),
                                      ("file:///tmp", False), ("https://", False), ("http://[bad", False)])
def test_endpoint_validation(url, valid):
    assert common.is_http_url(url) is valid


def test_taxonomy_groups_include_plain_notes_editable_rows_and_fixed_labels(monkeypatch):
    source = {"labels": {"one": "Một", "two": "Hai", "khac": "Khác", "khong_co": "Không có CTA"},
              **{group: {"one": "a", "two": "b", "khac": "other"} for group in config.TAXONOMY_GROUPS}}
    source["cta"]["khong_co"] = "none"
    monkeypatch.setattr(config, "load_taxonomy", lambda: source)
    result = taxonomy.get_taxonomy()
    assert result["ok"] and len(result["intro"]) == 5
    assert [group["id"] for group in result["groups"]] == list(config.TAXONOMY_GROUPS)
    assert all("**" not in group["note"] and len(group["rows"]) == 2 for group in result["groups"])
    assert result["groups"][-1]["fixed"] == ["Không có CTA", "Khác"]


@pytest.mark.parametrize("exception", [ValueError("invalid"), OSError("unwritable")])
def test_save_taxonomy_reports_validation_and_storage_errors(monkeypatch, exception):
    def fail_save(groups):
        raise exception

    monkeypatch.setattr(config, "save_taxonomy", fail_save)
    assert taxonomy.save_taxonomy({}) == {"ok": False, "error": str(exception)}


def test_login_admission_prevents_duplicate_and_scan_overlap(monkeypatch):
    from backend.api import scan

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(channels, "_message", None)
    monkeypatch.setattr(channels, "_notice", None)
    monkeypatch.setattr(scan, "is_running", lambda: True)
    assert not channels.start_login()["ok"]
    assert not channels.is_logging_in()
    monkeypatch.setattr(scan, "is_running", lambda: False)
    workers = []
    monkeypatch.setattr(channels.threading, "Thread", lambda **kwargs:
                        SimpleNamespace(start=lambda: workers.append(kwargs)))
    assert channels.start_login()["ok"]
    assert channels.is_logging_in()
    assert not channels.start_login()["ok"]
    assert len(workers) == 1 and workers[0]["daemon"] is True


def test_login_worker_publishes_notice_once(monkeypatch):
    monkeypatch.setattr(channels, "_logging_in", True)
    monkeypatch.setattr(channels, "_message", "old")
    monkeypatch.setattr(channels, "_notice", None)
    monkeypatch.setattr(channels.facebook, "login_interactive", lambda: True)
    monkeypatch.setattr(channels, "facebook_logged_in", lambda: True)
    channels._login_worker()
    first = channels.get_login_state()
    assert first["ok"] and first["fb_ready"] and not first["logging_in"]
    assert first["message"] is None and first["notice"]
    assert channels.get_login_state()["notice"] is None


def test_cookie_import_runs_off_calling_thread_and_keeps_source(monkeypatch, tmp_path):
    from backend.api import scan
    import threading

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    path = tmp_path / "cookies.json"
    path.write_text("[]", encoding="utf-8")
    caller = threading.get_ident()
    calls = []

    def imported(source):
        calls.append((source, threading.get_ident()))
        return True

    monkeypatch.setattr(channels.facebook, "import_cookies", imported)
    assert channels.import_cookies(path)["ok"]
    assert calls[0][0] == path and calls[0][1] != caller
    assert path.exists() and not channels.is_logging_in()


def test_cookie_import_without_login_cookies_fails(monkeypatch, tmp_path):
    from backend.api import scan

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    monkeypatch.setattr(channels.facebook, "import_cookies", lambda path: False)
    assert not channels.import_cookies(tmp_path / "empty.json")["ok"]
    assert not channels.is_logging_in()


def test_channels_write_error_does_not_claim_success(monkeypatch):
    def denied(path, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", denied)
    assert not channels.save_channels("https://www.facebook.com/page")["ok"]


def test_open_log_failure_returns_failure(monkeypatch):
    def denied(path):
        raise OSError("denied")

    monkeypatch.setattr(logs.os, "startfile", denied, raising=False)
    assert not logs.open_log_file("current")["ok"]
