from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app
import pipeline


class ScanUI:
    def __init__(self, selected=None, scan_kind="Video"):
        self.selected = selected
        self.scan_kind = scan_kind
        self.labels = []
        self.captions = []
        self.session_state = SimpleNamespace(update=lambda **kwargs: None)

    def columns(self, *args, **kwargs):
        return [nullcontext(), nullcontext()]

    def container(self, **kwargs):
        return nullcontext()

    def markdown(self, *args):
        pass

    def radio(self, label, options, **kwargs):
        return self.scan_kind if label == "Loại quét" else "14"

    def checkbox(self, label, *, value, key, disabled):
        self.labels.append((label, value, disabled))
        return value if self.selected is None else key.removeprefix("scan_kind_") in self.selected

    def number_input(self, label, **kwargs):
        return kwargs["value"]

    def caption(self, text):
        self.captions.append(text)

    def button(self, label, **kwargs):
        self.button_disabled = kwargs["disabled"]
        return False


def test_default_scan_has_four_checkboxes_and_excludes_live(monkeypatch):
    ui = ScanUI()
    monkeypatch.setattr(app, "st", ui)
    params = app._scan_options(deepcopy(app.DEFAULT_SETTINGS), False)
    assert params.formats == {"video", "reel"}
    assert ui.labels == [("Video thường", True, False), ("Reel", True, False),
                         ("Video (Live)", False, False), ("Reel (Live)", False, False)]


def test_saved_live_choices_and_post_mode(monkeypatch):
    settings = deepcopy(app.DEFAULT_SETTINGS)
    settings["scan"]["video_kinds"] = ["reel_live"]
    monkeypatch.setattr(app, "st", ScanUI())
    assert app._scan_options(settings, False).formats == {"reel_live"}
    ui = ScanUI(scan_kind="Bài đăng")
    monkeypatch.setattr(app, "st", ui)
    assert app._scan_options(settings, False).formats == {"post"}
    assert not ui.labels


def test_empty_choice_disables_start_and_explains(monkeypatch):
    ui = ScanUI(selected=set())
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "_scan_status", lambda: None)
    monkeypatch.setattr(app, "_busy", lambda: False)
    monkeypatch.setattr(app, "_key_status_panel", lambda *args, **kwargs: None)
    app._scan_page(deepcopy(app.DEFAULT_SETTINGS))
    assert ui.button_disabled
    assert ui.captions == ["Chọn ít nhất một loại video để quét."]


@pytest.mark.parametrize("formats", [{"video_live", "reel"}, {"post"}])
def test_start_remembers_video_kinds_without_changing_them_for_posts(monkeypatch, formats):
    ui = ScanUI()
    ui.rerun = lambda: None
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "_refresh_keys", lambda *args, **kwargs: {})
    monkeypatch.setattr(app.config, "load_lines", lambda *args: ["page"])
    saved = []
    monkeypatch.setattr(app.config, "save_settings", lambda settings: saved.append(deepcopy(settings)))
    monkeypatch.setattr(app.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    settings = deepcopy(app.DEFAULT_SETTINGS)
    app._start_scan(settings, pipeline.RunParams(14, formats, min_views=500))
    assert saved[0]["scan"]["video_kinds"] == (sorted(formats) if formats != {"post"} else ["video", "reel"])
