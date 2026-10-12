"""Test offline cho llm_client: client OpenAI được thay bằng bản giả, không gọi mạng, không cần khóa."""
from __future__ import annotations

import json
import unicodedata
from types import SimpleNamespace

import pytest

import llm_client
from config import load_lines
from errors import AuthError
from models import Video


class FakeStatusError(Exception):
    """Lỗi giống openai.APIStatusError: có status_code và thông báo chứa nội dung từ endpoint."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class FakeCompletions:
    def __init__(self, outcomes: tuple):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError("gọi LLM nhiều lần hơn dự kiến")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fake_client(*outcomes):
    completions = FakeCompletions(outcomes)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _reply(text: str, total: int = 10):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(total_tokens=total),
    )


SETTINGS = {"llm": {"base_url": "https://llm.test/v1", "model": "m-1", "temperature": 0.25}}
LABELS = {
    "topic": "Kiến thức bệnh",
    "hook_type": "Câu hỏi",
    "structure": "Vấn đề - giải pháp",
    "cta": "Bình luận",
}
VIDEO = Video(
    video_id="vid-1",
    url="https://fb.test/reel/1",
    page_url="https://fb.test/page",
    caption="Caption gốc",
    transcript="Thoại gốc của video",
    hook="Hook gốc",
)
VALID = {
    "chu_de_bai": "Dấu hiệu nhận biết sớm",
    "tom_tat": "Tóm tắt ngắn.",
    "hook_goc": "Hook gốc",
    "ly_do_viral": "Giả thuyết.",
    "goc_nhin": "Nhiều người nghĩ... đối lại Thực tế là...",
    "mau_hook_dien_cho_trong": "Chủ nhà thuốc nào cũng [ ] nhưng ít ai biết",
    "vi_tri_cta": "cuối video, mồi bình luận",
    "goi_y_nhan_ban": [{"hook_moi": "Hỏi dược sĩ trước khi uống", "y_tuong": "Giải thích GPP"}],
}


class TestParseJsonLoose:
    def test_fenced_json_is_parsed(self):
        text = '```json\n{"chu_de_bai": "A", "n": 1}\n```'
        assert llm_client.parse_json_loose(text) == {"chu_de_bai": "A", "n": 1}

    def test_bare_fence_is_parsed(self):
        assert llm_client.parse_json_loose('```\n{"a": 2}\n```') == {"a": 2}

    def test_prose_around_json_is_ignored(self):
        text = 'Đây là kết quả: {"tom_tat": "có {ngoặc} trong chữ"} Hết.'
        assert llm_client.parse_json_loose(text) == {"tom_tat": "có {ngoặc} trong chữ"}

    @pytest.mark.parametrize(
        "text",
        ["", "không phải json", "{không đóng", "[1, 2, 3]", "{'a': 1}", "} sai thứ tự {"],
    )
    def test_garbage_returns_none(self, text):
        assert llm_client.parse_json_loose(text) is None


class TestWriteAnalysis:
    def test_returns_parsed_json_with_usage_and_settings(self):
        client, comp = fake_client(_reply(json.dumps(VALID, ensure_ascii=False), total=120))

        out = llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert out == {**VALID, "_usage": 120}
        call = comp.calls[0]
        assert call["model"] == "m-1"
        assert call["temperature"] == 0.25
        assert call["response_format"] == {"type": "json_object"}
        system, user = call["messages"]
        assert system["role"] == "system" and user["role"] == "user"
        for key in ("goc_nhin", "mau_hook_dien_cho_trong", "vi_tri_cta", "goi_y_nhan_ban"):
            assert key in system["content"]
        assert "Không bịa" in system["content"]
        for text in ("Caption gốc", "Thoại gốc của video", "Hook gốc", *LABELS.values()):
            assert text in user["content"]

    def test_bad_json_is_asked_again_once_with_chi_tra_json(self):
        client, comp = fake_client(
            _reply("Xin lỗi, đây là văn xuôi", total=30),
            _reply(json.dumps(VALID, ensure_ascii=False), total=50),
        )

        out = llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert out == {**VALID, "_usage": 80}
        assert len(comp.calls) == 2
        retry_messages = comp.calls[1]["messages"]
        assert retry_messages[-2] == {"role": "assistant", "content": "Xin lỗi, đây là văn xuôi"}
        assert retry_messages[-1]["role"] == "user"
        assert "Chỉ trả JSON" in retry_messages[-1]["content"]

    def test_still_bad_json_after_retry_returns_raw_text(self):
        client, comp = fake_client(_reply("hỏng lần 1", total=5), _reply("hỏng lần 2", total=7))

        out = llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert out == {"_raw": "hỏng lần 2", "_usage": 12}
        assert len(comp.calls) == 2

    def test_response_format_rejected_retries_without_it(self):
        rejected = FakeStatusError("Error code: 400 - response_format is not supported by this endpoint")
        client, comp = fake_client(rejected, _reply(json.dumps(VALID), total=40))

        out = llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert out == {**VALID, "_usage": 40}
        assert comp.calls[0]["response_format"] == {"type": "json_object"}
        assert "response_format" not in comp.calls[1]

    def test_reasoning_effort_is_sent_and_dropped_when_endpoint_rejects_it(self):
        rejected = FakeStatusError("Error code: 400 - Unrecognized request argument: reasoning_effort")
        client, comp = fake_client(rejected, _reply(json.dumps(VALID), total=40))

        out = llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert out == {**VALID, "_usage": 40}
        assert comp.calls[0]["reasoning_effort"] == "low"
        assert "reasoning_effort" not in comp.calls[1]
        assert comp.calls[1]["response_format"] == {"type": "json_object"}

    def test_empty_reasoning_effort_setting_sends_no_parameter(self):
        client, comp = fake_client(_reply(json.dumps(VALID)))
        settings = {**SETTINGS, "llm": {**SETTINGS["llm"], "reasoning_effort": ""}}

        llm_client.write_analysis(client, "m-1", VIDEO, LABELS, settings)

        assert "reasoning_effort" not in comp.calls[0]

    def test_fallback_is_kept_for_the_bad_json_retry(self):
        rejected = FakeStatusError("400 - unsupported response_format")
        client, comp = fake_client(rejected, _reply("không phải json", total=1), _reply(json.dumps(VALID), total=1))

        llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)

        assert len(comp.calls) == 3
        assert "response_format" not in comp.calls[1]
        assert "response_format" not in comp.calls[2]

    def test_other_400_is_not_swallowed(self):
        client, comp = fake_client(FakeStatusError("model không tồn tại"))

        with pytest.raises(FakeStatusError):
            llm_client.write_analysis(client, "m-1", VIDEO, LABELS, SETTINGS)
        assert len(comp.calls) == 1

    def test_missing_transcript_is_marked_for_the_model(self):
        silent = Video(video_id="vid-2", url="u", page_url="p", caption="Chỉ có caption")
        client, comp = fake_client(_reply(json.dumps(VALID)))

        llm_client.write_analysis(client, "m-1", silent, LABELS, SETTINGS)

        user = comp.calls[0]["messages"][1]["content"]
        assert "chỉ dựa vào caption" in user

    def test_post_prompt_is_caption_only_and_requests_new_post_ideas(self):
        post = Video(
            video_id="post-1", url="u", page_url="p", format="post",
            caption="Dòng mở bài\nNội dung caption", transcript="Thoại không được dùng", hook="Hook cũ",
        )
        client, comp = fake_client(_reply(json.dumps(VALID)))

        llm_client.write_analysis(client, "m-1", post, LABELS, SETTINGS)

        assert len(comp.calls) == 1
        system, user = comp.calls[0]["messages"]
        prompt = system["content"] + user["content"]
        assert "bài đăng" in prompt.lower()
        assert "transcript" not in prompt.lower()
        assert "Thoại không được dùng" not in prompt
        assert "Hook cũ" not in prompt
        assert "Hook (dòng đầu caption):\nDòng mở bài" in user["content"]
        assert "vị trí CTA trong bài đăng" in user["content"]
        assert "ý tưởng bài đăng mới" in prompt
        for label in LABELS.values():
            assert label in user["content"]

    def test_post_without_caption_does_not_use_stale_hook_or_transcript(self):
        post = Video(
            video_id="post-empty", url="u", page_url="p", format="post",
            caption="", transcript="Thoại cũ", hook="Hook cũ",
        )
        prompt = llm_client._user_prompt(post, LABELS)
        assert "Hook (dòng đầu caption):\n(không có)" in prompt
        assert "Thoại cũ" not in prompt
        assert "Hook cũ" not in prompt


class TestFilterBanned:
    BAN = ["khỏi hẳn", "cam kết", "100%"]

    def test_drops_matching_suggestions_case_insensitively(self):
        suggestions = [
            {"hook_moi": "Chủ nhà thuốc nào cũng cần biết", "y_tuong": "Giải thích GPP"},
            {"hook_moi": "Uống xong KHỎI HẲN trong 3 ngày", "y_tuong": "Demo"},
            {"hook_moi": "Hỏi dược sĩ", "y_tuong": "Cam Kết hiệu quả"},
            {"hook_moi": "Hiệu quả 100%", "y_tuong": "Không có"},
        ]
        assert llm_client.filter_banned(suggestions, self.BAN) == [suggestions[0]]

    def test_checks_both_fields(self):
        assert llm_client.filter_banned([{"hook_moi": "ok", "y_tuong": "hứa cam kết"}], self.BAN) == []

    def test_does_not_join_fields_into_a_false_match(self):
        suggestion = {"hook_moi": "khỏi", "y_tuong": "hẳn ngay hôm nay"}
        assert llm_client.filter_banned([suggestion], self.BAN) == [suggestion]

    def test_matches_decomposed_unicode(self):
        decomposed = unicodedata.normalize("NFD", "Khỏi hẳn ngay")
        assert llm_client.filter_banned([{"hook_moi": decomposed, "y_tuong": ""}], self.BAN) == []

    def test_blank_ban_words_do_not_ban_everything(self):
        suggestions = [{"hook_moi": "bất kỳ", "y_tuong": "gì"}]
        assert llm_client.filter_banned(suggestions, ["", "   "]) == suggestions

    def test_non_dict_items_are_dropped(self):
        assert llm_client.filter_banned(["chuỗi lạ", {"hook_moi": "ok", "y_tuong": "ok"}], self.BAN) == [
            {"hook_moi": "ok", "y_tuong": "ok"}
        ]


SUMMARY = {
    "by_topic": [
        {"label": "Kiến thức bệnh", "count": 4, "avg_views": 1234.5, "avg_score": 62.0, "caption": "BÍ MẬT CAPTION"},
    ],
    "by_hook": [{"label": "Câu hỏi", "count": 2, "avg_views": 900, "avg_score": 40.5}],
    "by_structure": [{"label": "Liệt kê", "count": 3, "avg_views": None, "avg_score": 80}],
    "commentary": "NHẬN XÉT CŨ",
}


class TestWriteCommentary:
    def test_prompt_contains_only_table_data(self):
        client, comp = fake_client(_reply("  Dòng 1\nDòng 2  ", total=42))

        text, tokens = llm_client.write_commentary(client, "m-1", SUMMARY)

        assert text == "Dòng 1\nDòng 2"
        assert tokens == 42
        call = comp.calls[0]
        assert "response_format" not in call
        system, user = call["messages"]
        assert "5-7" in system["content"]
        assert "BÍ MẬT CAPTION" not in system["content"] + user["content"]
        assert "NHẬN XÉT CŨ" not in system["content"] + user["content"]
        payload = json.loads(user["content"])
        assert set(payload) == {"by_topic", "by_hook", "by_structure"}
        assert payload["by_topic"] == [
            {"label": "Kiến thức bệnh", "count": 4, "avg_views": 1234.5, "avg_score": 62.0}
        ]
        assert payload["by_hook"] == [{"label": "Câu hỏi", "count": 2, "avg_views": 900, "avg_score": 40.5}]
        assert payload["by_structure"] == SUMMARY["by_structure"]

    def test_commentary_wording_is_neutral_and_does_not_invent_missing_views(self):
        prompt = llm_client.COMMENTARY_SYSTEM_PROMPT
        assert "số nội dung" in prompt
        assert "số video" not in prompt
        assert "thiếu/null không có nghĩa là 0" in prompt

    def test_no_rows_means_no_call(self):
        client, comp = fake_client()
        assert llm_client.write_commentary(client, "m-1", {"by_topic": [], "by_hook": []}) == ("", 0)
        assert comp.calls == []


class TestCheckKey:
    @staticmethod
    def _client(model_ids=None, models_error=None, *outcomes):
        from openai.types import Model

        client, comp = fake_client(*outcomes)

        def list_models():
            if models_error is not None:
                raise models_error
            return SimpleNamespace(data=[
                Model.model_validate({"id": i, "object": "model", "created": 0, "owned_by": "x"})
                for i in model_ids or []
            ])

        client.models = SimpleNamespace(list=list_models)
        return client, comp

    def test_listed_model_requires_one_token_completion(self, monkeypatch):
        client, comp = self._client(["m-0", "m-1"], None, _reply("pong"))
        seen = {}

        def fake_make_client(base_url, api_key):
            seen["args"] = (base_url, api_key)
            return client

        monkeypatch.setattr(llm_client, "make_client", fake_make_client)

        assert llm_client.check_key("https://llm.test/v1", "sk-test", "m-1") is None
        assert seen["args"] == ("https://llm.test/v1", "sk-test")
        assert len(comp.calls) == 1
        assert comp.calls[0]["max_tokens"] == 1
        assert comp.calls[0]["reasoning_effort"] == "low"

    def test_no_models_endpoint_pings_with_one_token(self, monkeypatch):
        client, comp = self._client([], FakeStatusError("no /models", status_code=404), _reply("pong"))
        monkeypatch.setattr(llm_client, "make_client", lambda base_url, api_key: client)

        assert llm_client.check_key("https://llm.test/v1", "sk-test", "m-1") is None
        call = comp.calls[0]
        assert call["max_tokens"] == 1
        assert call["model"] == "m-1"
        assert call["messages"] == [{"role": "user", "content": "ping"}]

    def test_invalid_key_on_models_list_raises_auth_error_without_ping(self, monkeypatch):
        client, comp = self._client(models_error=FakeStatusError("invalid key", status_code=401))
        monkeypatch.setattr(llm_client, "make_client", lambda base_url, api_key: client)

        with pytest.raises(AuthError):
            llm_client.check_key("https://llm.test/v1", "sk-bad", "m-1")
        assert comp.calls == []

    def test_invalid_key_on_ping_raises_auth_error(self, monkeypatch):
        client, _ = self._client(["m-1"], None, FakeStatusError("invalid key", status_code=401))
        monkeypatch.setattr(llm_client, "make_client", lambda base_url, api_key: client)

        with pytest.raises(AuthError):
            llm_client.check_key("https://llm.test/v1", "sk-bad", "m-1")

    def test_unlisted_model_fails_without_completion(self, monkeypatch):
        from errors import ServiceError
        client, comp = self._client(["other"])
        monkeypatch.setattr(llm_client, "make_client", lambda *args: client)
        with pytest.raises(ServiceError, match="không có"):
            llm_client.check_key("https://llm.test/v1", "sk-test", "m-1")
        assert not comp.calls

    def test_token_cap_and_reasoning_fallbacks_keep_one_token_limit(self, monkeypatch):
        client, comp = self._client(
            ["m-1"], None,
            FakeStatusError("unsupported max_tokens; use max_completion_tokens"),
            FakeStatusError("unsupported reasoning_effort"),
            _reply("pong"),
        )
        monkeypatch.setattr(llm_client, "make_client", lambda *args: client)
        llm_client.check_key("https://llm.test/v1", "sk-test", "m-1")
        assert len(comp.calls) == 3
        assert comp.calls[-1]["max_completion_tokens"] == 1
        assert "max_tokens" not in comp.calls[-1]
        assert "reasoning_effort" not in comp.calls[-1]


def test_make_client_disables_sdk_retries(monkeypatch):
    seen: dict = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(llm_client, "OpenAI", RecordingOpenAI)

    llm_client.make_client("https://llm.test/v1", "sk-test")

    assert seen["base_url"] == "https://llm.test/v1"
    assert seen["api_key"] == "sk-test"
    assert seen["max_retries"] == 0


def test_list_models_sorts_and_converts_per_token_price_to_per_million(monkeypatch):
    from openai.types import Model

    def model(mid, **extra):
        return Model.model_validate({"id": mid, "object": "model", "created": 0, "owned_by": "x", **extra})

    data = [
        model("z-model", pricing={"prompt": "0.0000008", "completion": "0.0000016"}, context_length=131072),
        model("a-model"),  # endpoint không công bố giá
        model("bad-price", pricing={"prompt": "-1", "completion": "abc"}),
    ]
    client = SimpleNamespace(models=SimpleNamespace(list=lambda: SimpleNamespace(data=data)))
    monkeypatch.setattr(llm_client, "make_client", lambda base_url, api_key: client)

    models = llm_client.list_models("https://llm.test/v1", "sk")

    assert [m["id"] for m in models] == ["a-model", "bad-price", "z-model"]
    assert models[0]["price_in"] is None and models[0]["context_length"] is None
    assert models[1]["price_in"] is None and models[1]["price_out"] is None
    assert models[2] == {"id": "z-model", "owned_by": "x", "context_length": 131072,
                         "price_in": 0.8, "price_out": 1.6}


def test_shipped_ban_list_has_plan_words():
    words = load_lines("config/ban_words.txt")
    for word in ("khỏi hẳn", "100%", "tốt nhất", "cam kết", "đặc trị"):
        assert word in words


def test_shipped_keyterms_has_gpp_and_thong_tu():
    terms = load_lines("config/keyterms.txt")
    assert "GPP" in terms
    assert "thông tư" in terms
