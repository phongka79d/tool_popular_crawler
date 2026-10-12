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

    def checkbox(self, label, *, value, disabled, key="", **kwargs):
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
    assert settings["scan"].get("read_images", False) is False


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


class FilterUI(ScanUI):
    def __init__(self, ratio=0.0, views=None, match=None):
        super().__init__()
        self.ratio, self.views, self.match = ratio, views, match
        self.notes = []

    def number_input(self, label, **kwargs):
        if label.startswith("Lượt xem tối thiểu so với"):
            return self.ratio
        return kwargs["value"] if self.views is None else self.views

    def radio(self, label, options, **kwargs):
        if label == "Cách kết hợp":
            return options[1] if self.match is False else options[0]
        return super().radio(label, options, **kwargs)

    def markdown(self, text):
        self.notes.append(text)


def test_ratio_params_and_summary(monkeypatch):
    ui = FilterUI(ratio=5, views=50_000, match=False)
    monkeypatch.setattr(app, "st", ui)
    params = app._scan_options(deepcopy(app.DEFAULT_SETTINGS), False)
    assert (params.min_views, params.min_ratio_follow, params.match_all) == (50_000, 5, False)
    assert "*Giữ video có ≥ 50.000 lượt xem HOẶC ≥ 5× follower*" in ui.notes
    params.match_all = True
    assert app._filter_summary(params) == "Giữ video có ≥ 50.000 lượt xem VÀ ≥ 5× follower"


def test_start_persists_ratio_and_combination(monkeypatch):
    ui = ScanUI()
    ui.rerun = lambda: None
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "_refresh_keys", lambda *args, **kwargs: {})
    monkeypatch.setattr(app.config, "load_lines", lambda *args: ["page"])
    saved = []
    monkeypatch.setattr(app.config, "save_settings", lambda settings: saved.append(deepcopy(settings)))
    monkeypatch.setattr(app.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    app._start_scan(deepcopy(app.DEFAULT_SETTINGS),
                    pipeline.RunParams(14, {"video"}, min_views=0, min_ratio_follow=10, match_all=False))
    assert (saved[0]["scan"]["min_ratio_follow"], saved[0]["scan"]["match_all"]) == (10, False)


class TermsUI(ScanUI):
    def __init__(self, ticked):
        super().__init__()
        self.ticked = ticked
        self.start_disabled = None

    def checkbox(self, label, *, value, disabled, key="", **kwargs):
        return self.ticked if key == "terms_ack" else super().checkbox(label, value=value, disabled=disabled, key=key)

    def expander(self, *args, **kwargs):
        return nullcontext()

    def button(self, label, **kwargs):
        if label == "Bắt đầu quét":
            self.start_disabled = kwargs["disabled"]
        return False


def _terms_page(monkeypatch, ui, settings):
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "_scan_status", lambda: None)
    monkeypatch.setattr(app, "_busy", lambda: False)
    monkeypatch.setattr(app, "_key_status_panel", lambda *args, **kwargs: None)
    saved = []
    monkeypatch.setattr(app.config, "save_settings", lambda s: saved.append(deepcopy(s)))
    app._scan_page(settings)
    return saved


def test_start_disabled_until_terms_accepted(monkeypatch):
    ui = TermsUI(ticked=False)
    saved = _terms_page(monkeypatch, ui, deepcopy(app.DEFAULT_SETTINGS))
    assert ui.start_disabled is True
    assert saved == []


def test_terms_acceptance_is_persisted_and_shown_once(monkeypatch):
    ui = TermsUI(ticked=True)
    saved = _terms_page(monkeypatch, ui, deepcopy(app.DEFAULT_SETTINGS))
    assert ui.start_disabled is False
    assert saved[0]["terms_accepted_at"]
    later = deepcopy(saved[0])
    ui = TermsUI(ticked=False)  # lần sau không còn ô tick nhưng vẫn cho quét
    assert _terms_page(monkeypatch, ui, later) == []
    assert ui.start_disabled is False
