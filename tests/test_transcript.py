"""Offline tests for collectors/transcript.py. Mọi HTTP, ffmpeg và DB đều được giả lập."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import requests

from backend.collectors import transcript
from backend.core.errors import AuthError, QuotaError, ServiceError
from backend.core.models import Video

_REAL_TRANSCRIBE_DEEPGRAM = transcript.transcribe_deepgram

STT = {
    "provider": "deepgram",
    "model": "nova-3",
    "language": "vi",
    "keyterms_file": "config/keyterms.txt",
}

DG_PAYLOAD = {
    "metadata": {"duration": 61.5, "language": "vi"},
    "results": {"channels": [{"alternatives": [{
        "transcript": "Chủ nhà thuốc cần biết điều này.",
        "words": [
            {"word": "chu", "punctuated_word": "Chủ", "start": 0.1, "end": 0.4},
            {"word": "nha", "punctuated_word": "nhà", "start": 0.4, "end": 0.7},
            {"word": "", "punctuated_word": " ", "start": 0.7, "end": 0.7},
            {"word": "thuoc", "punctuated_word": "thuốc", "start": 0.7, "end": 1.1},
        ],
    }]}]},
}

TIMED_WORDS = [
    {"punctuated_word": "Chủ", "start": 0.2, "end": 0.5},
    {"punctuated_word": "nhà", "start": 0.8, "end": 1.1},
    {"punctuated_word": "thuốc", "start": 1.4, "end": 1.8},
    {"punctuated_word": "cần", "start": 2.2, "end": 2.6},
    {"punctuated_word": "biết", "start": 2.8, "end": 3.2},
    {"punctuated_word": "điều", "start": 3.3, "end": 3.6},
    {"punctuated_word": "này.", "start": 3.9, "end": 4.2},
]
TIMED_HOOK = "Chủ nhà thuốc cần biết điều này."

AUTH_MSG = "API key [deepgram] không hợp lệ. Vào Cài đặt để nhập lại."
QUOTA_MSG = "Tài khoản Deepgram đã hết credit/hạn mức."


def w(token: str, start: float) -> dict:
    return {"punctuated_word": token, "start": start, "end": start + 0.3}


class FakeResponse:
    """Tối thiểu giống requests.Response: status_code, json(), raise_for_status() như thật."""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


def _video(**overrides: Any) -> Video:
    base: dict[str, Any] = {
        "video_id": "vid1",
        "url": "https://www.facebook.com/reel/1",
        "page_url": "https://www.facebook.com/page",
        "caption": "Cảnh báo sai lầm khi bán thuốc\nDòng hai",
    }
    base.update(overrides)
    return Video(**base)


# --- hook_3s ---------------------------------------------------------------

def test_hook_stops_before_3s_then_extends_to_sentence_end():
    words = [
        w("Chủ", 0.5), w("nhà", 1.5), w("thuốc", 2.9),   # trong 3 giây đầu, chưa hết câu
        w("cần", 3.2), w("biết", 3.8), w("điều.", 4.5),  # nối thêm tới dấu kết câu
        w("Này", 5.0),                                   # câu sau, không được lấy
    ]
    assert transcript.hook_3s(words) == "Chủ nhà thuốc cần biết điều."


def test_hook_does_not_extend_when_window_already_ends_sentence():
    words = [w("Sai", 0.0), w("lầm.", 1.0), w("Tiếp", 3.5)]
    assert transcript.hook_3s(words) == "Sai lầm."


def test_word_starting_exactly_at_3s_is_outside_the_window():
    words = [w("Một", 0.0), w("hai.", 2.0), w("Ba", 3.0)]
    assert transcript.hook_3s(words) == "Một hai."


def test_hook_takes_whole_transcript_when_it_ends_without_sentence_end():
    words = [w("Chỉ", 0.5), w("một", 1.0), w("câu", 2.0)]
    assert transcript.hook_3s(words) == "Chỉ một câu"


def test_hook_extension_is_capped_when_no_sentence_end_appears():
    words = [w("a", 0.5), w("b", 1.0)] + [w(f"t{i}", 3.5 + i * 0.1) for i in range(100)]
    hook = transcript.hook_3s(words)
    assert hook.split() == ["a", "b"] + [f"t{i}" for i in range(transcript.HOOK_MAX_EXTRA_WORDS)]


def test_hook_empty_words_returns_empty_string():
    assert transcript.hook_3s([]) == ""


def test_hook_returns_empty_when_no_word_starts_in_first_3s():
    assert transcript.hook_3s([w("Xin", 3.5), w("chào.", 4.0)]) == ""


# --- first_lines_hook -------------------------------------------------------

def test_first_lines_hook_uses_first_caption_line_cut_to_200_chars():
    caption = "x" * 250 + "\nDòng hai"
    assert transcript.first_lines_hook(caption, "lời thoại") == "x" * 200 + "\nlời thoại"


def test_first_lines_hook_strips_blank_leading_space_and_keeps_first_line_only():
    assert transcript.first_lines_hook("   Dòng một   \nDòng hai", "") == "Dòng một"


def test_first_lines_hook_falls_back_to_first_30_transcript_words_without_caption():
    text = " ".join(f"t{i}" for i in range(40))
    assert transcript.first_lines_hook("", text) == " ".join(f"t{i}" for i in range(30))


def test_first_lines_hook_combines_caption_and_30_transcript_words():
    text = " ".join(f"t{i}" for i in range(40))
    assert transcript.first_lines_hook("Dòng một\nDòng hai", text) == (
        "Dòng một\n" + " ".join(f"t{i}" for i in range(30))
    )


def test_first_lines_hook_empty_inputs_return_empty_string():
    assert transcript.first_lines_hook("", "") == ""
    assert transcript.first_lines_hook("   \n  ", "") == ""


# --- transcribe_deepgram ----------------------------------------------------

def test_transcribe_deepgram_sends_params_keyterms_and_headers_then_parses(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3fake-audio")
    sent: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        sent["url"] = url
        sent["kwargs"] = kwargs
        sent["body"] = kwargs["data"].read()
        return FakeResponse(200, DG_PAYLOAD)

    monkeypatch.setattr(transcript.requests, "post", fake_post)
    result = transcript.transcribe_deepgram(audio, "secret-key", STT, ["Thông tư 02", "GPP"])

    assert sent["url"] == "https://api.deepgram.com/v1/listen"
    assert sent["kwargs"]["params"] == [
        ("model", "nova-3"),
        ("detect_language", "vi"),
        ("detect_language", "en"),
        ("smart_format", "true"),
        ("keyterm", "Thông tư 02"),
        ("keyterm", "GPP"),
    ]
    assert sent["kwargs"]["headers"] == {
        "Authorization": "Token secret-key",
        "Content-Type": "audio/mpeg",
    }
    assert sent["kwargs"]["timeout"] == transcript.DEEPGRAM_TIMEOUT_S
    assert sent["body"] == b"ID3fake-audio"

    assert result["text"] == "Chủ nhà thuốc cần biết điều này."
    assert result["duration"] == pytest.approx(61.5)
    assert result["words"] == [
        {"punctuated_word": "Chủ", "start": 0.1, "end": 0.4},
        {"punctuated_word": "nhà", "start": 0.4, "end": 0.7},
        {"punctuated_word": "thuốc", "start": 0.7, "end": 1.1},
    ]
    assert result["language"] == ""
    assert result["language_confidence"] is None


def test_transcribe_deepgram_fixed_language_and_detected_language(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")
    sent = []
    payload = {"metadata": {"duration": 1}, "results": {"channels": [{
        "detected_language": "en", "language_confidence": 0.9,
        "alternatives": [{"transcript": "Hello", "words": []}],
    }]}}
    monkeypatch.setattr(transcript.requests, "post",
                        lambda url, **kwargs: (sent.append(kwargs["params"]) or FakeResponse(200, payload)))
    result = transcript.transcribe_deepgram(audio, "k", STT, [])
    assert result["language"] == "en"
    assert result["language_confidence"] == 0.9
    monkeypatch.setattr(transcript.requests, "post",
                        lambda url, **kwargs: (sent.append(kwargs["params"]) or FakeResponse(200, DG_PAYLOAD)))
    result = transcript.transcribe_deepgram(audio, "k", {**STT, "auto_language": False, "language": "en"}, [])
    assert ("language", "en") in sent[-1]
    assert not any(key == "detect_language" for key, _ in sent[-1])
    assert result["language"] == "en"
    assert result["language_confidence"] is None


def test_transcribe_deepgram_silent_audio_has_no_language_and_no_retry(tmp_path, monkeypatch):
    # Deepgram still "detects" a language (confidence ~0) on audio without speech: it must not
    # be labelled English nor trigger the paid low-confidence retry.
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")
    calls = []
    payload = {"metadata": {"duration": 60}, "results": {"channels": [{
        "detected_language": "en", "language_confidence": 0.0,
        "alternatives": [{"transcript": "", "words": []}],
    }]}}
    monkeypatch.setattr(transcript.requests, "post",
                        lambda url, **kwargs: (calls.append(kwargs["params"]) or FakeResponse(200, payload)))
    result, minutes = transcript._transcribe(audio, "k", STT, [], [])
    assert result["language"] == "" and result["language_confidence"] is None
    assert len(calls) == 1 and minutes == 1.0


def test_transcribe_deepgram_401_raises_auth_error_without_retrying(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    calls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(url)
        return FakeResponse(401, {"err_msg": "INVALID_AUTH"})

    monkeypatch.setattr(transcript.requests, "post", fake_post)
    with pytest.raises(AuthError) as info:
        transcript.transcribe_deepgram(audio, "bad-key", STT, [])
    assert info.value.service == "deepgram"
    assert len(calls) == 1


def test_transcribe_deepgram_malformed_response_raises_service_error(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    monkeypatch.setattr(transcript.requests, "post",
                        lambda url, **kwargs: FakeResponse(200, {"results": {"channels": []}}))
    with pytest.raises(ServiceError) as info:
        transcript.transcribe_deepgram(audio, "k", STT, [])
    assert info.value.service == "deepgram"


# --- check_key --------------------------------------------------------------

def test_check_key_posts_bundled_sample_and_accepts_success(monkeypatch):
    monkeypatch.setattr(transcript.config, "load_settings", lambda: {"stt": STT})
    sent: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        sent["body"] = kwargs["data"].read()
        return FakeResponse(200, {"results": {"channels": [{"alternatives": [
            {"transcript": "", "words": []}]}]}, "metadata": {"duration": 1.0}})

    monkeypatch.setattr(transcript.requests, "post", fake_post)
    assert transcript.check_key("good-key") is None
    assert sent["body"] == transcript.SAMPLE_PATH.read_bytes()


def test_check_key_raises_auth_error_on_401(monkeypatch):
    monkeypatch.setattr(transcript.config, "load_settings", lambda: {"stt": STT})
    monkeypatch.setattr(transcript.requests, "post", lambda url, **kwargs: FakeResponse(401))
    with pytest.raises(AuthError):
        transcript.check_key("bad-key")


def test_check_key_uses_given_stt_model_and_language(monkeypatch):
    sent: dict[str, Any] = {}

    def fake_post(url, params, **kwargs):
        sent["params"] = dict(params)
        return FakeResponse(200, {"results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]},
                                  "metadata": {"duration": 1.0}})

    monkeypatch.setattr(transcript.requests, "post", fake_post)
    transcript.check_key("good-key", {**STT, "model": "nova-2-general", "language": "en", "auto_language": False})
    assert sent["params"]["model"] == "nova-2-general"
    assert sent["params"]["language"] == "en"


def test_list_deepgram_models_keeps_batch_merges_languages_and_labels(monkeypatch):
    payload = {
        "stt": [
            {"canonical_name": "nova-3-general", "architecture": "nova-3", "languages": ["vi", "en"], "batch": True},
            {"canonical_name": "nova-3-general", "architecture": "nova-3", "languages": ["en", "fr"], "batch": True},
            {"canonical_name": "live-only", "architecture": "x", "languages": ["vi"], "batch": False},
            {"canonical_name": "base-general", "architecture": "base", "languages": ["en"], "batch": True},
        ],
        "languages": {"vi": "Vietnamese", "en": "English"},
    }
    urls: list[str] = []

    def fake_get(url, headers, **kwargs):
        urls.append(url)
        assert headers["Authorization"] == "Token key-1"
        return FakeResponse(200, payload if url.endswith("/models") else {"projects": []})

    monkeypatch.setattr(transcript.requests, "get", fake_get)
    models = transcript.list_deepgram_models("key-1")

    assert urls[0] == transcript.DEEPGRAM_PROJECTS_URL  # key verified before listing
    assert [m["name"] for m in models] == ["base-general", "nova-3-general"]
    assert models[1]["languages"] == [
        {"code": "en", "label": "English"}, {"code": "fr", "label": "fr"}, {"code": "vi", "label": "Vietnamese"},
    ]


def test_list_deepgram_models_bad_key_raises_auth_error(monkeypatch):
    monkeypatch.setattr(transcript.requests, "get", lambda url, **kwargs: FakeResponse(401))
    with pytest.raises(AuthError):
        transcript.list_deepgram_models("bad")

# --- extract_audio ----------------------------------------------------------

def test_extract_audio_uses_contract_ffmpeg_flags(tmp_path, monkeypatch):
    src = tmp_path / "raw.mp4"
    src.write_bytes(b"raw")
    dst = tmp_path / "out" / "a.mp3"
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"ID3")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(transcript, "_ffmpeg_exe", lambda: "C:/tools/ffmpeg.exe")
    monkeypatch.setattr(transcript.subprocess, "run", fake_run)

    assert transcript.extract_audio(src, dst) == dst
    cmd = seen["cmd"]
    assert cmd[0] == "C:/tools/ffmpeg.exe"
    assert cmd[cmd.index("-i") + 1] == str(src.resolve())
    vn = cmd.index("-vn")
    assert cmd[vn:vn + 9] == ["-vn", "-acodec", "libmp3lame", "-ar", "16000",
                              "-ac", "1", "-b:a", "64k"]
    # Livestream nhiều giờ: chỉ gửi 10 phút đầu cho Deepgram.
    assert cmd[cmd.index("-t") + 1] == "600"
    assert cmd.index("-t") > cmd.index("-i")  # tùy chọn đầu ra, không phải đầu vào


def test_extract_audio_seeks_to_start_before_reading_input(tmp_path, monkeypatch):
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"ID3")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(transcript, "_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(transcript.subprocess, "run", fake_run)

    transcript.extract_audio(tmp_path / "raw.m4a", tmp_path / "a.mp3", start_s=600)
    cmd = seen["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "600"
    assert cmd.index("-ss") < cmd.index("-i")  # tua đầu vào: không giải mã 10 phút đầu
    assert cmd[cmd.index("-t") + 1] == "600"


def test_extract_audio_returns_none_when_output_is_empty(tmp_path, monkeypatch):
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        Path(cmd[-1]).write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(transcript, "_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(transcript.subprocess, "run", fake_run)
    assert transcript.extract_audio(tmp_path / "raw.mp4", tmp_path / "a.mp3") is None


def test_extract_audio_returns_none_on_ffmpeg_error(tmp_path, monkeypatch):
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 1, "", "Invalid data found")

    monkeypatch.setattr(transcript, "_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(transcript.subprocess, "run", fake_run)
    assert transcript.extract_audio(tmp_path / "raw.mp4", tmp_path / "a.mp3") is None


# --- get_transcript ---------------------------------------------------------

class Env:
    """Ghi lại các lời gọi của các phụ thuộc đã được giả lập trong get_transcript."""

    def __init__(self) -> None:
        self.cached: tuple[str, str] | None = None
        self.stored: Video | None = None
        self.saved: list[tuple[str, str, str, str]] = []
        self.saved_languages: list[str] = []
        self.download_ok = True
        self.extract_ok = True
        self.downloads = 0
        self.download_requests: list[int | None] = []  # first_seconds của từng lần tải
        self.raw_path: Path | None = None
        self.audio_path: Path | None = None
        self.extract_starts: list[int] = []  # start_s của từng lần tách audio
        self.dg_calls: list[tuple[Path, str, dict, list[str]]] = []
        self.deepgram: Any = None


@pytest.fixture
def env(monkeypatch) -> Env:
    e = Env()

    def fake_download(url: str, out_dir: Path, first_seconds: int | None = None,
                      ffmpeg: str | None = None) -> Path | None:
        e.downloads += 1
        e.download_requests.append(first_seconds)
        if not e.download_ok:
            return None
        e.raw_path = Path(out_dir) / "raw.m4a"
        e.raw_path.write_bytes(b"raw")
        return e.raw_path

    def fake_extract(src: Path, dst: Path, start_s: int = 0) -> Path | None:
        e.extract_starts.append(start_s)
        if not e.extract_ok:
            return None
        e.audio_path = Path(dst)
        e.audio_path.write_bytes(b"ID3")
        return e.audio_path

    def fake_deepgram(path: Path, api_key: str, stt: dict, keyterms: list[str]) -> Any:
        e.dg_calls.append((Path(path), api_key, dict(stt), list(keyterms)))
        if isinstance(e.deepgram, BaseException):
            raise e.deepgram
        return e.deepgram

    monkeypatch.setattr(transcript.db, "get_transcript", lambda video_id: e.cached)
    monkeypatch.setattr(transcript.db, "get_video", lambda video_id: e.stored)
    def fake_save(video_id, text, status, hook, transcript_language=""):
        e.saved.append((video_id, text, status, hook))
        e.saved_languages.append(transcript_language)

    monkeypatch.setattr(transcript.db, "save_transcript", fake_save)
    monkeypatch.setattr(transcript, "download_audio", fake_download)
    monkeypatch.setattr(transcript, "extract_audio", fake_extract)
    monkeypatch.setattr(transcript, "transcribe_deepgram", fake_deepgram)
    return e


def test_deepgram_success_saves_ok_bills_minutes_and_removes_temp_audio(env, tmp_path):
    env.deepgram = {"text": TIMED_HOOK, "duration": 90.0, "words": TIMED_WORDS}
    video = _video()

    minutes = transcript.get_transcript(video, "dg-key", STT, ["GPP"], tmp_path / "tmp")

    assert minutes == pytest.approx(1.5)
    assert env.dg_calls == [(env.audio_path, "dg-key", STT, ["GPP"])]
    assert video.transcript == TIMED_HOOK
    assert video.transcript_status == "ok"
    assert video.hook == TIMED_HOOK
    assert video.notes == []
    assert env.saved == [("vid1", TIMED_HOOK, "ok", TIMED_HOOK)]
    assert not env.audio_path.exists()
    assert not env.raw_path.exists()


def test_quota_error_warns_marks_failed_and_retries_instead_of_using_cache(env, tmp_path):
    env.deepgram = QuotaError("deepgram", QUOTA_MSG)
    video = _video()
    warnings = []

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp", warnings)

    assert warnings == [QUOTA_MSG + " Nạp thêm hoặc đổi key Deepgram trong Cài đặt rồi quét lại."]
    assert minutes == 0.0
    assert video.transcript == ""
    assert video.transcript_status == "failed"
    assert video.notes == ["Chưa lấy được thoại"]
    expected_hook = "Cảnh báo sai lầm khi bán thuốc"
    assert video.hook == expected_hook
    assert env.saved == [("vid1", "", "failed", expected_hook)]
    assert not env.audio_path.exists()
    assert not env.raw_path.exists()

    env.cached = ("", "failed")
    env.deepgram = {"text": TIMED_HOOK, "duration": 60.0, "words": TIMED_WORDS}
    retried = _video()
    assert transcript.get_transcript(retried, "dg-key", STT, [], tmp_path / "tmp") == 1.0
    assert env.downloads == 2
    assert retried.transcript_status == "ok"
    assert retried.transcript == TIMED_HOOK


def test_empty_transcript_is_no_speech_and_still_bills_deepgram_minutes(env, tmp_path):
    env.deepgram = {"text": "", "duration": 12.0, "words": []}
    video = _video()

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert minutes == pytest.approx(0.2)
    assert video.transcript == ""
    assert video.transcript_status == "no_speech"
    assert video.notes == ["Không có thoại"]
    expected_hook = "Cảnh báo sai lầm khi bán thuốc"
    assert video.hook == expected_hook
    assert env.saved == [("vid1", "", "no_speech", expected_hook)]


def test_download_failure_marks_failed_and_skips_deepgram(env, tmp_path):
    env.download_ok = False
    video = _video()

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert minutes == 0.0
    assert env.dg_calls == []
    assert video.transcript_status == "failed"
    assert video.notes == ["Chưa lấy được thoại"]


@pytest.mark.parametrize("duration, requested", [
    (transcript.MAX_AUDIO_SECONDS + 1, transcript.SPEECH_SEARCH_SECONDS),  # livestream: chỉ tải đoạn đầu
    (transcript.MAX_AUDIO_SECONDS, None),
    (None, None),  # chưa biết thời lượng: tải cả audio
])
def test_only_long_videos_download_just_the_searched_part(env, tmp_path, monkeypatch, duration, requested):
    monkeypatch.setattr(transcript, "_ffmpeg_exe", lambda: "ffmpeg")
    env.deepgram = {"text": TIMED_HOOK, "duration": 60.0, "words": TIMED_WORDS}

    transcript.get_transcript(_video(duration_s=duration), "dg-key", STT, [], tmp_path / "tmp")

    assert env.download_requests == [requested]


def test_long_video_with_music_intro_transcribes_the_first_window_with_speech(env, tmp_path, monkeypatch):
    # Livestream thật: 15 phút nhạc chờ rồi mới chào khán giả.
    windows = iter([{"text": "", "duration": 600.0, "words": []},
                    {"text": TIMED_HOOK, "duration": 600.0, "words": TIMED_WORDS}])
    monkeypatch.setattr(transcript, "transcribe_deepgram", lambda *args: next(windows))
    video = _video(duration_s=3445)

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert env.extract_starts == [0, 600]
    assert minutes == pytest.approx(20.0)  # cả hai đoạn đều tính phí Deepgram
    assert video.transcript_status == "ok" and video.transcript == TIMED_HOOK
    assert video.notes == ["Video dài 57 phút: chỉ chép lời 10 phút từ phút 10."]


def test_long_video_without_speech_stops_after_the_searched_minutes(env, tmp_path):
    env.deepgram = {"text": "", "duration": 600.0, "words": []}
    video = _video(duration_s=3 * 3600)

    transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert env.extract_starts == [0, 600, 1200]
    assert video.transcript_status == "no_speech"
    assert video.notes == ["Video dài 180 phút: không thấy thoại trong 30 phút đầu.", "Không có thoại"]


def test_cached_ok_transcript_skips_download_and_reuses_stored_hook(env, tmp_path):
    env.cached = ("Chủ nhà thuốc.", "ok")
    env.stored = Video(video_id="vid1", url="", page_url="", hook="Hook đã lưu", transcript_language="en")
    video = _video()

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert minutes == 0.0
    assert env.downloads == 0
    assert env.dg_calls == []
    assert env.saved == []
    assert video.transcript == "Chủ nhà thuốc."
    assert video.transcript_status == "ok"
    assert video.hook == "Hook đã lưu"
    assert video.transcript_language == "en"


def test_cached_no_speech_adds_note_and_falls_back_to_caption_hook(env, tmp_path):
    env.cached = ("", "no_speech")
    video = _video()

    transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert env.downloads == 0
    assert video.transcript_status == "no_speech"
    assert video.notes == ["Không có thoại"]
    assert video.hook == "Cảnh báo sai lầm khi bán thuốc"


def test_cached_failed_transcript_is_retried(env, tmp_path):
    env.cached = ("", "failed")
    env.deepgram = {"text": "Chủ nhà.", "duration": 6.0, "words": []}
    video = _video()

    minutes = transcript.get_transcript(video, "dg-key", STT, [], tmp_path / "tmp")

    assert env.downloads == 1
    assert minutes == pytest.approx(0.1)
    assert video.transcript_status == "ok"
    assert env.saved[0][2] == "ok"


def test_auth_error_propagates_and_cleans_files(env, tmp_path):
    error = AuthError("deepgram", AUTH_MSG)
    env.deepgram = error
    warnings = []
    with pytest.raises(AuthError) as caught:
        transcript.get_transcript(_video(), "dg-key", STT, [], tmp_path / "tmp", warnings)
    assert caught.value is error
    assert env.saved == []
    assert warnings == []
    assert not env.audio_path.exists()
    assert not env.raw_path.exists()


def test_low_language_confidence_retries_once_in_vi_and_bills_both_calls(env, tmp_path, monkeypatch):
    results = iter([
        {"text": "Uncertain", "duration": 60.0, "words": [], "language": "en", "language_confidence": 0.49},
        {"text": TIMED_HOOK, "duration": 60.0, "words": TIMED_WORDS, "language": "vi", "language_confidence": 0.1},
    ])
    calls = []

    def fake_deepgram(audio, key, stt, keyterms):
        calls.append((audio, dict(stt)))
        return next(results)

    monkeypatch.setattr(transcript, "transcribe_deepgram", fake_deepgram)
    usage = []
    video = _video()
    with transcript.observe_usage(usage.append):
        minutes = transcript.get_transcript(video, "k", STT, [], tmp_path)
    assert minutes == 2.0
    assert usage == [1.0, 1.0]
    assert len(calls) == 2 and calls[0][0] == calls[1][0]
    assert calls[1][1]["auto_language"] is False
    assert calls[1][1]["language"] == "vi"
    assert video.transcript == TIMED_HOOK
    assert video.transcript_language == "vi"
    assert video.notes == [transcript.NOTE_LANGUAGE_UNCERTAIN]
    assert env.saved_languages == ["vi"]


@pytest.mark.parametrize("auto, confidence", [(True, None), (True, 0.5), (False, 0.1)])
def test_language_detection_does_not_retry_when_confident_unknown_or_disabled(env, tmp_path, auto, confidence):
    env.deepgram = {"text": "Hello", "duration": 60.0, "words": [],
                    "language": "en", "language_confidence": confidence}
    video = _video()
    minutes = transcript.get_transcript(video, "k", {**STT, "auto_language": auto}, [], tmp_path)
    assert minutes == 1.0
    assert len(env.dg_calls) == 1
    assert video.transcript_language == "en"
    assert env.saved_languages == ["en"]
    assert video.notes == []


def test_transcript_language_database_roundtrip_migration_and_cache_restore(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with transcript.db.conn(path) as connection:
        connection.executescript(transcript.db.SCHEMA
                                 .replace("    transcript_language TEXT,\n", "")
                                 .replace("    transcript_vi     TEXT,\n", ""))
        connection.execute("INSERT INTO videos (video_id, transcript, transcript_status, hook) "
                           "VALUES ('vid1', 'Hello', 'ok', 'Hello')")
    transcript.db.init_db(path)
    transcript.db.init_db(path)
    assert transcript.db.get_video("vid1", path).transcript_language == ""
    assert transcript.db.get_video("vid1", path).transcript_vi == ""
    transcript.db.save_transcript("vid1", "Hello", "ok", "Hello", path,
                                  transcript_language="en", transcript_vi="Xin chào")
    transcript.db.upsert_video(_video(), path)
    transcript.db.save_transcript("vid1", "", "", "", path)
    assert transcript.db.get_video("vid1", path).transcript_language == "en"
    assert transcript.db.get_video("vid1", path).transcript_vi == "Xin chào"
    monkeypatch.setattr(transcript.config, "DB_PATH", path)
    monkeypatch.setattr(transcript, "download_audio", lambda *args: pytest.fail("cache must skip audio"))
    video = _video()
    assert transcript.get_transcript(video, "k", STT, [], tmp_path) == 0.0
    assert video.transcript == "Hello"
    assert video.transcript_language == "en"
    assert video.transcript_vi == "Xin chào"
    transcript.db.upsert_video(_video(video_id="other", transcript_language="en", transcript_vi="Bản dịch"), path)
    assert transcript.db.get_video("other", path).transcript_language == "en"
    assert transcript.db.get_video("other", path).transcript_vi == "Bản dịch"


def test_low_confidence_retry_quota_keeps_first_call_billing(env, tmp_path, monkeypatch):
    calls = []

    def fake_deepgram(audio, key, stt, keyterms):
        calls.append(dict(stt))
        if len(calls) == 2:
            raise QuotaError("deepgram", QUOTA_MSG)
        return {"text": "Uncertain", "duration": 60.0, "words": [],
                "language": "en", "language_confidence": 0.1}

    monkeypatch.setattr(transcript, "transcribe_deepgram", fake_deepgram)
    usage = []
    video = _video()
    with transcript.observe_usage(usage.append):
        minutes = transcript.get_transcript(video, "k", STT, [], tmp_path)
    assert minutes == 1.0
    assert usage == [1.0, 0.0]
    assert video.transcript == ""
    assert video.transcript_status == "failed"
    assert env.saved[0][2] == "failed"


@pytest.mark.parametrize("duration,extension,direct", [
    (30, ".m4a", True), (600, ".MP4", True), (10, ".webm", True),
    (10, ".opus", True), (10, ".ogg", True), (10, ".mp3", True),
    (None, ".m4a", False), (0, ".m4a", False), (601, ".m4a", False),
    (30, ".wav", False),
])
def test_original_audio_decision_and_ffmpeg_path(env, tmp_path, monkeypatch, duration, extension, direct):
    raw = tmp_path / ("raw" + extension)
    raw.write_bytes(b"raw")
    monkeypatch.setattr(transcript, "download_audio", lambda *args, **kwargs: raw)
    env.deepgram = {"text": TIMED_HOOK, "duration": 30.0, "words": TIMED_WORDS}
    assert transcript.get_transcript(_video(duration_s=duration), "k", STT, [], tmp_path) == 0.5
    assert env.extract_starts == ([] if direct else [0])
    assert env.dg_calls[0][0] == (raw if direct else env.audio_path)
    assert not raw.exists()


def test_large_original_audio_keeps_ffmpeg_path(env, tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "MAX_DIRECT_AUDIO_BYTES", 3)
    env.deepgram = {"text": TIMED_HOOK, "duration": 30.0, "words": TIMED_WORDS}
    transcript.get_transcript(_video(duration_s=30), "k", STT, [], tmp_path)
    assert env.extract_starts == [0]


@pytest.mark.parametrize("extension,content_type", [
    (".m4a", "audio/mp4"), (".mp4", "audio/mp4"), (".webm", "audio/webm"),
    (".opus", "audio/ogg"), (".ogg", "audio/ogg"), (".mp3", "audio/mpeg"),
])
def test_deepgram_original_content_type(tmp_path, monkeypatch, extension, content_type):
    audio = tmp_path / ("audio" + extension)
    audio.write_bytes(b"audio")
    def post(url, **kwargs):
        assert kwargs["headers"]["Content-Type"] == content_type
        assert kwargs["data"].read() == b"audio"
        return FakeResponse(200, DG_PAYLOAD)
    monkeypatch.setattr(transcript.requests, "post", post)
    assert transcript.transcribe_deepgram(audio, "k", STT, [])["text"]


def test_original_400_retries_once_through_ffmpeg(env, tmp_path, monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((kwargs["headers"]["Content-Type"], kwargs["data"].read()))
        return FakeResponse(400) if len(calls) == 1 else FakeResponse(200, DG_PAYLOAD)
    monkeypatch.setattr(transcript, "transcribe_deepgram", _REAL_TRANSCRIBE_DEEPGRAM)
    monkeypatch.setattr(transcript.requests, "post", post)
    usage = []
    timings = {}
    with transcript.observe_usage(usage.append), transcript.observe_timing(
            lambda stage, seconds: timings.__setitem__(stage, timings.get(stage, 0) + seconds)):
        minutes = transcript.get_transcript(_video(duration_s=30), "k", STT, [], tmp_path)
    assert calls == [("audio/mp4", b"raw"), ("audio/mpeg", b"ID3")]
    assert env.extract_starts == [0]
    assert minutes == 61.5 / 60
    assert usage == [0.0, 61.5 / 60]
    assert set(timings) == {"tải audio", "ffmpeg", "Deepgram"}
    assert not env.raw_path.exists() and not env.audio_path.exists()


def test_original_400_fallback_does_not_retry_a_second_400(env, tmp_path, monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["headers"]["Content-Type"])
        return FakeResponse(400)
    monkeypatch.setattr(transcript, "transcribe_deepgram", _REAL_TRANSCRIBE_DEEPGRAM)
    monkeypatch.setattr(transcript.requests, "post", post)
    with pytest.raises(requests.HTTPError):
        transcript.get_transcript(_video(duration_s=30), "k", STT, [], tmp_path)
    assert calls == ["audio/mp4", "audio/mpeg"]
    assert env.extract_starts == [0]
