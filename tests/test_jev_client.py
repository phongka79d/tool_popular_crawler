"""Offline tests for jev_client: label interpretation, suggestion check, cache, state, key check."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import config
import jev_client
from errors import AuthError, ServiceError
from models import Video

TAXONOMY = config.load_json("taxonomy.json")
SETTINGS = {
    "jev": {"model": "jev-1.13", "yes_threshold": 0.5, "min_confidence": 0.6},
    "my_page": {"name": "Thế Thảo Pharma", "audience": "Chủ nhà thuốc, dược sĩ"},
}
LABEL_QIDS = {
    "topic", "hook_type", "structure", "cta", "hook_strength",
    "cam_xuc_manh", "gia_tri_thuc_tien", "ket_thuc_tron_y", "kha_nang_chia_se",
    "relevant", "replicable", "risk_absolute", "risk_compare",
}
ZERO = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def make_video(**overrides) -> Video:
    fields = {
        "video_id": "vid1",
        "url": "https://example.test/v/1",
        "page_url": "https://example.test/page",
        "caption": "Chủ đề",
        "transcript": "Nội dung",
        "hook": "",
    }
    fields.update(overrides)
    return Video(**fields)


def _choice(code: str, confidence: float = 0.9) -> dict:
    return {"type": "choice", "choice": code, "confidence": confidence, "probabilities": {code: confidence}}


def _score(value: float, confidence: float = 0.9) -> dict:
    return {"type": "score", "score": value, "confidence": confidence, "probabilities": {}}


def _noul(p: float) -> dict:
    return {"type": "noul", "noul": p}


def base_raw() -> dict:
    """Raw answers in the plain form stored by jev_client."""
    return {
        "topic": _choice("phap_ly_gpp"),
        "hook_type": _choice("cau_hoi"),
        "structure": _choice("van_de_giai_phap"),
        "cta": _choice("binh_luan"),
        "hook_strength": _score(2.0),
        "cam_xuc_manh": _score(1.0),
        "gia_tri_thuc_tien": _score(1.0),
        "ket_thuc_tron_y": _score(2.0),
        "kha_nang_chia_se": _score(1.0),
        "relevant": _noul(0.9),
        "replicable": _noul(0.8),
        "risk_absolute": _noul(0.1),
        "risk_compare": _noul(0.1),
    }


def sdk_response(raw: dict, input_tokens=100, output_tokens=20) -> SimpleNamespace:
    """Build an SDK-shaped response (.choices/.scores/.nouls/.usage) from plain answers."""
    choices, scores, nouls = {}, {}, {}
    for qid, answer in raw.items():
        if answer["type"] == "choice":
            choices[qid] = SimpleNamespace(
                choice=answer["choice"],
                confidence=answer["confidence"],
                probabilities=answer["probabilities"],
            )
        elif answer["type"] == "score":
            scores[qid] = SimpleNamespace(
                score=answer["score"],
                confidence=answer["confidence"],
                probabilities=answer["probabilities"],
                legend={},
            )
        else:
            nouls[qid] = SimpleNamespace(noul=answer["noul"])
    return SimpleNamespace(
        model="jev-1.13",
        request_id="req-1",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        choices=choices,
        scores=scores,
        nouls=nouls,
    )


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []
        self.closed = False

    def system_one(self, state, questions, model=None, **_kwargs):
        self.calls.append({"state": state, "questions": questions, "model": model})
        return self.response

    def close(self):
        self.closed = True


class FakeDb:
    def __init__(self):
        self.rows: dict[tuple[str, str, str], dict] = {}
        self.saved: list[tuple] = []

    def get_jev(self, video_id, model, kind):
        return self.rows.get((video_id, model, kind))

    def save_jev(self, video_id, model, kind, answers, usage):
        self.saved.append((video_id, model, kind, answers, usage))
        self.rows[(video_id, model, kind)] = answers


@pytest.fixture
def fake_db(monkeypatch) -> FakeDb:
    fake = FakeDb()
    monkeypatch.setattr(jev_client, "db", fake)
    return fake


@pytest.fixture
def raw() -> dict:
    return base_raw()


# --- interpret_labels -------------------------------------------------------

@pytest.mark.parametrize(
    ("confidence", "unsure"),
    [(0.59, True), (0.6, False), (0.95, False)],
)
def test_low_confidence_choice_gets_unsure_suffix(raw, confidence, unsure):
    raw["topic"]["confidence"] = confidence
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    expected = TAXONOMY["labels"]["phap_ly_gpp"] + (" (chưa chắc)" if unsure else "")
    assert out["topic"] == expected
    assert out["topic_code"] == "phap_ly_gpp"
    assert ("topic" in out["uncertain"]) is unsure


def test_low_confidence_score_listed_as_uncertain(raw):
    raw["hook_strength"]["confidence"] = 0.4
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert "hook_strength" in out["uncertain"]
    assert out["confidence"]["hook_strength"] == 0.4


@pytest.mark.parametrize(
    ("p", "text"),
    [(0.5, "Có"), (0.49, "Không"), (0.9, "Có"), (0.0, "Không")],
)
def test_noul_becomes_yes_no_at_threshold(raw, p, text):
    raw["relevant"]["noul"] = p
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["relevant"] == text
    assert out["relevant_p"] == p


@pytest.mark.parametrize(
    ("absolute", "compare", "flags"),
    [
        (0.7, 0.2, ["risk_absolute"]),
        (0.2, 0.7, ["risk_compare"]),
        (0.5, 0.5, ["risk_absolute", "risk_compare"]),
        (0.1, 0.1, []),
    ],
)
def test_risk_flags_list_only_high_risk(raw, absolute, compare, flags):
    raw["risk_absolute"]["noul"] = absolute
    raw["risk_compare"]["noul"] = compare
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["risk_flags"] == [TAXONOMY["labels"][key] for key in flags]


@pytest.mark.parametrize(
    ("score", "level"),
    [(-0.3, 0), (0.0, 0), (0.4, 0), (0.5, 1), (1.4, 1), (1.5, 2), (2.0, 2), (2.7, 2)],
)
def test_hook_strength_rounds_to_level_0_to_2(raw, score, level):
    raw["hook_strength"]["score"] = score
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["hook_strength"] == level


def test_extra_scores_kept_as_floats_and_codes_exposed(raw):
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["cam_xuc_manh"] == 1.0
    assert out["ket_thuc_tron_y"] == 2.0
    assert out["structure_code"] == "van_de_giai_phap"
    assert out["cta_code"] == "binh_luan"


def test_jev_viral_is_mean_of_raw_scores(raw):
    values = [0.2, 0.4, 0.6, 0.8, 1.0]
    for key, value in zip(("hook_strength", *jev_client.EXTRA_SCORES), values):
        raw[key]["score"] = value
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["jev_viral"] == pytest.approx(0.6)


@pytest.mark.parametrize("value, expected", [(-0.2, 0.0), (2.0, 1.0)])
def test_jev_viral_is_bounded_for_legacy_raw_scores(raw, value, expected):
    for key in ("hook_strength", *jev_client.EXTRA_SCORES):
        raw[key]["score"] = value
    assert jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)["jev_viral"] == expected


# --- build_state / build_questions -------------------------------------------

def test_build_state_truncates_caption_and_transcript():
    video = make_video(caption="a" * 2000, transcript="b" * 5000, hook="")
    state = jev_client.build_state(video, "Page X")
    assert len(state["caption"]) == 1500
    assert len(state["transcript"]) == 3000
    assert state["hook"] == "a" * 200
    assert state["my_page"] == "Page X"


def test_build_state_prefers_video_hook():
    video = make_video(caption="Nội dung dài", hook="Câu mở đầu")
    assert jev_client.build_state(video, "Page X")["hook"] == "Câu mở đầu"


def test_build_state_handles_missing_text():
    video = make_video(caption=None, transcript=None, hook="")
    state = jev_client.build_state(video, "Page X")
    assert state["caption"] == ""
    assert state["transcript"] == ""
    assert state["hook"] == ""


def test_build_questions_covers_every_label_question():
    assert set(jev_client.build_questions(TAXONOMY)) == LABEL_QIDS


def test_post_state_uses_first_caption_line_without_transcript():
    video = make_video(format="post", caption="Dòng mở bài\nNội dung bài", hook="Hook cũ", transcript="Thoại cũ")
    state = jev_client.build_state(video, "Page X")
    assert state["hook"] == "Dòng mở bài"
    assert state["caption"] == video.caption
    assert "transcript" not in state


def test_post_questions_use_caption_and_keep_all_interpretable_keys(raw):
    questions = jev_client.build_questions(TAXONOMY, is_post=True)
    assert set(questions) == LABEL_QIDS
    for question in questions.values():
        assert "transcript" not in question.instructions
    for key in ("topic", "structure", "cta", *jev_client.EXTRA_SCORES):
        assert "`caption`" in questions[key].instructions
    assert "mở – thân – kết" in questions["structure"].instructions
    assert "jev_viral" in jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)


def test_video_structure_and_extra_questions_fall_back_to_caption():
    questions = jev_client.build_questions(TAXONOMY)
    for key in ("structure", *jev_client.EXTRA_SCORES):
        assert "`caption`" in questions[key].instructions
        assert "không có thoại" in questions[key].instructions


def test_taxonomy_has_escape_options_and_labels_for_every_code():
    for key in jev_client.CHOICE_KEYS:
        assert "khac" in TAXONOMY[key]
        assert list(TAXONOMY[key])[-1] == "khac"
        for code in TAXONOMY[key]:
            assert TAXONOMY["labels"][code], code
    assert "khong_co" in TAXONOMY["cta"]
    assert "risk_absolute" in TAXONOMY["labels"]
    assert "risk_compare" in TAXONOMY["labels"]


def test_cta_question_references_both_source_fields_and_escape_options():
    question = jev_client.build_questions(TAXONOMY)["cta"]
    assert "`transcript`" in question.instructions
    assert "`caption`" in question.instructions
    assert question.criteria == TAXONOMY["cta"]
    assert question.criteria["khac"] != question.criteria["khong_co"]
    assert "Có lời kêu gọi hành động" in question.criteria["khac"]
    assert "Không có lời kêu gọi hành động" in question.criteria["khong_co"]


@pytest.mark.parametrize("code", [
    "chuyen_gia_uy_tin", "pha_mach_bat_ngo", "hua_hen_ket_qua",
    "goc_nhin_ca_nhan", "hanh_trinh_thay_doi", "menh_lenh_truc_tiep",
    "xung_dot_tranh_cai", "tiet_lo_ket_qua_truoc",
])
def test_reference_hook_types_have_examples_and_display_labels(raw, code):
    criteria = jev_client.build_questions(TAXONOMY)["hook_type"].criteria
    assert code in criteria
    assert "Ví dụ:" in criteria[code]
    raw["hook_type"] = _choice(code)
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["hook_type_code"] == code
    assert out["hook_type"] == TAXONOMY["labels"][code]


def test_hot_take_uses_stable_existing_code():
    assert "hot take" in TAXONOMY["hook_type"]["xung_dot_tranh_cai"]
    assert "quan_diem_gay_tranh_cai" not in TAXONOMY["hook_type"]


def test_other_cta_is_preserved_as_distinct_from_no_cta(raw):
    raw["cta"] = _choice("khac")
    out = jev_client.interpret_labels(raw, SETTINGS, TAXONOMY)
    assert out["cta_code"] == "khac"
    assert out["cta"] == "Khác"


# --- ask_labels ----------------------------------------------------------------

def test_ask_labels_miss_calls_once_saves_and_returns_raw(fake_db, raw, monkeypatch):
    client = FakeClient(sdk_response(raw))
    services: list[str] = []

    def record_retry(fn, *, service, **_kwargs):
        services.append(service)
        return fn()

    monkeypatch.setattr(jev_client, "with_retry", record_retry)
    answers, usage = jev_client.ask_labels(client, make_video(), TAXONOMY, SETTINGS)

    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "jev-1.13"
    assert set(client.calls[0]["questions"]) == LABEL_QIDS
    assert services == ["jev"]
    assert answers == raw
    assert usage == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    assert fake_db.saved == [("vid1", "jev-1.13", jev_client.LABELS_KIND, raw, usage)]


def test_ask_labels_none_usage_counts_as_zero(fake_db, raw):
    client = FakeClient(sdk_response(raw, input_tokens=None, output_tokens=None))
    _, usage = jev_client.ask_labels(client, make_video(), TAXONOMY, SETTINGS)
    assert usage == ZERO


def test_ask_labels_cache_hit_makes_no_call(fake_db, raw):
    fake_db.rows[("vid1", "jev-1.13", jev_client.LABELS_KIND)] = raw
    client = FakeClient(sdk_response(raw))
    answers, usage = jev_client.ask_labels(client, make_video(), TAXONOMY, SETTINGS)
    assert client.calls == []
    assert fake_db.saved == []
    assert answers == raw
    assert usage == ZERO


def test_ask_labels_cache_is_keyed_by_model(fake_db, raw):
    fake_db.rows[("vid1", "jev-1.13", jev_client.LABELS_KIND)] = raw
    other = {**SETTINGS, "jev": {**SETTINGS["jev"], "model": "jev-2"}}
    client = FakeClient(sdk_response(raw))
    jev_client.ask_labels(client, make_video(), TAXONOMY, other)
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "jev-2"
    assert fake_db.saved[0][1:3] == ("jev-2", jev_client.LABELS_KIND)


def test_ask_labels_missing_answer_raises_and_does_not_cache(fake_db, raw):
    del raw["kha_nang_chia_se"]
    client = FakeClient(sdk_response(raw))
    with pytest.raises(ServiceError):
        jev_client.ask_labels(client, make_video(), TAXONOMY, SETTINGS)
    assert fake_db.saved == []


def test_ask_labels_ignores_old_labels_cache(fake_db, raw):
    fake_db.rows[("vid1", "jev-1.13", "labels")] = raw
    client = FakeClient(sdk_response(raw))
    jev_client.ask_labels(client, make_video(), TAXONOMY, SETTINGS)
    assert len(client.calls) == 1
    assert fake_db.saved[0][2] == "labels_v2"


def test_ask_labels_post_uses_caption_only_and_interprets_every_answer(fake_db, raw):
    client = FakeClient(sdk_response(raw))
    answers, _ = jev_client.ask_labels(client, make_video(format="post"), TAXONOMY, SETTINGS)
    call = client.calls[0]
    assert "transcript" not in call["state"]
    assert set(call["questions"]) == set(answers)
    assert "jev_viral" in jev_client.interpret_labels(answers, SETTINGS, TAXONOMY)


# --- check_suggestions ---------------------------------------------------------

SUGGESTION = {"hook_moi": "Hook mới", "y_tuong": "Ý tưởng mới"}


def suggestion_raw(giu: float, chep: float, rui: float, index: int = 0) -> dict:
    return {
        f"giu_cong_thuc_{index}": _score(giu),
        f"chep_nguyen_{index}": _noul(chep),
        f"rui_ro_{index}": _noul(rui),
    }


def suggestion_video() -> Video:
    return make_video(jev={"hook_type": "Câu hỏi (chưa chắc)", "structure": "Vấn đề → giải pháp"})


@pytest.mark.parametrize(
    ("giu", "chep", "rui", "kept"),
    [
        (1.0, 0.5, 0.5, True),
        (0.5, 0.0, 0.0, True),
        (0.49, 0.0, 0.0, False),
        (2.0, 0.51, 0.0, False),
        (2.0, 0.0, 0.51, False),
        (2.0, 0.2, 0.3, True),
        (0.0, 0.0, 0.0, False),
    ],
)
def test_check_suggestions_applies_rejection_thresholds(giu, chep, rui, kept):
    answers = suggestion_raw(giu, chep, rui)
    client = FakeClient(sdk_response(answers))
    kept_list, raw, _usage = jev_client.check_suggestions(
        client, suggestion_video(), [SUGGESTION], SETTINGS
    )
    assert kept_list == ([SUGGESTION] if kept else [])
    assert len(client.calls) == 1
    assert raw == answers


def test_check_suggestions_one_call_keeps_order_and_builds_state():
    suggestions = [
        {"hook_moi": "h0", "y_tuong": "y0"},
        {"hook_moi": "h1", "y_tuong": "y1"},
        {"hook_moi": "h2", "y_tuong": "y2"},
    ]
    answers = {}
    answers.update(suggestion_raw(2.0, 0.0, 0.0, 0))
    answers.update(suggestion_raw(0.0, 0.0, 0.0, 1))
    answers.update(suggestion_raw(1.0, 0.5, 0.5, 2))
    client = FakeClient(sdk_response(answers))

    kept, _raw, usage = jev_client.check_suggestions(
        client, suggestion_video(), suggestions, SETTINGS
    )

    assert kept == [suggestions[0], suggestions[2]]
    assert len(client.calls) == 1
    expected_qids = {
        f"{prefix}_{i}" for i in range(3) for prefix in ("giu_cong_thuc", "chep_nguyen", "rui_ro")
    }
    assert set(client.calls[0]["questions"]) == expected_qids
    state = client.calls[0]["state"]
    assert state["kieu_hook_goc"] == "Câu hỏi"
    assert state["cau_truc_goc"] == "Vấn đề → giải pháp"
    assert state["goi_y"] == suggestions
    assert usage == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def test_check_suggestions_truncates_transcript_in_state():
    video = make_video(transcript="x" * 5000, jev={"hook_type": "Câu hỏi", "structure": "Vấn đề → giải pháp"})
    client = FakeClient(sdk_response(suggestion_raw(2.0, 0.0, 0.0)))
    jev_client.check_suggestions(client, video, [SUGGESTION], SETTINGS)
    assert len(client.calls[0]["state"]["transcript"]) == 3000


def test_post_suggestion_check_uses_caption_and_original_post_wording():
    video = suggestion_video()
    video.format = "post"
    video.caption = "Mở bài\nNội dung gốc"
    client = FakeClient(sdk_response(suggestion_raw(0.5, 0.0, 0.0)))
    kept, _, _ = jev_client.check_suggestions(client, video, [SUGGESTION], SETTINGS)
    assert kept == [SUGGESTION]
    call = client.calls[0]
    assert call["state"]["caption"] == video.caption
    assert "transcript" not in call["state"]
    assert "bài gốc" in call["questions"]["giu_cong_thuc_0"].instructions
    assert "`caption`" in call["questions"]["chep_nguyen_0"].instructions
    assert all("transcript" not in q.instructions for q in call["questions"].values())


def test_video_suggestion_check_includes_caption_and_compares_transcript():
    video = suggestion_video()
    client = FakeClient(sdk_response(suggestion_raw(0.5, 0.0, 0.0)))
    jev_client.check_suggestions(client, video, [SUGGESTION], SETTINGS)
    call = client.calls[0]
    assert call["state"]["caption"] == video.caption
    assert call["state"]["transcript"] == video.transcript
    assert "`transcript`" in call["questions"]["chep_nguyen_0"].instructions


def test_check_suggestions_empty_makes_no_call():
    client = FakeClient(None)
    kept, raw, usage = jev_client.check_suggestions(client, suggestion_video(), [], SETTINGS)
    assert kept == []
    assert raw == {}
    assert usage == ZERO
    assert client.calls == []


# --- make_client / check_key -----------------------------------------------------

@pytest.mark.parametrize("api_key", [None, ""])
def test_make_client_without_key_raises_auth_error(api_key):
    with pytest.raises(AuthError):
        jev_client.make_client(api_key, "jev-1.13")


def test_make_client_disables_sdk_retries(monkeypatch):
    captured: dict = {}

    class Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(jev_client, "TypeSafeClient", Recorder)
    jev_client.make_client("sk-test", "jev-1.13")
    assert captured["api_key"] == "sk-test"
    assert captured["model"] == "jev-1.13"
    assert captured["retry"].max_retries == 0


def test_make_client_maps_sdk_construction_error_to_auth_error(monkeypatch):
    def reject(**_kwargs):
        raise jev_client.TypeSafeError("bad key")

    monkeypatch.setattr(jev_client, "TypeSafeClient", reject)
    with pytest.raises(AuthError):
        jev_client.make_client("sk-bad", "jev-1.13")


def test_check_key_sends_one_noul_and_closes_client(monkeypatch):
    fake = FakeClient(None)
    monkeypatch.setattr(jev_client, "make_client", lambda api_key, model: fake)
    assert jev_client.check_key("sk-test", "jev-1.13") is None
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "jev-1.13"
    assert list(fake.calls[0]["questions"]) == ["loi_chao"]
    assert fake.closed


def test_check_key_closes_client_when_call_fails(monkeypatch):
    fake = FakeClient(None)

    def failing_system_one(**_kwargs):
        raise ValueError("boom")

    fake.system_one = failing_system_one
    monkeypatch.setattr(jev_client, "make_client", lambda api_key, model: fake)
    monkeypatch.setattr(jev_client, "with_retry", lambda fn, *, service, **_kw: fn())
    with pytest.raises(ValueError):
        jev_client.check_key("sk-test", "jev-1.13")
    assert fake.closed
