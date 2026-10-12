"""Kiểm thử pipeline ngoại tuyến: không dùng trình duyệt, mạng hoặc API key thật."""
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

import pipeline
from errors import AuthError, LoginRequired, NetworkError, QuotaError
from collectors.facebook import page_url_problem
from models import Page


@pytest.fixture
def harness(monkeypatch, tmp_path):
    state = SimpleNamespace(
        channels=["large"], pages={"large": Page("large", "Kênh lớn", 200_000)},
        rows={"large": [{"video_id": "v1", "url": "https://facebook.test/v1", "views": 100_000,
                         "reactions": 100, "comments": 20, "shares": 40}]},
        errors={}, scans=[], pauses=[], progress=[], exports=[], finished=[],
        scan_formats=[],
        page_saved=[], video_saved=[], label_cache={}, llm_cache={},
        jev_calls=[], analysis_calls=[], suggestion_calls=[], commentary_calls=[],
        relevant=0.9, jev_error=None, llm_error=None, login_error=None,
        scan_stop=None, reject_suggestions=False, transcript_calls=[],
        scan_hook=None, pause_hook=None,
    )
    settings = {
        "jev": {"model": "jev-test", "yes_threshold": 0.5, "min_confidence": 0.6},
        "llm": {"base_url": "https://llm.test/v1", "model": "llm-test", "temperature": 0.4},
        "stt": {"keyterms_file": "config/keyterms.txt"},
        "scan": {"max_videos_per_page": 200, "min_views": 10000, "min_interactions": 200},
        "score_weights": {"ratio_median": 40, "ratio_median_cap": 5,
                          "replicable": 25, "hook_strength": 20, "relevant": 15, "jev_viral": 20},
        "my_page": {"name": "Page dược", "audience": "Nhà thuốc"},
    }
    monkeypatch.setattr(pipeline.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(pipeline.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline.config, "load_json", lambda name: {})
    monkeypatch.setattr(pipeline.config, "load_settings", lambda: settings)
    monkeypatch.setattr(pipeline.config, "load_lines", lambda name: list(state.channels) if name == "config/channels.txt" else [])
    monkeypatch.setattr(pipeline, "page_url_problem", lambda url: None)  # kênh giả "large"/"small"
    # Một luồng phân tích: thứ tự gọi giữa các video xác định được. Chạy song song có test riêng.
    monkeypatch.setattr(pipeline, "ANALYZE_WORKERS", 1)
    monkeypatch.setattr(pipeline.keys, "get_key", lambda name: "fake-key-" + name)
    monkeypatch.setattr(pipeline.keys, "mask", lambda key: "••••" + key[-4:])
    monkeypatch.setattr(pipeline.jev_client, "check_key", lambda *args: None)
    monkeypatch.setattr(pipeline.transcript, "check_key", lambda *args: None)
    monkeypatch.setattr(pipeline.llm_client, "check_key", lambda *args: None)
    monkeypatch.setattr(pipeline.db, "init_db", lambda: None)
    monkeypatch.setattr(pipeline.db, "start_run", lambda params: 1)
    monkeypatch.setattr(pipeline.db, "finish_run", lambda ident, log: state.finished.append(deepcopy(log)))
    monkeypatch.setattr(pipeline.db, "upsert_page", lambda page: state.page_saved.append(page))
    monkeypatch.setattr(pipeline.db, "upsert_video", lambda video: state.video_saved.append(video))
    monkeypatch.setattr(pipeline.db, "save_jev", lambda *args: None)
    monkeypatch.setattr(pipeline.db, "get_llm", lambda ident: deepcopy(state.llm_cache.get(ident)))
    monkeypatch.setattr(pipeline.db, "save_llm", lambda ident, model, output: state.llm_cache.__setitem__(ident, deepcopy(output)))
    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", lambda video: None)

    class Scanner:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def check_login(self):
            if state.login_error:
                raise state.login_error

        def get_page_info(self, url):
            if url in state.errors:
                raise state.errors[url]
            return state.pages[url]

        def scan_page(self, url, **kwargs):
            state.scans.append(url)
            state.scan_formats.append(kwargs["formats"])
            if state.scan_hook:
                state.scan_hook(url, kwargs["stop_event"])
            if state.scan_stop:
                state.scan_stop.set()
            return deepcopy(state.rows[url])

        def polite_page_pause(self, stop_event=None, on_tick=None):
            state.pauses.append(True)
            if on_tick:
                for left in (2, 1):
                    on_tick(left)
            if state.pause_hook:
                state.pause_hook(stop_event)

    monkeypatch.setattr(pipeline, "FacebookScanner", Scanner)

    def get_transcript(video, *args):
        state.transcript_calls.append(video.video_id)
        video.transcript = "Nội dung nghề dược"
        video.transcript_status = "ok"
        video.hook = "Bạn có biết?"
        return 0.5

    monkeypatch.setattr(pipeline.transcript, "get_transcript", get_transcript)
    monkeypatch.setattr(pipeline.jev_client, "make_client", lambda *args: object())
    monkeypatch.setattr(pipeline.llm_client, "make_client", lambda *args: object())

    def ask_labels(client, video, *args):
        if video.video_id in state.label_cache:
            return deepcopy(state.label_cache[video.video_id]), {}
        state.jev_calls.append(video.video_id)
        if state.jev_error:
            raise state.jev_error
        raw = {"relevant_p": state.relevant, "replicable_p": 0.8, "hook_strength": 2,
               "topic": "Nghề dược", "hook_type": "Câu hỏi"}
        state.label_cache[video.video_id] = deepcopy(raw)
        return raw, {"input_tokens": 7, "output_tokens": 3}

    monkeypatch.setattr(pipeline.jev_client, "ask_labels", ask_labels)
    monkeypatch.setattr(pipeline.jev_client, "interpret_labels", lambda raw, *args: raw)

    def analysis(client, model, video, *args):
        state.analysis_calls.append(video.video_id)
        if state.llm_error:
            raise state.llm_error
        pipeline.llm_client._record(
            SimpleNamespace(usage=SimpleNamespace(total_tokens=12, completion_tokens=4)), 2.0)
        return {"chu_de_bai": "Nghề dược", "_usage": 12,
                "goi_y_nhan_ban": [{"hook_moi": "Mẹo nhà thuốc", "y_tuong": "Một góc mới"}]}

    def check_suggestions(client, video, suggestions, *args):
        state.suggestion_calls.append(video.video_id)
        return ([] if state.reject_suggestions else suggestions), {}, {"total_tokens": 4}

    def commentary(client, model, summary, *args):
        state.commentary_calls.append(deepcopy(summary))
        pipeline.llm_client._record(
            SimpleNamespace(usage=SimpleNamespace(total_tokens=5, completion_tokens=2)), 1.0)
        return "Công thức đang thắng", 5

    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    monkeypatch.setattr(pipeline.llm_client, "filter_banned", lambda suggestions, words: suggestions)
    monkeypatch.setattr(pipeline.jev_client, "check_suggestions", check_suggestions)
    monkeypatch.setattr(pipeline.llm_client, "write_commentary", commentary)
    monkeypatch.setattr(pipeline.export_excel, "build_summary_tables", lambda videos: {
        "by_topic": [{"label": "Nghề dược", "count": len(videos), "avg_views": 100_000, "avg_score": 50}],
        "by_hook": [], "commentary": "",
    })

    def export(videos, summary, log):
        state.exports.append((deepcopy(videos), deepcopy(summary), deepcopy(log)))
        return tmp_path / "result.xlsx"

    monkeypatch.setattr(pipeline.export_excel, "export", export)
    state.params = pipeline.RunParams(14, {"reel", "video"}, min_views=50_000)
    state.settings = settings
    state.run = lambda stop=None, ask_user=None: pipeline.run(
        state.params, settings, state.progress.append, stop or Event(), ask_user
    )
    return state


def test_small_page_is_scanned_without_follower_gate(harness):
    h = harness
    h.channels.insert(0, "small")
    h.pages["small"] = Page("small", "Kênh nhỏ", 1)
    h.rows["small"] = [dict(h.rows["large"][0], video_id="small-v1")]
    assert h.run() is not None
    assert h.scans == ["small", "large"]
    assert h.exports[0][2]["pages"][0]["skipped_reason"] is None
    assert h.pauses == [True]


def test_length_filter_runs_before_paid_analysis_and_logs_counts(harness):
    h = harness
    template = h.rows["large"][0]
    h.rows["large"] = [
        dict(template, video_id=ident, format=kind, duration_s=duration)
        for ident, kind, duration in (
            ("video-ok", "video", 180), ("video-short", "video", 179),
            ("reel-ok", "reel", 90), ("reel-long", "reel", 120),
            ("live-video", "video_live", 180), ("live-reel-long", "reel_live", 91),
            ("unknown", "reel", None))
    ]
    h.params.length_limits = {"video": (180, None), "reel": (None, 90)}
    assert h.run() is not None
    expected = ["video-ok", "reel-ok", "live-video", "unknown"]
    assert h.transcript_calls == expected
    assert h.jev_calls == expected
    assert h.analysis_calls == expected
    videos, _, log = h.exports[0]
    assert log["params"]["length_limits"] == h.params.length_limits
    assert log["pages"][0]["passed"] == 4
    assert "Bỏ 1 video ngắn hơn 3 phút." in log["pages"][0]["errors"]
    assert "Bỏ 2 reel dài hơn 90 giây." in log["pages"][0]["errors"]
    assert any("Đạt ngưỡng: 4/7" in event.message for event in h.progress)
    assert any("Chưa biết thời lượng" in note for note in videos[-1].notes)


def test_partial_run_still_enforces_length_limits(harness):
    h = harness
    h.params.length_limits = {"video": (180, None)}
    h.rows["large"][0].update(duration_s=120)
    stop = Event()
    h.scan_stop = stop
    assert h.run(stop) is not None
    assert h.exports[0][0] == []
    assert h.exports[0][2]["pages"][0]["passed"] == 0
    assert h.transcript_calls == []


def test_post_run_ignores_video_length_limits(harness):
    h = harness
    h.params = pipeline.RunParams(14, {"post"}, min_interactions=160,
                                  length_limits={"video": (180, None), "reel": (None, 90)})
    h.rows["large"][0].update(format="post", caption="Bài đăng", duration_s=1)
    assert h.run() is not None
    assert len(h.exports[0][0]) == 1
    assert h.analysis_calls == ["v1"]


def test_post_run_skips_metadata_transcript_and_deepgram(harness, monkeypatch):
    h = harness
    h.params = pipeline.RunParams(14, {"post"}, min_interactions=160)
    h.rows["large"][0].update(format="post", views=None, caption="\n  Hook bài đăng  \nNội dung")
    monkeypatch.setattr(pipeline.keys, "get_key", lambda name: None if name == "deepgram" else "fake-key")
    monkeypatch.setattr(pipeline.transcript, "check_key", lambda *args: pytest.fail("post checked Deepgram"))
    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", lambda *args: pytest.fail("post fetched metadata"))
    assert h.run() is not None
    assert h.transcript_calls == []
    post = h.exports[0][0][0]
    assert post.interactions == 160
    assert post.hook == "Hook bài đăng"
    assert post.transcript == ""
    assert h.exports[0][2]["usage"]["deepgram_minutes"] == 0
    assert any("bài đăng" in progress.message.lower() for progress in h.progress)


def test_picture_only_post_is_skipped_unless_images_are_read(harness):
    h = harness
    h.params = pipeline.RunParams(14, {"post"})
    h.rows["large"][0].update(format="post", views=None, caption="Có chữ")
    h.rows["large"].append(dict(h.rows["large"][0], video_id="pic", caption="", image_urls=["u"]))
    assert h.run() is not None
    assert [post.video_id for post in h.exports[0][0]] == ["v1"]


def test_group_link_is_skipped_without_opening_or_pausing(harness, monkeypatch):
    h = harness
    group = "https://www.facebook.com/groups/123"
    h.channels.insert(0, group)
    # Validator thật cho link http; kênh giả "large" của harness vẫn được nhận.
    monkeypatch.setattr(pipeline, "page_url_problem",
                        lambda url: page_url_problem(url) if url.startswith("http") else None)
    assert h.run() is not None
    assert h.scans == ["large"]
    assert h.pauses == []  # không nghỉ 30–60 giây cho link bị bỏ qua
    log = h.exports[0][2]["pages"][0]
    assert "nhóm" in log["skipped_reason"]
    assert log["scanned"] == 0


def test_page_exception_does_not_stop_the_run(harness):
    h = harness
    h.channels.insert(0, "broken")
    h.errors["broken"] = ValueError("Không đọc được trang")
    assert h.run() is not None
    assert h.scans == ["large"]
    assert "Không đọc được trang" in h.exports[0][2]["pages"][0]["errors"]
    assert h.exports[0][2]["pages"][1]["analyzed"] == 1


def test_unreadable_page_link_is_reported_but_a_named_empty_page_is_not(harness):
    h = harness
    h.channels[:0] = ["wrong-link", "quiet"]
    h.pages["wrong-link"] = Page("wrong-link", "", None)  # link sai: không tên, không follower, không video
    h.pages["quiet"] = Page("quiet", "Kênh im ắng", 200_000)  # page thật, chỉ là không có video mới
    h.rows["wrong-link"] = h.rows["quiet"] = []

    assert h.run() is not None

    wrong, quiet = h.exports[0][2]["pages"][:2]
    assert any("kiểm tra link" in error for error in wrong["errors"])
    assert quiet["errors"] == []


def test_irrelevant_video_never_requests_llm_analysis(harness):
    h = harness
    h.relevant = 0.49
    assert h.run() is not None
    assert h.analysis_calls == []
    assert h.suggestion_calls == []
    assert h.exports[0][0][0].jev["relevant_p"] == 0.49
    assert h.exports[0][0][0].score is not None


def test_second_run_uses_per_video_jev_and_llm_cache(harness):
    h = harness
    assert h.run() is not None
    assert h.run() is not None
    assert h.jev_calls == ["v1"]
    assert h.analysis_calls == ["v1"]
    assert h.suggestion_calls == ["v1"]
    assert h.exports[1][0][0].llm["goi_y_nhan_ban"]
    assert h.exports[1][2]["usage"]["jev_tokens"] == 0
    # The run-level commentary is intentionally regenerated, not part of the video cache.
    assert len(h.commentary_calls) == 2


def test_jev_auth_error_exports_partial_and_records_message(harness):
    h = harness
    h.jev_error = AuthError("jev", "API key Jev không hợp lệ. Vào Cài đặt để nhập lại.")
    assert h.run() is not None
    assert len(h.exports[0][0]) == 1
    assert "API key Jev" in h.exports[0][2]["messages"][0]
    assert h.analysis_calls == []
    assert h.commentary_calls == []
    assert h.finished


def test_stop_event_halts_analysis_and_exports_collected_rows(harness):
    h = harness
    stop = Event()
    h.scan_stop = stop
    assert h.run(stop) is not None
    assert h.jev_calls == []
    assert h.transcript_calls == []
    assert h.analysis_calls == []
    assert any("Đã dừng" in message for message in h.exports[0][2]["messages"])


def test_stop_before_start_opens_no_scanner_and_finishes_run(harness):
    h = harness
    stop = Event()
    stop.set()
    assert h.run(stop) is None
    assert h.scans == []
    assert h.exports == []
    assert h.finished


def test_failed_key_blocks_scanning_and_reports_vietnamese_reason(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(pipeline.keys, "get_key", lambda name: None if name == "jev" else "fake-key")
    assert h.run() is None
    assert h.scans == []
    assert any(progress.error and "Chưa có API key Jev" in progress.error for progress in h.progress)
    assert h.finished


def test_login_required_blocks_run(harness):
    h = harness
    h.login_error = LoginRequired("facebook", "Cần đăng nhập Facebook.")
    assert h.run() is None
    assert h.scans == []
    assert h.exports == []
    assert h.finished[0]["messages"] == ["Cần đăng nhập Facebook."]


def test_llm_quota_continues_without_suggestions(harness):
    h = harness
    h.llm_error = QuotaError("llm", "Tài khoản LLM đã hết credit/hạn mức.")
    assert h.run() is not None
    assert h.exports[0][0][0].llm.get("goi_y_nhan_ban") == []
    assert any("tiếp tục không có gợi ý" in text for text in h.exports[0][2]["messages"])
    assert h.commentary_calls == []


def test_network_error_exports_partial_without_more_requests(harness):
    h = harness
    h.jev_error = NetworkError("jev", "Không kết nối được tới Jev.")
    assert h.run() is not None
    assert h.analysis_calls == []
    assert h.commentary_calls == []
    assert h.exports[0][2]["messages"] == ["Không kết nối được tới Jev."]


def test_rejected_suggestions_are_rewritten_only_once(harness):
    h = harness
    h.reject_suggestions = True
    assert h.run() is not None
    assert h.analysis_calls == ["v1", "v1"]
    assert h.suggestion_calls == ["v1", "v1"]
    assert h.exports[0][0][0].llm["goi_y_nhan_ban"] == []
    assert h.llm_cache["v1"]["goi_y_nhan_ban"] == []


def test_usage_counts_analysis_check_commentary_and_transcript(harness):
    h = harness
    h.run()
    usage = h.exports[0][2]["usage"]
    assert usage == {
        "jev_tokens": 14, "jev_calls": 2, "llm_tokens": 17, "deepgram_minutes": 0.5,
        "deepgram_calls": 1, "llm_model": "llm-test", "llm_calls": 2,
        "llm_output_tokens": 6, "llm_seconds": 3.0, "llm_cached": 0,
    }


def test_run_summary_reports_llm_speed_in_vietnamese_format():
    usage = {"llm_model": "claude-haiku-5-5", "llm_calls": 12, "llm_output_tokens": 23_400, "llm_seconds": 98.4}

    assert pipeline.usage_summary(usage) == (
        "LLM claude-haiku-5-5: 12 lần gọi, 23.400 token trả về, 98,4 giây chờ, trung bình 238 token/giây.")
    assert pipeline.usage_summary({"llm_calls": 0}) == ""



def test_cli_builds_requested_params(harness, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main(["--days", "14", "--formats", "post", "--min-views", "100", "--min-interactions", "250"]) == 0
    assert seen[0].days == 14
    assert seen[0].formats == {"post"}
    assert seen[0].min_views == 100
    assert seen[0].min_interactions == 250


def test_cli_ratio_and_any(harness, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main(["--min-views", "50000", "--min-ratio", "5", "--any"]) == 0
    assert (seen[0].min_views, seen[0].min_ratio_follow, seen[0].match_all) == (50_000, 5, False)
    assert pipeline.main(["--min-ratio", "0.5"]) == 0
    assert (seen[1].min_ratio_follow, seen[1].match_all) == (0.5, True)


def test_cli_length_limits_restore_settings_and_allow_zero_override(harness, monkeypatch):
    seen = []
    harness.settings["scan"]["length_limits"] = {"video": [180, None], "reel": [None, 90]}
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main([]) == 0
    assert seen[0].length_limits == {"video": (180, None), "reel": (None, 90)}
    assert pipeline.main(["--video-min-seconds", "0", "--reel-max-seconds", "60"]) == 0
    assert seen[1].length_limits == {"video": (None, None), "reel": (None, 60)}


@pytest.mark.parametrize("args", [
    ["--video-min-seconds", "180", "--video-max-seconds", "90"],
    ["--reel-max-seconds", "-1"],
])
def test_cli_rejects_invalid_length_limits(harness, args):
    with pytest.raises(SystemExit):
        pipeline.main(args)


def test_missing_views_are_filled_and_persisted_before_filtering(harness, monkeypatch):
    h = harness
    h.rows["large"][0]["views"] = None
    filled = []

    def fill(video):
        filled.append(video.video_id)
        video.views = 90_000

    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", fill)
    h.run()
    assert filled == ["v1"]
    assert len(h.video_saved) == 2
    assert h.exports[0][0][0].views == 90_000
    assert h.exports[0][2]["pages"][0]["passed"] == 1
    assert h.jev_calls == ["v1"]


@pytest.mark.parametrize("missing", ["views", "reactions", "comments", "shares", "posted_at", "duration_s", "caption"])
def test_each_missing_field_triggers_metadata_fallback_even_if_filtered_out(harness, monkeypatch, missing):
    row = harness.rows["large"][0]
    row.update(views=1, posted_at="2026-10-01T00:00:00Z", duration_s=60, caption="Nội dung")
    row[missing] = "" if missing == "caption" else None
    calls = []
    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", lambda video: calls.append(video.video_id))
    harness.run()
    assert calls == ["v1"]
    assert harness.exports[0][0] == []


def test_metadata_error_is_a_video_note_and_run_continues(harness, monkeypatch):
    def fail(video):
        raise ValueError("Không lấy được metadata")

    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", fail)
    harness.run()
    assert "Không lấy được metadata" in harness.exports[0][0][0].notes
    assert harness.jev_calls == ["v1"]


def test_stop_during_metadata_fallback_prevents_more_calls(harness, monkeypatch):
    h = harness
    h.rows["large"].append(dict(h.rows["large"][0], video_id="v2"))
    stop = Event()
    calls = []

    def fill(video):
        calls.append(video.video_id)
        stop.set()

    monkeypatch.setattr(pipeline.ytdlp, "fill_missing", fill)
    h.run(stop)
    assert calls == ["v1"]
    assert h.transcript_calls == []
    assert h.commentary_calls == []


def test_deepgram_auth_pauses_and_exports_partial(harness, monkeypatch):
    def fail(*args):
        raise AuthError("deepgram", "Key bị từ chối")

    monkeypatch.setattr(pipeline.transcript, "get_transcript", fail)
    harness.run()
    assert len(harness.exports[0][0]) == 1
    assert harness.exports[0][2]["messages"] == [
        "API key [Deepgram] không hợp lệ. Vào Cài đặt để nhập lại."
    ]
    assert harness.jev_calls == []
    assert harness.commentary_calls == []
    assert harness.progress[-1].message == "Đã xuất kết quả một phần."


def test_deepgram_quota_warning_is_logged_and_analysis_continues(harness, monkeypatch):
    warning = "Tài khoản Deepgram đã hết credit/hạn mức. Đã dùng local whisper."

    def get(video, key, stt, terms, tmp, warnings):
        warnings.append(warning)
        video.transcript = "Thoại dự phòng"
        return 0.0

    monkeypatch.setattr(pipeline.transcript, "get_transcript", get)
    harness.run()
    assert warning in harness.exports[0][2]["messages"]
    assert harness.exports[0][2]["usage"]["deepgram_minutes"] == 0.0
    assert harness.jev_calls == ["v1"]


@pytest.mark.parametrize("choice", ["pause", "continue", None])
def test_llm_quota_choice_controls_remaining_analysis(harness, choice):
    h = harness
    h.rows["large"].append(dict(h.rows["large"][0], video_id="v2"))
    h.llm_error = QuotaError("llm", "Tài khoản LLM đã hết credit/hạn mức.")
    questions = []

    def ask(kind, message, options):
        questions.append((kind, message, options))
        return choice

    h.run(ask_user=ask if choice is not None else None)
    assert h.analysis_calls == ["v1"]
    assert h.commentary_calls == []
    assert h.jev_calls == (["v1"] if choice == "pause" else ["v1", "v2"])
    assert len(h.exports[0][0]) == 2
    if choice is None:
        assert questions == []
        assert any("mặc định CLI" in text for text in h.exports[0][2]["messages"])
    else:
        assert questions == [("llm_quota", "Tài khoản LLM đã hết credit/hạn mức.",
                              [("continue", "Chạy tiếp không có gợi ý"), ("pause", "Tạm dừng")])]
    decision = "tạm dừng" if choice == "pause" else "tiếp tục không có gợi ý"
    assert any(decision in text for text in h.exports[0][2]["messages"])
    assert h.progress[-1].message == (
        "Đã xuất kết quả một phần." if choice == "pause" else "Đã xuất kết quả."
    )


@pytest.mark.parametrize("choice", ["pause", "continue", None])
def test_commentary_quota_uses_same_user_choice(harness, monkeypatch, choice):
    def fail(*args):
        raise QuotaError("llm", "Hết credit")

    monkeypatch.setattr(pipeline.llm_client, "write_commentary", fail)
    questions = []

    def ask(*args):
        questions.append(args)
        return choice

    harness.run(ask_user=ask if choice is not None else None)
    assert len(harness.exports) == 1
    assert len(questions) == (0 if choice is None else 1)
    done_text = "Đã xuất kết quả một phần." if choice == "pause" else "Đã xuất kết quả."
    assert harness.progress[-1].message == (
        f"{done_text} {pipeline.usage_summary(harness.exports[0][2]['usage'])}"
    )


def test_parallel_analysis_asks_llm_quota_once_and_keeps_export_order(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(pipeline, "ANALYZE_WORKERS", 3)
    for video_id in ("v2", "v3"):
        h.rows["large"].append(dict(h.rows["large"][0], video_id=video_id))
    h.llm_error = QuotaError("llm", "Tài khoản LLM đã hết credit/hạn mức.")
    together = Barrier(3, timeout=5)  # cả ba video tới bước LLM cùng lúc, cùng gặp hết hạn mức
    write_analysis = pipeline.llm_client.write_analysis

    def analysis(*args):
        together.wait()
        return write_analysis(*args)

    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    questions = []
    h.run(ask_user=lambda *args: questions.append(args) or "continue")
    assert len(questions) == 1
    assert sorted(h.analysis_calls) == ["v1", "v2", "v3"]
    assert [video.video_id for video in h.exports[0][0]] == ["v1", "v2", "v3"]
    assert h.exports[0][2]["pages"][0]["analyzed"] == 3


def test_first_page_analysis_overlaps_next_page_scan(harness, monkeypatch):
    h = harness
    h.channels.append("second")
    h.pages["second"] = Page("second", "Kênh thứ hai", 100)
    h.rows["second"] = [dict(h.rows["large"][0], video_id="v2")]
    started, second_scanned = Event(), Event()
    ordering = []
    original_analysis = pipeline.llm_client.write_analysis

    def analysis(client, model, video, *args):
        ordering.append(f"analyze:{video.video_id}")
        if video.video_id == "v1":
            started.set()
            assert second_scanned.wait(5)
        return original_analysis(client, model, video, *args)

    def scan(url, stop):
        ordering.append(f"scan:{url}")
        if url == "second":
            assert started.is_set()
            second_scanned.set()

    h.scan_hook = scan
    h.pause_hook = lambda stop: started.wait(5)
    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    assert h.run() is not None
    assert ordering == ["scan:large", "analyze:v1", "scan:second", "analyze:v2"]
    assert [video.video_id for video in h.exports[0][0]] == ["v1", "v2"]
    assert [page["passed"] for page in h.exports[0][2]["pages"]] == [1, 1]
    assert [page["analyzed"] for page in h.exports[0][2]["pages"]] == [1, 1]
    events = [p for p in h.progress if p.stage == "analyze"]
    assert events[0].message.startswith("Video 1:")
    assert events[0].steps == 1
    assert events[-1].step == events[-1].steps == 2


def test_rest_between_channels_counts_down_without_flooding_the_log(harness, caplog):
    h = harness
    h.channels.append("second")
    h.pages["second"] = Page("second", "Kênh thứ hai", 100)
    h.rows["second"] = [dict(h.rows["large"][0], video_id="v2")]

    with caplog.at_level("INFO", logger="pipeline"):
        assert h.run() is not None

    ticks = [p for p in h.progress if "còn" in p.message and "giây" in p.message]
    assert [p.message.rsplit("· ", 1)[1] for p in ticks] == ["còn 2 giây", "còn 1 giây"]
    assert all(p.transient for p in ticks)
    assert not any("còn 2 giây" in record.getMessage() for record in caplog.records)



@pytest.mark.parametrize("error", [
    AuthError("jev", "Key Jev không hợp lệ."),
    NetworkError("jev", "Không kết nối được tới Jev."),
    QuotaError("llm", "LLM hết hạn mức."),
])
def test_fatal_analysis_interrupts_pause_before_later_pages(harness, error):
    h = harness
    for url in ("second", "third"):
        h.channels.append(url)
        h.pages[url] = Page(url, url, 100)
        h.rows[url] = [dict(h.rows["large"][0], video_id=url)]
    if isinstance(error, QuotaError):
        h.llm_error = error
    else:
        h.jev_error = error
    interrupted = []

    def pause(stop):
        interrupted.append(stop.wait(5))

    h.pause_hook = pause
    user_stop = Event()
    assert h.run(user_stop, ask_user=lambda *args: "pause") is not None
    assert h.scans == ["large"]
    assert not user_stop.is_set()
    assert all(interrupted)
    assert [video.video_id for video in h.exports[0][0]] == ["v1"]
    assert h.commentary_calls == []
    assert h.progress[-1].message == "Đã xuất kết quả một phần."


def test_stop_during_second_page_exports_rows_not_yet_filtered(harness):
    h = harness
    h.channels.append("second")
    h.pages["second"] = Page("second", "Kênh thứ hai", 100)
    h.rows["second"] = [dict(h.rows["large"][0], video_id="v2")]
    stop = Event()

    def scan(url, combined_stop):
        if url == "second":
            stop.set()

    h.scan_hook = scan
    assert h.run(stop) is not None
    assert [video.video_id for video in h.exports[0][0]] == ["v1", "v2"]
    assert [page["passed"] for page in h.exports[0][2]["pages"]] == [1, 1]
    assert "v2" not in h.jev_calls


@pytest.mark.parametrize("formats", ["video_live", "reel_live", "video,reel", "video,reel,video_live,reel_live"])
def test_cli_accepts_live_kinds(harness, monkeypatch, formats):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main(["--formats", formats]) == 0
    assert seen[0].formats == set(formats.split(","))


@pytest.mark.parametrize("formats", ["post,video_live", "live", ""])
def test_cli_rejects_mixed_posts_or_unknown_kinds(formats):
    with pytest.raises(SystemExit):
        pipeline.main(["--formats", formats])


def test_pipeline_preserves_collected_live_flag(harness):
    h = harness
    h.params.formats = {"video_live"}
    h.rows["large"][0].update(format="video", is_live=True)
    assert h.run() is not None
    assert h.video_saved[0].is_live is True
    assert h.exports[0][0][0].is_live is True
    assert h.exports[0][2]["params"]["formats"] == ["video_live"]
    assert h.scan_formats == [{"video_live"}]


def test_cli_defaults_exclude_live(harness, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main([]) == 0
    assert seen[0].formats == {"video", "reel"}


def test_post_images_unsupported_model_stops_before_scanning(harness, monkeypatch):
    h = harness
    h.params = pipeline.RunParams(14, {"post"})
    h.settings["scan"]["read_images"] = True
    monkeypatch.setattr(pipeline.llm_client, "check_vision", lambda *args: False)
    monkeypatch.setattr(pipeline.config, "save_settings", lambda settings: None)
    assert h.run() is None
    assert h.scans == []
    assert any("không nhận ảnh" in p.message for p in h.progress)


def test_post_images_cached_description_avoids_reading_and_text_analysis_cache(harness, monkeypatch):
    h = harness
    h.params = pipeline.RunParams(14, {"post"})
    h.settings["scan"]["read_images"] = True
    llm = h.settings["llm"]
    llm["vision"] = {"base_url": llm["base_url"], "model": llm["model"], "ok": True}
    h.rows["large"][0].update(format="post", caption="Caption", image_urls=["image"])
    h.llm_cache["v1"] = {"chu_de_bai": "text-only stale"}
    monkeypatch.setattr(pipeline.db, "get_transcript", lambda ident: ("Image words", "images"))
    monkeypatch.setattr(pipeline, "download_images", lambda urls: pytest.fail("cached images downloaded"))
    assert h.run() is not None
    post = h.exports[0][0][0]
    assert post.transcript == "Image words"
    assert post.transcript_status == "images"
    assert h.analysis_calls == ["v1"]


def test_login_required_mid_tab_exports_rows_collected_before_failure(harness):
    h = harness

    def login_failure(url, stop_event):
        error = LoginRequired("facebook", "Phiên Facebook hết hạn")
        error.partial_rows = deepcopy(h.rows[url])
        raise error

    h.scan_hook = login_failure
    h.run()
    assert [video.video_id for video in h.video_saved] == ["v1"]
    assert [video.video_id for video in h.exports[0][0]] == ["v1"]
    assert h.exports[0][2]["pages"][0]["scanned"] == 1
    assert h.scans == ["large"]


def test_item_and_commentary_turns_sum_to_usage(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(pipeline, "ANALYZE_WORKERS", 3)
    together = Barrier(3, timeout=5)
    original = pipeline.llm_client.write_analysis

    def analysis(*args):
        together.wait()
        return original(*args)

    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    for video_id in ("v2", "v3"):
        h.rows["large"].append(dict(h.rows["large"][0], video_id=video_id))
    assert h.run() is not None
    completed = [p for p in h.progress if p.turn and p.stage == "analyze"]
    assert len(completed) == 3
    assert {p.turn["label"] for p in completed} == {"Video 1", "Video 2", "Video 3"}
    expected = {"llm_calls": 1, "llm_tokens": 12, "llm_output_tokens": 4,
                "llm_seconds": 2.0, "jev_calls": 2, "jev_tokens": 14, "deepgram_minutes": 0.5}
    for event in completed:
        assert event.turn == {"label": event.turn["label"], **expected}
        assert "LLM 4 token trong 2,0 giây (2 token/giây)" in event.message
    commentary = [p for p in h.progress if p.turn and p.stage == "export"]
    assert len(commentary) == 1
    assert commentary[0].turn == {
        "label": "Nhận xét tổng hợp", "llm_calls": 1, "llm_tokens": 5,
        "llm_output_tokens": 2, "llm_seconds": 1.0, "jev_calls": 0,
        "jev_tokens": 0, "deepgram_minutes": 0.0,
    }
    usage = h.exports[0][2]["usage"]
    for key in expected:
        assert sum(p.turn[key] for p in completed + commentary) == usage[key]
    assert usage["deepgram_calls"] == 3


def test_usage_refreshes_follow_calls_without_log_entries(harness, caplog):
    with caplog.at_level("INFO", logger="pipeline"):
        assert harness.run() is not None
    updates = [p for p in harness.progress if not p.message]
    assert len(updates) == 5  # Deepgram, nhãn Jev, phân tích LLM, kiểm tra Jev, nhận xét LLM
    assert all(p.transient and p.turn is None for p in updates)
    assert [p.stage for p in updates] == ["analyze"] * 4 + ["export"]
    assert [(p.usage["deepgram_calls"], p.usage["jev_calls"], p.usage["llm_calls"])
            for p in updates] == [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 2, 1), (1, 2, 2)]
    assert [p.usage["llm_tokens"] for p in updates] == [0, 0, 12, 12, 17]
    assert all(p.page_url == "large" and p.page_index == 1 for p in updates)
    assert not any(record.getMessage() == "" for record in caplog.records)
    assert "" not in harness.exports[0][2]["messages"]


@pytest.mark.parametrize("cached", [False, True])
def test_completion_turn_exists_for_irrelevant_and_cached_analysis(harness, cached):
    if cached:
        harness.llm_cache["v1"] = {"chu_de_bai": "Đã lưu"}
    else:
        harness.relevant = 0.49
    assert harness.run() is not None
    turns = [p.turn for p in harness.progress if p.turn and p.stage == "analyze"]
    assert turns == [{"label": "Video 1", "llm_calls": 0, "llm_tokens": 0,
                      "llm_output_tokens": 0, "llm_seconds": 0.0, "jev_calls": 1,
                      "jev_tokens": 10, "deepgram_minutes": 0.5}]


def test_retry_turn_includes_both_analysis_and_suggestion_checks(harness):
    harness.reject_suggestions = True
    assert harness.run() is not None
    turn = next(p.turn for p in harness.progress if p.turn and p.stage == "analyze")
    assert turn["llm_calls"] == 2
    assert turn["llm_tokens"] == 24
    assert turn["llm_output_tokens"] == 8
    assert turn["llm_seconds"] == 4.0
    assert turn["jev_calls"] == 3
    assert turn["jev_tokens"] == 18


def test_deepgram_reports_each_segment_including_zero_minutes(harness, monkeypatch):
    durations = iter((0.0, 30.0))
    monkeypatch.setattr(pipeline.transcript, "transcribe_deepgram",
                        lambda *args: {"text": "Thoại", "duration": next(durations)})

    def get(video, key, stt, terms, tmp, warnings):
        minutes = 0.0
        for number in range(2):
            _, billed = pipeline.transcript._transcribe(Path("audio.mp3"), key, stt, terms, warnings)
            minutes += billed
            updates = [p for p in harness.progress if not p.message]
            assert updates[-1].usage["deepgram_calls"] == number + 1
        return minutes

    monkeypatch.setattr(pipeline.transcript, "get_transcript", get)
    assert harness.run() is not None
    usage = harness.exports[0][2]["usage"]
    assert usage["deepgram_calls"] == 2
    assert usage["deepgram_minutes"] == 0.5


def test_cached_transcript_does_not_count_deepgram(harness, monkeypatch):
    monkeypatch.setattr(pipeline.transcript, "get_transcript", lambda *args: 0.0)
    assert harness.run() is not None
    usage = harness.exports[0][2]["usage"]
    assert usage["deepgram_calls"] == 0
    assert usage["deepgram_minutes"] == 0.0
    assert next(p.turn for p in harness.progress if p.turn)["deepgram_minutes"] == 0.0


def test_llm_usage_refreshes_before_internal_retry_returns(harness, monkeypatch):
    invocations = []

    def analysis(*args):
        invocations.append(True)
        for number in (1, 2):
            pipeline.llm_client._record(
                SimpleNamespace(usage=SimpleNamespace(total_tokens=6, completion_tokens=2)), 1.0)
            update = next(p for p in reversed(harness.progress) if not p.message)
            assert update.usage["llm_calls"] == number
            assert update.usage["llm_tokens"] == number * 6
        return {"_usage": 12,
                "goi_y_nhan_ban": [{"hook_moi": "Mẹo nhà thuốc", "y_tuong": "Một góc mới"}]}

    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    assert harness.run() is not None
    assert invocations == [True]
    assert harness.exports[0][2]["messages"] == []
    turn = next(p.turn for p in harness.progress if p.turn and p.stage == "analyze")
    assert turn["llm_calls"] == 2
    assert turn["llm_tokens"] == 12
    assert turn["llm_output_tokens"] == 4
    assert turn["llm_seconds"] == 2.0


def test_post_image_usage_is_included_in_item_turn(harness, monkeypatch):
    h = harness
    h.params = pipeline.RunParams(14, {"post"})
    h.settings["scan"]["read_images"] = True
    llm = h.settings["llm"]
    llm["vision"] = {"base_url": llm["base_url"], "model": llm["model"], "ok": True}
    h.rows["large"][0].update(format="post", caption="Caption", image_urls=["image"])
    monkeypatch.setattr(pipeline.db, "get_transcript", lambda ident: None)
    monkeypatch.setattr(pipeline.db, "save_transcript", lambda *args: None)
    monkeypatch.setattr(pipeline, "download_images", lambda urls: [b"image"])

    def describe(*args):
        pipeline.llm_client._record(
            SimpleNamespace(usage=SimpleNamespace(total_tokens=9, completion_tokens=3)), 1.5)
        return "Chữ trên ảnh", 9

    monkeypatch.setattr(pipeline.llm_client, "describe_images", describe)
    assert h.run() is not None
    turn = next(p.turn for p in h.progress if p.turn and p.stage == "analyze")
    assert turn["label"] == "Bài đăng 1"
    assert turn["llm_calls"] == 2
    assert turn["llm_tokens"] == 21
    assert turn["llm_output_tokens"] == 7
    assert turn["llm_seconds"] == 3.5
    assert turn["deepgram_minutes"] == 0.0
    assert h.exports[0][2]["usage"]["deepgram_calls"] == 0


def test_successful_llm_request_before_error_still_counts(harness, monkeypatch):
    def analysis(*args):
        pipeline.llm_client._record(
            SimpleNamespace(usage=SimpleNamespace(total_tokens=6, completion_tokens=2)), 1.0)
        raise ValueError("Không đọc được kết quả")

    monkeypatch.setattr(pipeline.llm_client, "write_analysis", analysis)
    assert harness.run() is not None
    turn = next(p.turn for p in harness.progress if p.turn and p.stage == "analyze")
    assert turn["llm_calls"] == 1
    assert turn["llm_tokens"] == 6
    assert turn["llm_output_tokens"] == 2
    assert turn["llm_seconds"] == 1.0
    assert harness.exports[0][2]["usage"]["llm_tokens"] == 11


def test_failed_jev_call_counts_without_tokens(harness):
    harness.jev_error = AuthError("jev", "Key Jev bị từ chối")
    assert harness.run() is not None
    usage = harness.exports[0][2]["usage"]
    assert usage["jev_calls"] == 1
    assert usage["jev_tokens"] == 0
    assert any(not p.message and p.usage["jev_calls"] == 1 for p in harness.progress)
