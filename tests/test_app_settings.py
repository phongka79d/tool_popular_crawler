from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app


class SettingsUI:
    def __init__(self, text=None, submit=False):
        self.text = text
        self.submit = submit
        self.saved_value = None
        self.errors = []
        self.reruns = 0
        self.session_state = SimpleNamespace()

    def container(self, **kwargs):
        return nullcontext()

    def form(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args):
        return nullcontext()

    def markdown(self, *args):
        pass

    def caption(self, *args):
        pass

    def warning(self, *args):
        pass

    def text_area(self, *args, **kwargs):
        self.saved_value = kwargs['value']
        return self.text if self.text is not None else self.saved_value

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    def error(self, message):
        self.errors.append(message)

    def rerun(self):
        self.reruns += 1


@pytest.fixture
def channels_root(monkeypatch, tmp_path):
    directory = tmp_path / 'config'
    directory.mkdir()
    monkeypatch.setattr(app.config, 'ROOT', tmp_path)
    monkeypatch.setattr(app.config, 'CONFIG_DIR', directory)
    return directory / 'channels.txt'


def test_channels_save_preserves_comments_and_reload(monkeypatch, channels_root):
    text = '# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\n\nhttps://www.facebook.com/another.page\n'
    ui = SettingsUI(text, submit=True)
    monkeypatch.setattr(app, 'st', ui)
    app._channels_section(False)
    expected = '# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\nhttps://www.facebook.com/another.page\n'
    assert channels_root.read_text(encoding='utf-8') == expected
    assert app.config.load_lines('config/channels.txt') == [
        'https://www.facebook.com/pharmacy.page', 'https://www.facebook.com/another.page',
    ]
    assert ui.reruns == 1
    reloaded = SettingsUI()
    monkeypatch.setattr(app, 'st', reloaded)
    app._channels_section(False)
    assert reloaded.saved_value == expected


def test_channels_reject_group_without_writing(monkeypatch, channels_root):
    original = '# Giữ lại\nhttps://www.facebook.com/pharmacy.page\n'
    channels_root.write_text(original, encoding='utf-8')
    ui = SettingsUI('https://www.facebook.com/groups/123456', submit=True)
    monkeypatch.setattr(app, 'st', ui)
    monkeypatch.setattr(app, '_show_error', lambda message, *args: ui.errors.append(message))
    app._channels_section(False)
    assert ui.errors
    assert not ui.reruns
    assert channels_root.read_text(encoding='utf-8') == original


def test_service_settings_write_failure_never_changes_key(monkeypatch):
    ui = SettingsUI()
    monkeypatch.setattr(app, 'st', ui)
    monkeypatch.setattr(app.keys, 'storage_secure', lambda: True)
    monkeypatch.setattr(app, '_check_selection', lambda *args: None)
    writes = []
    monkeypatch.setattr(app.keys, 'set_key', lambda *args: writes.append(args))
    def fail_save(settings):
        raise OSError('disk full')
    monkeypatch.setattr(app.config, 'save_settings', fail_save)
    settings = deepcopy(app.DEFAULT_SETTINGS)
    original = deepcopy(settings)
    app._save_service('llm', 'test-secret', settings, {'model': 'm-1', 'base_url': 'https://llm.test/v1'})
    assert writes == []
    assert settings == original
    assert ui.errors and not ui.reruns


def test_service_saves_settings_before_key(monkeypatch):
    class State(dict):
        def __setattr__(self, name, value):
            self[name] = value
    ui = SettingsUI()
    ui.session_state = State()
    monkeypatch.setattr(app, 'st', ui)
    monkeypatch.setattr(app.keys, 'storage_secure', lambda: True)
    monkeypatch.setattr(app, '_check_selection', lambda *args: None)
    events = []
    monkeypatch.setattr(app.config, 'save_settings', lambda value: events.append(('settings', deepcopy(value))))
    monkeypatch.setattr(app.keys, 'set_key', lambda *args: events.append(('key', args)))
    app._save_service('llm', 'test-secret', deepcopy(app.DEFAULT_SETTINGS),
                      {'model': 'm-1', 'base_url': 'https://llm.test/v1'})
    assert [event[0] for event in events] == ['settings', 'key']
    assert events[0][1]['llm']['model'] == 'm-1'
    assert ui.reruns == 1
