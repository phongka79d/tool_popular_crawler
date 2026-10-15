"""Tách audio, chuyển thoại bằng Deepgram và lấy câu hook.

Xem PLAN-JEV.md mục 4 (bước 1–6) và mục 11.5.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests

from backend.core import config
from backend.core import db
from backend.collectors.ytdlp import download_audio
from backend.core.errors import QuotaError, ServiceError
from backend.core.models import Video
from backend.core.retry import with_retry

log = logging.getLogger(__name__)

_usage = threading.local()

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_MODELS_URL = "https://api.deepgram.com/v1/models"
DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"
DEEPGRAM_LIST_TIMEOUT_S = 30
DEEPGRAM_TIMEOUT_S = 300
LANGUAGE_CONFIDENCE_THRESHOLD = 0.5
FFMPEG_TIMEOUT_S = 600
# Chỉ chép lời 10 phút: hook và cấu trúc nằm ở đầu video, Jev chỉ đọc 3000 ký tự đầu,
# còn livestream 3 giờ sẽ tốn ~3 phút Deepgram, tiền và một prompt LLM rất dài.
MAX_AUDIO_SECONDS = 600
MAX_DIRECT_AUDIO_BYTES = 50 * 1024 * 1024
_AUDIO_TYPES = {
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm",
    ".opus": "audio/ogg", ".ogg": "audio/ogg", ".mp3": "audio/mpeg",
}
# Livestream thường mở đầu bằng nhạc chờ nhiều phút: tải 30 phút đầu, chép từng đoạn 10 phút
# tới khi gặp thoại.
SPEECH_SEARCH_SECONDS = 1800
SAMPLE_PATH = config.BUNDLE_DIR / "assets" / "sample_1s.mp3"

HOOK_WINDOW_S = 3.0
HOOK_MAX_EXTRA_WORDS = 40          # giới hạn nối thêm tới dấu kết câu (video không có dấu câu)
CAPTION_HOOK_CHARS = 200
TRANSCRIPT_HOOK_WORDS = 30

STATUS_OK = "ok"
STATUS_NO_SPEECH = "no_speech"
STATUS_FAILED = "failed"
NOTE_NO_SPEECH = "Không có thoại"
NOTE_FAILED = "Chưa lấy được thoại"
NOTE_LANGUAGE_UNCERTAIN = "Không chắc ngôn ngữ thoại, đã dùng tiếng Việt"
_STATUS_NOTES = {STATUS_NO_SPEECH: NOTE_NO_SPEECH, STATUS_FAILED: NOTE_FAILED}
_CACHED_STATUSES = (STATUS_OK, STATUS_NO_SPEECH)

_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]»]*$")
_POPEN_KWARGS: dict[str, Any] = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)


@contextmanager
def observe_usage(callback: Callable[[float], None]) -> Iterator[None]:
    """Báo từng lượt Deepgram trên luồng hiện tại, kể cả lượt không có thoại."""
    previous = getattr(_usage, "callback", None)
    _usage.callback = callback
    try:
        yield
    finally:
        _usage.callback = previous


@contextmanager
def observe_timing(callback: Callable[[str, float], None]) -> Iterator[None]:
    """Báo thời gian từng bước trên luồng phân tích, không thêm sự kiện UI."""
    previous = getattr(_usage, "timing", None)
    _usage.timing = callback
    try:
        yield
    finally:
        _usage.timing = previous


@contextmanager
def _timed(stage: str) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        callback = getattr(_usage, "timing", None)
        if callback is not None:
            callback(stage, time.monotonic() - started)


def _can_send_original(path: Path, duration_s: float | None) -> bool:
    return (duration_s is not None and 0 < duration_s <= MAX_AUDIO_SECONDS
            and path.suffix.lower() in _AUDIO_TYPES
            and 0 < path.stat().st_size < MAX_DIRECT_AUDIO_BYTES)

# --- audio -----------------------------------------------------------------

def _ffmpeg_exe() -> str | None:
    bundled = config.BUNDLE_DIR / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")


def extract_audio(src: Path | str, dst: Path | str, start_s: int = 0) -> Path | None:
    """Tách audio mono 16 kHz 64 kbps mp3 từ `src`, tối đa MAX_AUDIO_SECONDS kể từ giây `start_s`.

    Trả None nếu ffmpeg lỗi hoặc không ra audio (kể cả khi `start_s` vượt quá độ dài)."""
    src_path, dst_path = Path(src), Path(dst)
    exe = _ffmpeg_exe()
    if exe is None:
        log.error("Không tìm thấy ffmpeg (ffmpeg.exe trong thư mục app của tool hoặc trong PATH)")
        return None

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        *(["-ss", str(start_s)] if start_s else []),
        "-i", str(src_path.resolve()),
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        "-t", str(MAX_AUDIO_SECONDS),
        str(dst_path.resolve()),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=FFMPEG_TIMEOUT_S, **_POPEN_KWARGS)
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg quá thời gian khi tách audio: %s", src_path.name)
        return None
    if proc.returncode != 0:
        log.warning("ffmpeg lỗi khi tách audio %s: %s", src_path.name, proc.stderr.strip()[:300])
        return None
    if not dst_path.exists() or dst_path.stat().st_size == 0:
        log.warning("ffmpeg không tạo ra audio (video có thể không có tiếng): %s", src_path.name)
        return None
    return dst_path


# --- speech-to-text --------------------------------------------------------

def _parse_deepgram(payload: Any, language: str = "") -> dict:
    try:
        channel = payload["results"]["channels"][0]
        alt = channel["alternatives"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ServiceError("deepgram", "Deepgram trả về dữ liệu không đúng định dạng.") from exc

    duration = (payload.get("metadata") or {}).get("duration") or 0.0
    words: list[dict] = []
    for raw in alt.get("words") or []:
        token = str(raw.get("punctuated_word") or raw.get("word") or "").strip()
        if not token:
            continue
        words.append({
            "punctuated_word": token,
            "start": float(raw.get("start") or 0.0),
            "end": float(raw.get("end") or 0.0),
        })
    confidence = channel.get("language_confidence")
    text = str(alt.get("transcript") or "").strip()
    # Không có thoại thì ngôn ngữ "phát hiện" chỉ là đoán (độ tin cậy ~0): bỏ trống.
    return {
        "text": text,
        "duration": float(duration),
        "words": words,
        "language": str(channel.get("detected_language") or language or "") if text else "",
        "language_confidence": float(confidence) if confidence is not None and text else None,
    }


def transcribe_deepgram(path: Path | str, api_key: str, stt: dict, keyterms: list[str]) -> dict:
    """Gửi audio với Content-Type theo định dạng tới Deepgram; trả text, duration, words và ngôn ngữ.

    Raises: AuthError (401/403), QuotaError (402, hoặc 429/529 quá số lần thử), NetworkError.
    """
    params: list[tuple[str, str]] = [
        ("model", stt["model"]),
        *([("detect_language", "vi"), ("detect_language", "en")]
          if stt.get("auto_language", True) else [("language", stt["language"])]),
        ("smart_format", "true"),
    ]
    params += [("keyterm", term) for term in keyterms]
    audio = Path(path)
    headers = {"Authorization": f"Token {api_key}",
               "Content-Type": _AUDIO_TYPES.get(audio.suffix.lower(), "audio/mpeg")}

    def _post() -> Any:
        with audio.open("rb") as fh:
            resp = requests.post(DEEPGRAM_URL, params=params, headers=headers,
                                 data=fh, timeout=DEEPGRAM_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()

    language = "" if stt.get("auto_language", True) else stt["language"]
    return _parse_deepgram(with_retry(_post, service="deepgram"), language)


def check_key(api_key: str, stt: dict | None = None) -> None:
    """Gọi thử Deepgram bằng file mẫu 1 giây với model/ngôn ngữ của `stt` (mặc định: settings). Sai key thì raise AuthError."""
    stt = stt or config.load_settings()["stt"]
    transcribe_deepgram(SAMPLE_PATH, api_key, stt, [])


def list_deepgram_models(api_key: str) -> list[dict]:
    """Model chuyển thoại file ghi sẵn (batch) của Deepgram, gộp theo canonical_name, sắp theo tên.

    Mỗi mục: {"name": canonical_name (giá trị gửi ở tham số model), "architecture",
    "languages": [{"code", "label"}]}. Kiểm tra key trước (GET /v1/projects); sai key → AuthError.
    Deepgram không trả giá qua API.
    """
    headers = {"Authorization": f"Token {api_key}"}

    def _get(url: str) -> Any:
        resp = requests.get(url, headers=headers, timeout=DEEPGRAM_LIST_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()

    with_retry(lambda: _get(DEEPGRAM_PROJECTS_URL), service="deepgram")
    payload = with_retry(lambda: _get(DEEPGRAM_MODELS_URL), service="deepgram")
    names: dict[str, str] = payload.get("languages") or {}
    merged: dict[str, dict] = {}
    for m in payload.get("stt") or []:
        if not m.get("batch") or not m.get("canonical_name"):
            continue
        entry = merged.setdefault(m["canonical_name"], {"name": m["canonical_name"],
                                                       "architecture": m.get("architecture") or "",
                                                       "codes": set()})
        entry["codes"].update(m.get("languages") or [])
    return [
        {"name": e["name"], "architecture": e["architecture"],
         "languages": [{"code": c, "label": names.get(c, c)} for c in sorted(e["codes"])]}
        for e in sorted(merged.values(), key=lambda e: e["name"])
    ]


# --- hook ------------------------------------------------------------------

def _start(word: dict) -> float:
    return float(word.get("start") or 0.0)


def _token(word: dict) -> str:
    return str(word.get("punctuated_word") or "").strip()


def hook_3s(words: list[dict]) -> str:
    """Câu hook: các từ bắt đầu trước 3,0 giây, nối thêm tới dấu kết câu nếu câu chưa hết.

    `words` theo thứ tự thời gian. Trả "" nếu không có từ nào bắt đầu trong 3 giây đầu.
    """
    head = 0
    while head < len(words) and _start(words[head]) < HOOK_WINDOW_S:
        head += 1
    if head == 0:
        return ""

    tokens = [_token(w) for w in words[:head]]
    idx = head
    extra = 0
    while (idx < len(words) and extra < HOOK_MAX_EXTRA_WORDS
           and not _SENTENCE_END.search(tokens[-1])):
        tokens.append(_token(words[idx]))
        idx += 1
        extra += 1
    return " ".join(t for t in tokens if t)


def first_lines_hook(caption: str, transcript: str) -> str:
    """Hook dự phòng: dòng đầu caption (≤200 ký tự) và 30 từ đầu thoại, nối bằng xuống dòng."""
    lines = (caption or "").strip().splitlines()
    first = lines[0].strip()[:CAPTION_HOOK_CHARS].strip() if lines else ""
    spoken = " ".join((transcript or "").split()[:TRANSCRIPT_HOOK_WORDS])
    return "\n".join(part for part in (first, spoken) if part)


# --- orchestration ---------------------------------------------------------

def _add_note(video: Video, note: str) -> None:
    if note not in video.notes:
        video.notes.append(note)


def _set_fields(video: Video, text: str, status: str, hook: str) -> None:
    video.transcript = text
    video.transcript_status = status
    video.hook = hook
    if status in _STATUS_NOTES:
        _add_note(video, _STATUS_NOTES[status])


def _apply_cached(video: Video, text: str, status: str) -> float:
    stored = db.get_video(video.video_id)
    hook = (stored.hook if stored and stored.hook else "") or first_lines_hook(video.caption, text)
    _set_fields(video, text, status, hook)
    if stored:
        video.transcript_language = stored.transcript_language
        video.transcript_vi = stored.transcript_vi
    return 0.0


def _save(video: Video, text: str, status: str, words: list[dict], minutes: float) -> float:
    hook = hook_3s(words) or first_lines_hook(video.caption, text)
    _set_fields(video, text, status, hook)
    db.save_transcript(video.video_id, text, status, hook,
                       transcript_language=video.transcript_language)
    return minutes


def _transcribe(audio: Path, api_key: str, stt: dict, keyterms: list[str],
                warnings: list[str]) -> tuple[dict | None, float]:
    """Trả (kết quả, phút Deepgram đã tính phí); ghi cảnh báo khi hết hạn mức."""
    minutes = 0.0
    uncertain = False
    try:
        for attempt in range(2):
            result = None
            call_settings = {**stt, "auto_language": False, "language": "vi"} if attempt else stt
            try:
                with _timed("Deepgram"):
                    result = transcribe_deepgram(audio, api_key, call_settings, keyterms)
            finally:
                billed = result["duration"] / 60.0 if result is not None else 0.0
                minutes += billed
                callback = getattr(_usage, "callback", None)
                if callback is not None:
                    callback(billed)
            confidence = result.get("language_confidence")
            if (attempt == 0 and stt.get("auto_language", True)
                    and confidence is not None and confidence < LANGUAGE_CONFIDENCE_THRESHOLD):
                uncertain = True
                continue
            if uncertain:
                result["language"] = "vi"
                result["language_note"] = NOTE_LANGUAGE_UNCERTAIN
            return result, minutes
    except QuotaError as exc:
        log.warning("Deepgram không dùng được: %s", exc)

    warnings.append("Tài khoản Deepgram đã hết credit/hạn mức. "
                    "Nạp thêm hoặc đổi key Deepgram trong Cài đặt rồi quét lại.")
    return None, minutes


def _remove(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Không xóa được file tạm %s: %s", path, exc)


def get_transcript(video: Video, api_key: str, stt_settings: dict,
                   keyterms: list[str], tmp_dir: Path | str,
                   warnings: list[str] | None = None) -> float:
    """Điền video.transcript, transcript_status, hook (và ghi chú). Trả số phút Deepgram đã tính phí.

    Cache: transcript "ok" hoặc "no_speech" trong SQLite được dùng lại, không tải lại audio.
    Transcript "failed" không nằm trong cache nên lần chạy sau sẽ thử lại.
    AuthError được chuyển cho bên gọi để tạm dừng; QuotaError đánh dấu thất bại.
    Nếu truyền `warnings`, thêm cảnh báo hạn mức vào danh sách này.
    """
    cached = db.get_transcript(video.video_id)
    if cached is not None and cached[1] in _CACHED_STATUSES:
        text, status = cached
        return _apply_cached(video, text, status)

    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    downloaded: Path | None = None
    audio: Path | None = None
    try:
        long_video = bool(video.duration_s and video.duration_s > MAX_AUDIO_SECONDS)
        with _timed("tải audio"):
            if long_video:
                # Không tải cả livestream nhiều giờ: chỉ phần đủ để tìm đoạn có thoại.
                downloaded = download_audio(video.url, tmp, first_seconds=SPEECH_SEARCH_SECONDS, ffmpeg=_ffmpeg_exe())
                starts = list(range(0, int(min(video.duration_s, SPEECH_SEARCH_SECONDS)), MAX_AUDIO_SECONDS))
            else:
                downloaded = download_audio(video.url, tmp)
                starts = [0]
        if downloaded is None:
            log.warning("Không có audio để chuyển thoại: %s", video.video_id)
            return _save(video, "", STATUS_FAILED, [], 0.0)

        minutes = 0.0
        result: dict | None = None
        direct = _can_send_original(downloaded, video.duration_s)
        start = 0
        for start in starts:
            _remove(audio if audio != downloaded else None)
            if direct:
                audio = downloaded
            else:
                with _timed("ffmpeg"):
                    audio = extract_audio(downloaded, tmp / f"{video.video_id}_stt.mp3", start_s=start)
            if audio is None:
                if start == 0:
                    log.warning("Không có audio để chuyển thoại: %s", video.video_id)
                    return _save(video, "", STATUS_FAILED, [], 0.0)
                break  # tệp ngắn hơn dự kiến: giữ kết quả đoạn trước
            try:
                result, billed = _transcribe(audio, api_key, stt_settings, keyterms,
                                             warnings if warnings is not None else [])
            except requests.HTTPError as exc:
                if not direct or exc.response is None or exc.response.status_code != 400:
                    raise
                # Chỉ file gốc bị từ chối mới thử lại một lần bằng đường mp3 cũ.
                direct = False
                with _timed("ffmpeg"):
                    audio = extract_audio(downloaded, tmp / f"{video.video_id}_stt.mp3", start_s=start)
                if audio is None:
                    return _save(video, "", STATUS_FAILED, [], minutes)
                result, billed = _transcribe(audio, api_key, stt_settings, keyterms,
                                             warnings if warnings is not None else [])
            minutes += billed
            if result is not None:
                video.transcript_language = result.get("language") or video.transcript_language
                if result.get("language_note"):
                    _add_note(video, result["language_note"])
            if result is None:
                return _save(video, "", STATUS_FAILED, [], minutes)
            if result["text"]:
                break
            if start < starts[-1]:
                log.info("Video %s: không có thoại từ phút %d, thử 10 phút tiếp theo",
                         video.video_id, start // 60)
        text = result["text"] if result is not None else ""
        if long_video:
            if not text:
                searched = f"không thấy thoại trong {(start + MAX_AUDIO_SECONDS) // 60} phút đầu"
            else:
                searched = f"chỉ chép lời 10 phút {'đầu' if start == 0 else f'từ phút {start // 60}'}"
            _add_note(video, f"Video dài {video.duration_s / 60:.0f} phút: {searched}.")
        if not text:
            return _save(video, "", STATUS_NO_SPEECH, [], minutes)
        return _save(video, text, STATUS_OK, result["words"], minutes)
    finally:
        _remove(audio)
        _remove(downloaded)
