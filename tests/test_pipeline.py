"""Tests hors ligne du pipeline : aucun navigateur, réseau ni vraie clé."""
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import pipeline
from errors import AuthError, LoginRequired, NetworkError, QuotaError
from models import Page


@pytest.fixture
def harness(monkeypatch, tmp_path):
    state = SimpleNamespace(
        channels=["large"], pages={"large": Page("large", "Kênh lớn", 200_000)},
        rows={"large": [{"video_id": "v1", "url": "https://facebook.test/v1", "views": 100_000,
                         "reactions": 100, "comments": 20, "shares": 40}]},
        errors={}, scans=[], pauses=[], progress=[], exports=[], finished=[],
        page_saved=[], video_saved=[], label_cache={}, llm_cache={},
        jev_calls=[], analysis_calls=[], suggestion_calls=[], commentary_calls=[],
        relevant=0.9, jev_error=None, llm_error=None, login_error=None,
        scan_stop=None, reject_suggestions=False, transcript_calls=[],
    )
    settings = {
        "jev": {"model": "jev-test", "yes_threshold": 0.5, "min_confidence": 0.6},
        "llm": {"base_url": "https://llm.test/v1", "model": "llm-test", "temperature": 0.4},
        "stt": {"keyterms_file": "config/keyterms.txt"},
        "scan": {"max_videos_per_page": 200, "min_page_followers": 100_000},
        "score_weights": {"ratio_median": 40, "ratio_median_cap": 5,
                          "replicable": 25, "hook_strength": 20, "relevant": 15},
        "my_page": {"name": "Page dược", "audience": "Nhà thuốc"},
    }
    monkeypatch.setattr(pipeline.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(pipeline.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline.config, "load_json", lambda name: {})
    monkeypatch.setattr(pipeline.config, "load_settings", lambda: settings)
    monkeypatch.setattr(pipeline.config, "load_lines", lambda name: list(state.channels) if name == "config/channels.txt" else [])
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
            if state.scan_stop:
                state.scan_stop.set()
            return deepcopy(state.rows[url])

        def polite_page_pause(self, stop_event=None):
            state.pauses.append(True)

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
        return {"chu_de_bai": "Nghề dược", "_usage": 12,
                "goi_y_nhan_ban": [{"hook_moi": "Mẹo nhà thuốc", "y_tuong": "Một góc mới"}]}

    def check_suggestions(client, video, suggestions, *args):
        state.suggestion_calls.append(video.video_id)
        return ([] if state.reject_suggestions else suggestions), {}, {"total_tokens": 4}

    def commentary(client, model, summary):
        state.commentary_calls.append(deepcopy(summary))
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
    state.params = pipeline.RunParams(14, {"reel", "video"}, 100_000, {"views": 50_000}, "viral_tuyet_doi")
    state.settings = settings
    state.run = lambda stop=None: pipeline.run(state.params, settings, state.progress.append, stop or Event())
    return state


def test_below_threshold_page_is_skipped_and_recorded(harness):
    h = harness
    h.channels.insert(0, "small")
    h.pages["small"] = Page("small", "Kênh nhỏ", 99_999)
    assert h.run() is not None
    assert h.scans == ["large"]
    skipped = h.exports[0][2]["pages"][0]
    assert skipped["skipped_reason"] == "Dưới ngưỡng follower"
    assert skipped["scanned"] == 0
    assert h.pauses == [True]


def test_page_exception_does_not_stop_the_run(harness):
    h = harness
    h.channels.insert(0, "broken")
    h.errors["broken"] = ValueError("Không đọc được trang")
    assert h.run() is not None
    assert h.scans == ["large"]
    assert "Không đọc được trang" in h.exports[0][2]["pages"][0]["errors"]
    assert h.exports[0][2]["pages"][1]["analyzed"] == 1


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
    assert h.exports[0][2]["usage"] == {"jev_tokens": 14, "llm_tokens": 17, "deepgram_minutes": 0.5}


def test_cli_builds_requested_params(harness, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda params, settings, progress, stop: seen.append(params) or Path("result.xlsx"))
    assert pipeline.main(["--days", "14", "--preset", "no_bat_thuong", "--formats", "reel,video"]) == 0
    assert seen[0].days == 14
    assert seen[0].formats == {"reel", "video"}
    assert seen[0].preset == "no_bat_thuong"
