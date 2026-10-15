from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import time

import pytest
from backend.api import scan
from backend.services import pipeline


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    monkeypatch.setattr(scan, "_session", scan._new_session())


def _progress_event(**kwargs):
    values = dict(stage="analyze", page_index=1, page_total=1, page_url="page",
                  message="Video 1: đang phân tích", done=False, error=None, step=0, steps=1,
                  transient=False, usage=None, turn=None)
    values.update(kwargs)
    return SimpleNamespace(**values)

def test_length_summary_and_validation():
    params = pipeline.RunParams(14, {"video", "reel"}, length_limits={
        "video": (180, 1200), "reel": (None, 90)})
    assert scan._filter_summary(params) == "Video 3–20 phút · Reel ≤ 90 giây"
    assert scan.filters.validate_length_limits({"video": (181, 180)})
    assert scan.filters.validate_length_limits({"reel": (-1, 90)})
    assert scan.filters.validate_length_limits({"video": (180, None), "reel": (None, 90)}) is None

@pytest.mark.parametrize("tokens,seconds,expected", [(100, 4, 25.0), (10, 3, 3.33),
                                                  (0, 2, None), (10, 0, None), (10, -1, None)])
def test_turn_speed_uses_output_tokens_and_wait_time(tokens, seconds, expected):
    assert scan._turn_speed({"llm_output_tokens": tokens, "llm_seconds": seconds,
                            "llm_tokens": 999}) == expected

def test_turn_rows_show_latest_first_and_preserve_unmeasured_speed():
    first = {"label": "Video 1", "llm_tokens": 50, "llm_output_tokens": 10, "llm_seconds": 2}
    second = {"label": "Nhận xét tổng hợp", "jev_tokens": 15, "deepgram_minutes": 1.234}
    rows = scan._turn_rows([first, second])
    assert [row["label"] for row in rows] == ["Nhận xét tổng hợp", "Video 1"]
    assert rows[0]["speed"] is None
    assert rows[0]["deepgram_minutes"] == 1.23
    assert rows[1]["speed"] == 5.0

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
        scan._record_scan_progress(state, event, stamp, lambda text: text)
        overall.append(state["scan_overall"])
    assert [(row["found"], row["passed"], row["analyzed"]) for row in state["scan_channels"]] == [
        (5, 2, 2), (4, 1, 1)]
    assert all(row["status"] == "Đã phân tích" for row in state["scan_channels"])
    assert all(row["progress"] == 1.0 for row in scan._channel_rows(state["scan_channels"]))
    assert overall == sorted(overall)
    assert overall[-1] < 1
    scan._record_scan_progress(state, _progress_event(stage="done", message="Xong", done=True),
                              stamp, lambda text: text)
    assert state["scan_overall"] == 1

def test_channel_progress_distinguishes_unknown_counts_from_no_results():
    channels = [{"url": "waiting", "status": "Chờ quét", "found": None, "passed": None, "analyzed": 0},
                {"url": "empty", "status": "Đã phân tích", "found": 5, "passed": 0, "analyzed": 0},
                {"url": "skipped", "status": "Bỏ qua", "found": None, "passed": None, "analyzed": 0}]
    rows = scan._channel_rows(channels)
    assert rows[0]["found"] is None
    assert rows[0]["progress"] == 0
    assert rows[1]["passed"] == 0
    assert rows[1]["progress"] == 1
    assert rows[2]["progress"] == 1

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
    assert scan._page_header(message) == expected

def test_channel_metadata_is_kept_after_later_progress_events():
    state = {}
    scan._track_channels(state, _progress_event(
        stage="scan", page_url="https://www.facebook.com/page",
        message="Kênh 1/1: Nhà thuốc A · 123.456 người theo dõi"))
    scan._track_channels(state, _progress_event(
        stage="scan", page_url="https://www.facebook.com/page",
        message="Kênh 1/1: thu được 5 video trong 14 ngày."))
    row = scan._channel_rows(state["scan_channels"])[0]
    assert row["name"] == "Nhà thuốc A"
    assert row["url"] == "https://www.facebook.com/page"
    assert row["followers"] == 123456
    assert row["found"] == 5

@pytest.fixture
def configured(monkeypatch):
    settings = {"terms_accepted_at": "2026-10-12", "scan": {"video_kinds": ["video", "reel"],
                "min_views": 10000, "min_interactions": 200, "length_limits": {"video": [180, None]}},
                "llm": {"base_url": "https://example.com", "model": "model"}}
    saved = []
    monkeypatch.setattr(scan.config, "load_settings", lambda: deepcopy(settings))
    monkeypatch.setattr(scan.config, "save_settings", lambda value: saved.append(deepcopy(value)))
    monkeypatch.setattr(scan.config, "load_lines", lambda *args: ["page", "second"])
    monkeypatch.setattr(scan.services, "check_keys", lambda **kwargs: {"ok": True, "status": {}})
    monkeypatch.setattr(scan.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    return settings, saved


@pytest.mark.parametrize("formats", [["video", "reel"], ["post"]])
def test_start_remembers_video_kinds_without_changing_them_for_posts(configured, formats):
    settings, saved = configured
    assert scan.start_scan({"kind": "post" if formats == ["post"] else "video", "formats": formats})["ok"]
    assert saved[0]["scan"]["video_kinds"] == (sorted(formats) if formats != ["post"] else ["video", "reel"])


def test_ratio_params_summary_and_persistence(configured):
    options = dict(formats=["video"], min_views=50000, min_ratio_follow=5, match_all=False, length_limits={})
    params = scan._params(options)
    assert (params.min_views, params.min_ratio_follow, params.match_all) == (50000, 5, False)
    assert scan.preview_scan(options)["summary"] == "Giữ video có ≥ 50.000 lượt xem HOẶC ≥ 5× follower"
    params.match_all = True
    assert scan._filter_summary(params) == "Giữ video có ≥ 50.000 lượt xem VÀ ≥ 5× follower"
    assert scan.start_scan(options)["ok"]
    saved = configured[1][0]["scan"]
    assert (saved["min_ratio_follow"], saved["match_all"]) == (5, False)


def test_start_persists_length_limits_preserves_unselected_type(configured):
    assert scan.start_scan(dict(formats=["reel"], length_limits={"reel": [None, 90]}))["ok"]
    assert configured[1][0]["scan"]["length_limits"] == {"video": [180, None], "reel": (None, 90)}
    assert scan._params(dict(formats=["reel"], length_limits={"video": [180, None], "reel": [None, 90]})).length_limits == {"reel": (None, 90)}


def test_invalid_length_blocks_start_before_services(configured, monkeypatch):
    monkeypatch.setattr(scan.services, "check_keys", lambda **kwargs: pytest.fail("must not check keys"))
    options = dict(formats=["video"], length_limits={"video": [180, 90]})
    assert scan.start_scan(options)["error"] == "Thời lượng Video: tối thiểu không được lớn hơn tối đa."
    assert not scan.preview_scan(options)["can_start"]


def test_terms_acceptance_persisted_once(configured, monkeypatch):
    settings, saved = configured
    settings.pop("terms_accepted_at")
    assert not scan.start_scan({})["ok"]
    assert not scan.preview_scan({})["can_start"]
    first = scan.accept_terms()["accepted_at"]
    assert datetime.fromisoformat(first).tzinfo is not None
    monkeypatch.setattr(scan.config, "load_settings", lambda: deepcopy(saved[-1]))
    assert scan.accept_terms()["accepted_at"] == first
    assert len(saved) == 1
    assert scan.get_scan_options()["terms"]["accepted_at"] == first


def test_empty_formats_explained(configured):
    response = scan.preview_scan({"formats": []})
    assert response["problems"] == ["Chọn ít nhất một loại video để quét."]
    assert not response["can_start"]


def _enqueue(monkeypatch, events, **values):
    scan._session.update(running=True, scan_started=time.monotonic(), **values)
    for event in events:
        scan._session["scan_queue"].put(event)
    monkeypatch.setattr(scan, "redact", lambda value: value.replace("secret", "•••"))
    return scan._session


def test_usage_only_event_preserves_progress_and_timeline(monkeypatch):
    prior = _progress_event(message="Đang chờ 3 giây", transient=True)
    usage = dict(llm_tokens=40, llm_output_tokens=20, llm_seconds=2, jev_tokens=10)
    state = _enqueue(monkeypatch, [_progress_event(stage="export", message="", transient=True, usage=usage)],
                     progress=prior, scan_log=["đã quét"], scan_overall=0.4)
    result = scan.get_scan_state(0)
    assert state["progress"] is prior
    assert result["log"] == ["đã quét"] and result["overall"] == 0.4
    assert state["scan_usage"] == usage and state["scan_usage"] is not usage
    assert result["usage_history"][0]["llm"] == 40
    assert result["usage_history"][0]["jev"] == 10
    assert len(result["usage_history"][0]["t"]) == 8


def test_turn_events_keep_usage_after_finish_and_freeze_elapsed(monkeypatch):
    turn = dict(label="Video 1", llm_tokens=100, llm_output_tokens=20, llm_seconds=2.5, jev_tokens=15, deepgram_minutes=0.5)
    usage = dict(llm_tokens=100, jev_tokens=15)
    state = _enqueue(monkeypatch, [_progress_event(message="Video 1: xong", turn=turn, usage=usage), ("finished", None)])
    result = scan.get_scan_state(0)
    assert not result["running"] and result["usage"]["llm_tokens"] == 100
    assert state["scan_turns"] == [turn] and state["scan_turns"][0] is not turn
    assert len(result["log"]) == 1 and result["channels"][0]["analyzed"] == 1
    assert result["elapsed_s"] == scan.get_scan_state(1)["elapsed_s"]
    assert scan.get_scan_state(1)["log"] == []


def test_countdown_displayed_not_logged(monkeypatch):
    _enqueue(monkeypatch, [_progress_event(message="Nghỉ · còn 5 giây", transient=True, usage={"llm_tokens": 10})])
    result = scan.get_scan_state(0)
    assert result["message"] == "Nghỉ · còn 5 giây" and result["log"] == []
    assert result["usage"]["llm_tokens"] == 10


def test_error_keeps_progress_and_masks(monkeypatch):
    prior = _progress_event()
    _enqueue(monkeypatch, [_progress_event(message="Lỗi secret", error="secret", usage={"llm_tokens": 12})], progress=prior)
    result = scan.get_scan_state(0)
    assert scan._session["progress"] is prior
    assert result["errors"] == ["•••"] and "secret" not in result["log"][0]
    assert result["usage"]["llm_tokens"] == 12


def test_start_resets_previous_tracking(configured):
    scan._session.update(scan_usage={"llm_tokens": 999}, scan_turns=[{"label": "Cũ"}], scan_usage_history=[{}], scan_overall=1)
    assert scan.start_scan({"formats": ["video"]})["ok"]
    s = scan._session
    assert s["scan_usage"] is None and s["scan_turns"] == [] and s["scan_usage_history"] == []
    assert s["scan_overall"] == 0 and s["scan_passed_total"] == 0
    assert [row["url"] for row in s["scan_channels"]] == ["page", "second"]
    assert all(row["found"] is None and row["passed"] is None for row in s["scan_channels"])


def test_channel_name_kept_without_followers():
    state = {}
    scan._track_channels(state, _progress_event(stage="scan", message="Kênh 1/1: Nhà thuốc A · chưa đọc được số người theo dõi"))
    row = scan._channel_rows(state["scan_channels"])[0]
    assert (row["name"], row["followers"], row["url"]) == ("Nhà thuốc A", None, "page")


def test_keys_failure_and_post_deepgram(configured, monkeypatch):
    required = []
    def check(**kwargs):
        required.append(kwargs["require_deepgram"])
        return {"ok": True, "status": {"jev": "Lỗi", "llm": None}}
    monkeypatch.setattr(scan.services, "check_keys", check)
    response = scan.start_scan({"kind": "post"})
    assert not response["ok"] and response["key_status"]["jev"] == "Lỗi"
    assert required == [False]
    assert not scan.is_running()


def test_read_images_supported_and_unsupported(configured, monkeypatch):
    monkeypatch.setattr(scan.llm_client, "vision_cached", lambda llm: None)
    monkeypatch.setattr(scan.keys, "get_key", lambda name: "key")
    monkeypatch.setattr(scan.llm_client, "check_vision", lambda *args: True)
    assert scan.set_read_images(True) == {"ok": True, "enabled": True, "message": "Model LLM hỗ trợ đọc ảnh."}
    assert configured[1][-1]["llm"]["vision"]["ok"] is True
    monkeypatch.setattr(scan.llm_client, "check_vision", lambda *args: False)
    response = scan.set_read_images(True)
    assert not response["enabled"] and response["message"] == scan.llm_client.vision_error("model")
    assert configured[1][-1]["scan"]["read_images"] is False


def test_options_saved_formats_presets_and_post_mode(configured):
    settings, _ = configured
    settings["scan"]["video_kinds"] = ["reel_live"]
    options = scan.get_scan_options()
    assert options["defaults"]["formats"] == ["video", "reel"]
    assert [item["id"] for item in options["kinds"]] == ["video", "reel"]
    assert options["presets"]["length"]["video"][1] == {"label": "≥ 3 phút", "min": 180, "max": None}
    assert options["terms"]["link"]["url"] == "https://www.facebook.com/terms"
    assert len(options["terms"]["bullets"]) == 3
    params = scan._params({"kind": "post"})
    assert params.formats == {"post"} and params.length_limits == {}


@pytest.mark.parametrize("old,expected", [
    (["video", "video_live", "reel_live"], ["video"]),
    (["video_live", "reel_live"], ["video", "reel"]),
    ([], ["video", "reel"]),
])
@pytest.mark.parametrize("post", [False, True])
def test_saved_video_kinds_migrate_on_read_and_persist(configured, old, expected, post):
    settings, saved = configured
    settings["scan"]["video_kinds"] = old
    assert scan.get_scan_options()["defaults"]["formats"] == expected
    assert scan._params({}).formats == set(expected)
    assert scan.start_scan({"kind": "post" if post else "video"})["ok"]
    assert saved[0]["scan"]["video_kinds"] == (expected if post else sorted(expected))


@pytest.mark.parametrize("formats", [["video_live"], ["reel_live"], ["video", "video_live"]])
def test_explicit_removed_kinds_are_rejected(configured, formats):
    assert "Loại video không hợp lệ." in scan.preview_scan({"formats": formats})["problems"]
    assert not scan.start_scan({"formats": formats})["ok"]


def test_question_answer_and_stop(monkeypatch):
    import threading
    question = dict(kind="llm_quota", message="Hết hạn mức", options=[("continue", "Chạy tiếp"), ("pause", "Tạm dừng")],
                    answer=None, answer_event=threading.Event())
    _enqueue(monkeypatch, [("question", question)])
    assert scan.has_question()
    assert scan.get_scan_state(0)["question"]["options"][0]["id"] == "continue"
    assert not scan.answer_question("invalid")["ok"]
    assert scan.answer_question("continue")["ok"]
    assert question["answer_event"].is_set() and question["answer"] == "continue"
    assert not scan.has_question()
    scan._session["scan_queue"].put(("question", dict(question, answer_event=threading.Event())))
    assert scan.stop_scan()["ok"]
    assert scan.get_scan_state(0)["stopping"] and not scan.has_question()


def test_worker_passes_questions_and_records_failure(monkeypatch):
    import queue
    import threading
    events, stop = queue.Queue(), threading.Event()
    answers = []
    def fake_run(params, settings, emit, stop_event, ask_user):
        stop_event.set()
        answers.append(ask_user("quota", "Hết hạn mức", [("pause", "Tạm dừng")]))
        raise RuntimeError("failure")
    monkeypatch.setattr(scan.pipeline, "run", fake_run)
    monkeypatch.setattr(scan, "error_message", lambda exc: "Đã che lỗi")
    scan._scan_worker(pipeline.RunParams(7, {"video"}), {}, events, stop)
    assert answers == ["pause"]
    assert events.get_nowait()[0] == "question"
    assert events.get_nowait() == ("failure", "Đã che lỗi")
    assert events.get_nowait()[0] == "finished"


def test_reject_running_and_empty_channels(configured, monkeypatch):
    scan._session["running"] = True
    assert not scan.start_scan({})["ok"]
    scan._session["running"] = False
    monkeypatch.setattr(scan.config, "load_lines", lambda *args: [])
    assert scan.start_scan({})["error"] == "Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét."


def test_usage_speed_and_structured_stages(monkeypatch):
    _enqueue(monkeypatch, [_progress_event(step=1, steps=2, usage={"llm_output_tokens": 100, "llm_seconds": 4})])
    state = scan.get_scan_state(0)
    assert state["usage"]["llm_speed"] == 25
    assert state["step"] == {"fraction": 0.5, "label": "Đã phân tích 1/2 video"}
    assert [row["state"] for row in state["stages"]] == ["done", "done", "done", "current", "pending"]
