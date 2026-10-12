from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import queue
import time
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
        if label.endswith("(giây)"):
            return kwargs["value"]
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


def test_length_summary_and_validation():
    params = pipeline.RunParams(14, {"video", "reel"}, length_limits={
        "video": (180, 1200), "reel": (None, 90)})
    assert app._filter_summary(params) == "Video 3–20 phút · Reel ≤ 90 giây"
    assert app.filters.validate_length_limits({"video": (181, 180)})
    assert app.filters.validate_length_limits({"reel": (-1, 90)})
    assert app.filters.validate_length_limits({"video": (180, None), "reel": (None, 90)}) is None


def test_length_inputs_restore_only_selected_base_types(monkeypatch):
    settings = deepcopy(app.DEFAULT_SETTINGS)
    settings["scan"].update(video_kinds=["reel_live"], length_limits={"video": [180, None], "reel": [None, 90]})
    monkeypatch.setattr(app, "st", ScanUI())
    params = app._scan_options(settings, False)
    assert params.length_limits == {"reel": (None, 90)}


def test_start_persists_length_limits_and_preserves_unselected_type(monkeypatch):
    ui = ScanUI()
    ui.rerun = lambda: None
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "_refresh_keys", lambda *args, **kwargs: {})
    monkeypatch.setattr(app.config, "load_lines", lambda *args: ["page"])
    monkeypatch.setattr(app.config, "save_settings", lambda settings: None)
    monkeypatch.setattr(app.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    settings = deepcopy(app.DEFAULT_SETTINGS)
    settings["scan"]["length_limits"] = {"video": [180, None]}
    app._start_scan(settings, pipeline.RunParams(14, {"reel"}, length_limits={"reel": (None, 90)}))
    assert settings["scan"]["length_limits"] == {"video": [180, None], "reel": (None, 90)}


def test_invalid_length_limits_block_start_before_services(monkeypatch):
    errors = []
    monkeypatch.setattr(app, "_show_error", errors.append)
    monkeypatch.setattr(app, "_refresh_keys", lambda *args, **kwargs: pytest.fail("must not check keys"))
    app._start_scan({}, pipeline.RunParams(14, {"video"}, length_limits={"video": (180, 90)}))
    assert errors == ["Thời lượng Video: tối thiểu không được lớn hơn tối đa."]


def test_invalid_length_range_disables_scan_button(monkeypatch):
    ui = TermsUI(ticked=False)
    errors = []
    ui.error = errors.append
    settings = deepcopy(app.DEFAULT_SETTINGS)
    settings["terms_accepted_at"] = "2026-10-12"
    settings["scan"]["length_limits"] = {"video": [180, 90]}
    _terms_page(monkeypatch, ui, settings)
    assert ui.start_disabled is True
    assert errors == ["Thời lượng Video: tối thiểu không được lớn hơn tối đa."]


@pytest.mark.parametrize("kind,preset,expected", [
    ("video", "≥ 3 phút", (180.0, 0.0)),
    ("reel", "≤ 90 giây", (0.0, 90.0)),
])
def test_length_presets_set_both_bounds(monkeypatch, kind, preset, expected):
    ui = ScanUI()
    ui.session_state = {}
    callbacks = {}
    ui.button = lambda label, **kwargs: callbacks.update({label: kwargs}) or False
    monkeypatch.setattr(app, "st", ui)
    app._length_preset_buttons(kind, False)
    choice = callbacks[preset]
    choice["on_click"](*choice["args"])
    assert (ui.session_state[f"scan_length_{kind}_min"],
            ui.session_state[f"scan_length_{kind}_max"]) == expected


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


@pytest.mark.parametrize("relative", ["rapport.xlsx", "nested/rapport.xlsx", "RAPPORT.XLSX",
                                      "nested/../rapport.xlsx"])
def test_safe_excel_path_accepts_only_resolved_output_files(tmp_path, relative):
    output = tmp_path / "output"
    output.mkdir()
    target = output / relative
    assert app._safe_excel_path(target, output) == target.resolve()


@pytest.mark.parametrize("relative", ["../rapport.xlsx", "../output_elsewhere/rapport.xlsx",
                                      "rapport.csv", "rapport.xlsx.exe", "."])
def test_safe_excel_path_rejects_outside_paths_and_extensions(tmp_path, relative):
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError):
        app._safe_excel_path(output / relative, output)


def test_safe_excel_path_checks_resolved_target(monkeypatch, tmp_path):
    output = tmp_path / "output"
    link = output / "link.xlsx"
    outside = tmp_path / "outside.xlsx"
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        outside if path == link else original(path, *args, **kwargs))
    with pytest.raises(ValueError):
        app._safe_excel_path(link, output)


def test_delete_excel_removes_only_selected_file(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    target, other = output / "selected.xlsx", output / "other.xlsx"
    target.write_bytes(b"selected")
    other.write_bytes(b"other")
    assert app._delete_excel(target, output) == target.resolve()
    assert not target.exists()
    assert other.read_bytes() == b"other"


def test_delete_excel_preserves_file_when_locked(monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    target = output / "locked.xlsx"
    target.write_bytes(b"locked")

    def locked(path):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(PermissionError):
        app._delete_excel(target, output)
    assert target.read_bytes() == b"locked"


class QueueState(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def _progress_event(**kwargs):
    values = dict(stage="analyze", page_index=1, page_total=1, page_url="page",
                  message="Video 1: đang phân tích", done=False, error=None, step=0, steps=1,
                  transient=False, usage=None, turn=None)
    values.update(kwargs)
    return SimpleNamespace(**values)


def _queue_ui(monkeypatch, events, **kwargs):
    state = QueueState(scan_queue=queue.Queue(), scan_log=[], scan_errors=[],
                       running=True, scan_started=time.monotonic(), question=None)
    state.update(kwargs)
    for event in events:
        state.scan_queue.put(event)
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(app, "_redact", lambda text: text.replace("secret", "•••"))
    return state


def test_usage_only_queue_event_preserves_progress_and_timeline(monkeypatch):
    prior = _progress_event(message="Đang chờ 3 giây", transient=True)
    usage = {"llm_tokens": 40, "llm_output_tokens": 20, "llm_seconds": 2, "jev_tokens": 10}
    event = _progress_event(stage="export", message="", transient=True, usage=usage)
    state = _queue_ui(monkeypatch, [event], progress=prior, scan_log=["đã quét"],
                      scan_overall=0.4)
    assert app._drain_scan_queue() is False
    assert state.progress is prior
    assert state.scan_log == ["đã quét"]
    assert state.scan_overall == 0.4
    assert state.scan_usage == usage
    assert state.scan_usage is not usage
    assert state.scan_usage_history[0]["Token LLM"] == 40
    assert state.scan_usage_history[0]["Token Jev"] == 10
    assert isinstance(state.scan_usage_history[0]["Thời gian"], datetime)


def test_turn_events_append_and_keep_usage_after_finish(monkeypatch):
    turn = {"label": "Video 1", "llm_tokens": 100, "llm_output_tokens": 20,
            "llm_seconds": 2.5, "jev_tokens": 15, "deepgram_minutes": 0.5}
    usage = {"llm_tokens": 100, "jev_tokens": 15}
    event = _progress_event(message="Video 1: xong", usage=usage, turn=turn, step=1)
    state = _queue_ui(monkeypatch, [event, ("finished", None)])
    assert app._drain_scan_queue() is True
    assert not state.running
    assert state.scan_usage == usage
    assert state.scan_turns == [turn]
    assert state.scan_turns[0] is not turn
    assert state.progress is event
    assert len(state.scan_log) == 1
    assert state.scan_channels[0]["analyzed"] == 1


def test_countdown_is_displayed_but_not_logged(monkeypatch):
    event = _progress_event(message="Nghỉ · còn 5 giây", transient=True, usage={"llm_tokens": 10})
    state = _queue_ui(monkeypatch, [event])
    app._drain_scan_queue()
    assert state.progress is event
    assert not state.scan_log
    assert state.scan_usage["llm_tokens"] == 10


def test_error_event_keeps_current_progress_and_masks_log(monkeypatch):
    prior = _progress_event()
    event = _progress_event(message="Lỗi secret", error="secret", usage={"llm_tokens": 12})
    state = _queue_ui(monkeypatch, [event], progress=prior)
    app._drain_scan_queue()
    assert state.progress is prior
    assert state.scan_errors == ["•••"]
    assert "secret" not in state.scan_log[0]
    assert state.scan_usage["llm_tokens"] == 12


@pytest.mark.parametrize("tokens,seconds,expected", [(100, 4, 25.0), (10, 3, 3.33),
                                                  (0, 2, None), (10, 0, None), (10, -1, None)])
def test_turn_speed_uses_output_tokens_and_wait_time(tokens, seconds, expected):
    assert app._turn_speed({"llm_output_tokens": tokens, "llm_seconds": seconds,
                            "llm_tokens": 999}) == expected


def test_turn_rows_show_latest_first_and_preserve_unmeasured_speed():
    first = {"label": "Video 1", "llm_tokens": 50, "llm_output_tokens": 10, "llm_seconds": 2}
    second = {"label": "Nhận xét tổng hợp", "jev_tokens": 15, "deepgram_minutes": 1.234}
    rows = app._turn_rows([first, second])
    assert [row["Lượt"] for row in rows] == ["Nhận xét tổng hợp", "Video 1"]
    assert rows[0]["Token/giây"] is None
    assert rows[0]["Deepgram (phút)"] == 1.23
    assert rows[1]["Token/giây"] == 5.0


def test_channel_counts_split_cumulative_filter_totals_and_parallel_turns():
    state = {"scan_channels": [{"url": url, "status": "Chờ quét", "found": None,
                                "passed": None, "analyzed": 0} for url in ["page", "second"]]}
    stamp = datetime(2026, 10, 12, 10, 0)
    events = [
        _progress_event(stage="scan", message="Kênh 1/2: thu được 5 video trong 14 ngày."),
        _progress_event(stage="filter", message="Đạt ngưỡng: 2/5 video."),
        _progress_event(page_url="second", stage="scan", message="Kênh 2/2: thu được 4 video trong 14 ngày."),
        _progress_event(page_url="second", stage="filter", message="Đạt ngưỡng: 3/9 video."),
        _progress_event(message="Video 1: xong", turn={"label": "Video 1"}),
        _progress_event(message="Video 2: xong", turn={"label": "Video 2"}),
        _progress_event(page_url="second", message="Video 3: xong", turn={"label": "Video 3"}),
    ]
    overall = []
    for event in events:
        app._record_scan_progress(state, event, stamp, lambda text: text)
        overall.append(state["scan_overall"])
    assert [(row["found"], row["passed"], row["analyzed"]) for row in state["scan_channels"]] == [
        (5, 2, 2), (4, 1, 1)]
    assert all(row["status"] == "Đã phân tích" for row in state["scan_channels"])
    assert all(row["Tiến độ"] == 1.0 for row in app._channel_rows(state["scan_channels"]))
    assert overall == sorted(overall)
    assert overall[-1] < 1
    app._record_scan_progress(state, _progress_event(stage="done", message="Xong", done=True),
                              stamp, lambda text: text)
    assert state["scan_overall"] == 1


def test_summary_charts_rank_views_group_topics_and_ignore_missing_scores():
    summary = {"kind": "video", "items": [
        {"title": "A", "views": 100, "topic": "Dược", "score": 19},
        {"title": "B", "views": 200, "topic": "Dược", "score": 80},
        {"title": "C", "views": None, "topic": "", "score": None},
    ]}
    top, topics, scores = app._summary_charts(summary)
    assert [row["Lượt xem"] for row in top] == [200, 100]
    assert sum(row["Số nội dung"] for row in topics) == 3
    assert next(row["Số nội dung"] for row in topics if row["Chủ đề"] == "Dược") == 2
    assert sum(row["Số nội dung"] for row in scores) == 2


def test_summary_charts_posts_use_interactions_and_limit_top_items():
    items = [{"title": "Trùng tiêu đề", "views": 1000 - index, "interactions": index,
              "topic": "A", "score": 50} for index in range(12)]
    top, _, _ = app._summary_charts({"kind": "post", "items": items})
    assert len(top) == 10
    assert [row["Tương tác"] for row in top] == list(range(11, 1, -1))
    assert len({row["Nội dung"] for row in top}) == 10


def test_file_summary_uses_path_and_modification_time_cache_key(monkeypatch, tmp_path):
    path = tmp_path / "test.xlsx"
    path.write_bytes(b"example")
    calls = []

    def cached(name, mtime):
        calls.append((name, mtime))
        return {"count": 3}

    monkeypatch.setattr(app, "_cached_summary", cached)
    assert app._file_summary(path) == {"count": 3}
    assert calls == [(str(path), path.stat().st_mtime_ns)]
    assert app._file_summary(tmp_path / "missing.xlsx") == {}


def test_start_scan_resets_tracking_from_previous_run(monkeypatch):
    state = QueueState(scan_usage={"llm_tokens": 999}, scan_turns=[{"label": "Cũ"}],
                       scan_usage_history=[{"Token LLM": 999}], scan_overall=1.0)
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=state, rerun=lambda: None))
    monkeypatch.setattr(app, "_refresh_keys", lambda *args, **kwargs: {})
    monkeypatch.setattr(app.config, "load_lines", lambda *args: ["first", "second"])
    monkeypatch.setattr(app.config, "save_settings", lambda settings: None)
    monkeypatch.setattr(app.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    app._start_scan(deepcopy(app.DEFAULT_SETTINGS), pipeline.RunParams(14, {"video"}))
    assert state.scan_usage is None
    assert state.scan_turns == []
    assert state.scan_usage_history == []
    assert state.scan_overall == 0.0
    assert state.scan_passed_total == 0
    assert [row["url"] for row in state.scan_channels] == ["first", "second"]
    assert all(row["found"] is None and row["passed"] is None for row in state.scan_channels)


def test_channel_progress_distinguishes_unknown_counts_from_no_results():
    channels = [{"url": "waiting", "status": "Chờ quét", "found": None, "passed": None, "analyzed": 0},
                {"url": "empty", "status": "Đã phân tích", "found": 5, "passed": 0, "analyzed": 0},
                {"url": "skipped", "status": "Bỏ qua", "found": None, "passed": None, "analyzed": 0}]
    rows = app._channel_rows(channels)
    assert rows[0]["Tìm thấy"] is None
    assert rows[0]["Tiến độ"] == 0
    assert rows[1]["Đạt ngưỡng"] == 0
    assert rows[1]["Tiến độ"] == 1
    assert rows[2]["Tiến độ"] == 1


@pytest.mark.parametrize("value,expected", [(200000, "200.000"), (1234.5, "1.234,50"),
                                          (0, "0"), (12.34, "12,34")])
def test_chart_tooltip_values_use_vietnamese_separators(value, expected):
    assert app._chart_value(value) == expected


@pytest.mark.parametrize("horizontal", [False, True])
def test_count_charts_have_zero_based_integer_axes_and_no_zoom_selection(horizontal):
    chart = app._bar_chart(app.pd.DataFrame([
        {"Chủ đề": "A", "Số nội dung": 2}, {"Chủ đề": "B", "Số nội dung": 1}
    ]), "Chủ đề", "Số nội dung", count=True, horizontal=horizontal)
    spec = chart.to_dict()
    numeric = spec["encoding"]["x" if horizontal else "y"]
    assert numeric["scale"]["domainMin"] == 0
    assert numeric["scale"]["zero"] is True
    assert numeric["axis"]["tickMinStep"] == 1
    assert numeric["axis"]["format"] == "d"
    assert "params" not in spec
    assert "selection" not in spec
    assert spec["encoding"]["tooltip"]


def test_large_number_chart_uses_compact_axis_and_localized_tooltips():
    spec = app._bar_chart(app.pd.DataFrame([
        {"Nội dung": "A", "Lượt xem": 200000}
    ]), "Nội dung", "Lượt xem", horizontal=True).to_dict()
    assert spec["encoding"]["x"]["axis"]["format"] == "~s"
    assert spec["encoding"]["x"]["scale"]["domainMin"] == 0
    assert "params" not in spec
    data = next(iter(spec["datasets"].values()))
    assert data[0]["Giá trị hiển thị"] == "200.000"


def test_token_series_chart_keeps_grouped_bars_without_scale_bindings():
    spec = app._bar_chart(app.pd.DataFrame([
        {"Lượt": "Video 1", "Dịch vụ": "Token LLM", "Token": 200000},
        {"Lượt": "Video 1", "Dịch vụ": "Token Jev", "Token": 1000},
    ]), "Lượt", "Token", series="Dịch vụ").to_dict()
    assert spec["encoding"]["xOffset"]["field"] == "Dịch vụ"
    assert spec["encoding"]["color"]["field"] == "Dịch vụ"
    assert spec["encoding"]["y"]["axis"]["format"] == "~s"
    assert "params" not in spec
    assert "selection" not in spec


def test_usage_line_chart_keeps_tooltips_without_wheel_zoom():
    spec = app._usage_line_chart([
        {"Thời gian": datetime(2026, 10, 12, 10, 0), "Token LLM": 200000, "Token Jev": 1000},
    ]).to_dict()
    assert spec["encoding"]["y"]["scale"]["domainMin"] == 0
    assert spec["encoding"]["y"]["axis"]["format"] == "~s"
    assert "params" not in spec
    assert "selection" not in spec
    assert spec["encoding"]["tooltip"]
    data = next(iter(spec["datasets"].values()))
    assert any(row["Token hiển thị"] == "200.000" for row in data)


def test_delete_button_is_icon_only_with_vietnamese_help(monkeypatch, tmp_path):
    path = tmp_path / "result.xlsx"
    path.write_bytes(b"example")
    options = []
    download = SimpleNamespace(download_button=lambda *args, **kwargs: None)

    def button(label, **kwargs):
        options.append((label, kwargs))
        return False

    delete = SimpleNamespace(button=button)
    monkeypatch.setattr(app, "st", SimpleNamespace(columns=lambda *args, **kwargs: [download, delete]))
    app._download_button(path)
    label, kwargs = options[0]
    assert label == ""
    assert kwargs["icon"] == ":material/delete:"
    assert kwargs["help"] == "Xóa file"


@pytest.mark.parametrize("message,expected", [
    ("Kênh 1/3: Nhà thuốc A · 200.000 người theo dõi", ("Nhà thuốc A", 200000)),
    ("Kênh 2/3: Page A · Page B · 1,234 người theo dõi", ("Page A · Page B", 1234)),
    ("Kênh 3/3: Tên kênh · 0 người theo dõi", ("Tên kênh", 0)),
    ("Kênh 1/3: Tên kênh · chưa đọc được số người theo dõi", ("Tên kênh", None)),
    ("Kênh 1/3: mở trang, đọc tên và số người theo dõi…", None),
    ("Kênh 1/3: thu được 5 video trong 14 ngày.", None),
    ("Kênh 1/3 · Tab Video xong: thêm 5 video mới", None),
])
def test_page_header_only_parses_name_and_follower_events(message, expected):
    assert app._page_header(message) == expected


def test_channel_metadata_is_kept_after_later_progress_events():
    state = {}
    app._track_channels(state, _progress_event(
        stage="scan", page_url="https://www.facebook.com/page",
        message="Kênh 1/1: Nhà thuốc A · 123.456 người theo dõi"))
    app._track_channels(state, _progress_event(
        stage="scan", page_url="https://www.facebook.com/page",
        message="Kênh 1/1: thu được 5 video trong 14 ngày."))
    row = app._channel_rows(state["scan_channels"])[0]
    assert row["Kênh"] == "Nhà thuốc A"
    assert row["Link kênh"] == "https://www.facebook.com/page"
    assert row["Follower"] == 123456
    assert row["Tìm thấy"] == 5


def test_channel_table_formats_unknown_counts_as_dashes_and_known_counts_locally():
    channels = [
        {"url": "https://www.facebook.com/first", "status": "Chờ quét",
         "found": None, "passed": None, "analyzed": 0},
        {"url": "https://www.facebook.com/second", "name": "Nhà thuốc A", "followers": 200000,
         "status": "Đã phân tích", "found": 1234, "passed": 0, "analyzed": 0},
    ]
    records = app._channel_frame(channels).to_dict(orient="records")
    assert records[0]["Follower"] == "—"
    assert records[0]["Tìm thấy"] == "—"
    assert records[0]["Đạt ngưỡng"] == "—"
    assert records[0]["Đã phân tích"] == "0"
    assert records[1]["Kênh"] == "Nhà thuốc A"
    assert records[1]["Follower"] == "200.000"
    assert records[1]["Tìm thấy"] == "1.234"
    assert records[1]["Đạt ngưỡng"] == "0"
    assert all(value is not None for row in records for value in row.values())
    assert "None" not in str(records)


def test_channel_table_retains_name_when_follower_count_is_unavailable():
    state = {}
    app._track_channels(state, _progress_event(
        stage="scan", message="Kênh 1/1: Nhà thuốc A · chưa đọc được số người theo dõi"))
    row = app._channel_frame(state["scan_channels"]).to_dict(orient="records")[0]
    assert row["Kênh"] == "Nhà thuốc A"
    assert row["Follower"] == "—"
    assert row["Link kênh"] == "page"


def test_channel_table_all_unknown_numeric_cells_are_dashes():
    channels = [{"url": "page", "status": "Chờ quét", "found": None,
                 "passed": None, "analyzed": 0}]
    frame = app._channel_frame(channels)
    assert frame.loc[0, ["Follower", "Tìm thấy", "Đạt ngưỡng"]].tolist() == ["—", "—", "—"]
    assert app._channel_frame([]).empty


def test_turn_table_never_displays_none_for_unmeasured_speed():
    frame = app._turn_frame([{"label": "Video 1"}, {"label": "Video 2"}])
    assert frame["Token/giây"].tolist() == ["—", "—"]
    frame = app._turn_frame([
        {"label": "Video 1", "llm_output_tokens": 10, "llm_seconds": 4},
        {"label": "Video 2"},
    ])
    assert frame["Token/giây"].tolist() == ["—", "2,5"]
