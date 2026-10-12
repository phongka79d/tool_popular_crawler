"""Tách audio, chuyển thoại (Deepgram; dự phòng faster-whisper chạy máy) và lấy câu hook.

Xem PLAN-JEV.md mục 4 (bước 1–6) và mục 11.5.
"""
from __future__ import annotations

import functools
import logging
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import requests

import config
import db
from collectors.ytdlp import download_audio
from errors import AuthError, QuotaError, ServiceError
from models import Video
from retry import with_retry

log = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_MODELS_URL = "https://api.deepgram.com/v1/models"
DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"
DEEPGRAM_LIST_TIMEOUT_S = 30
DEEPGRAM_TIMEOUT_S = 300
FFMPEG_TIMEOUT_S = 600
# Chỉ chép lời 10 phút: hook và cấu trúc nằm ở đầu video, Jev chỉ đọc 3000 ký tự đầu,
# còn livestream 3 giờ sẽ tốn ~3 phút Deepgram, tiền và một prompt LLM rất dài.
MAX_AUDIO_SECONDS = 600
# Livestream thường mở đầu bằng nhạc chờ nhiều phút: tải 30 phút đầu, chép từng đoạn 10 phút
# tới khi gặp thoại.
SPEECH_SEARCH_SECONDS = 1800
SAMPLE_PATH = config.ROOT / "assets" / "sample_1s.mp3"

HOOK_WINDOW_S = 3.0
HOOK_MAX_EXTRA_WORDS = 40          # giới hạn nối thêm tới dấu kết câu (video không có dấu câu)
CAPTION_HOOK_CHARS = 200
TRANSCRIPT_HOOK_WORDS = 30

STATUS_OK = "ok"
STATUS_NO_SPEECH = "no_speech"
STATUS_FAILED = "failed"
NOTE_NO_SPEECH = "Không có thoại"
NOTE_FAILED = "Chưa lấy được thoại"
_STATUS_NOTES = {STATUS_NO_SPEECH: NOTE_NO_SPEECH, STATUS_FAILED: NOTE_FAILED}
_CACHED_STATUSES = (STATUS_OK, STATUS_NO_SPEECH)

_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]»]*$")
_POPEN_KWARGS: dict[str, Any] = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)
# faster-whisper dùng hết CPU: các video phân tích song song chạy lần lượt, mô hình chỉ nạp một lần.
_WHISPER_LOCK = threading.Lock()


# --- audio -----------------------------------------------------------------

def _ffmpeg_exe() -> str | None:
    bundled = config.ROOT / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")


def extract_audio(src: Path | str, dst: Path | str, start_s: int = 0) -> Path | None:
    """Tách audio mono 16 kHz 64 kbps mp3 từ `src`, tối đa MAX_AUDIO_SECONDS kể từ giây `start_s`.

    Trả None nếu ffmpeg lỗi hoặc không ra audio (kể cả khi `start_s` vượt quá độ dài)."""
    src_path, dst_path = Path(src), Path(dst)
    exe = _ffmpeg_exe()
    if exe is None:
        log.error("Không tìm thấy ffmpeg (ffmpeg.exe cạnh tool hoặc trong PATH)")
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

def _parse_deepgram(payload: Any) -> dict:
    try:
        alt = payload["results"]["channels"][0]["alternatives"][0]
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
    return {
        "text": str(alt.get("transcript") or "").strip(),
        "duration": float(duration),
        "words": words,
    }


def transcribe_deepgram(path: Path | str, api_key: str, stt: dict, keyterms: list[str]) -> dict:
    """Gửi file mp3 tới Deepgram /v1/listen. Trả {"text", "duration" (giây), "words"}.

    Raises: AuthError (401/403), QuotaError (402, hoặc 429/529 quá số lần thử), NetworkError.
    """
    params: list[tuple[str, str]] = [
        ("model", stt["model"]),
        ("language", stt["language"]),
        ("smart_format", "true"),
    ]
    params += [("keyterm", term) for term in keyterms]
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "audio/mpeg"}
    audio = Path(path)

    def _post() -> Any:
        with audio.open("rb") as fh:
            resp = requests.post(DEEPGRAM_URL, params=params, headers=headers,
                                 data=fh, timeout=DEEPGRAM_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()

    return _parse_deepgram(with_retry(_post, service="deepgram"))


@functools.lru_cache(maxsize=1)
def _load_whisper(model_size: str) -> Any:
    from faster_whisper import WhisperModel  # import muộn: chỉ cần khi bật dự phòng chạy máy

    return WhisperModel(model_size, device="cpu", compute_type="int8", download_root=str(config.MODELS_DIR))


def transcribe_local(path: Path | str, model_size: str) -> dict:
    """faster-whisper chạy CPU, tiếng Việt, có timestamp từng từ. Cùng định dạng với Deepgram."""
    with _WHISPER_LOCK:
        model = _load_whisper(model_size)
        segments, info = model.transcribe(str(path), language="vi", word_timestamps=True)
        texts: list[str] = []
        words: list[dict] = []
        for seg in segments:  # segments chạy dần khi đọc: phải đọc hết trong khóa
            seg_text = seg.text.strip()
            if seg_text:
                texts.append(seg_text)
            for w in seg.words or []:
                token = w.word.strip()
                if token:
                    words.append({"punctuated_word": token, "start": float(w.start), "end": float(w.end)})
    return {"text": " ".join(texts), "duration": float(info.duration), "words": words}


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
    return 0.0


def _save(video: Video, text: str, status: str, words: list[dict], minutes: float) -> float:
    hook = hook_3s(words) or first_lines_hook(video.caption, text)
    _set_fields(video, text, status, hook)
    db.save_transcript(video.video_id, text, status, hook)
    return minutes


def _transcribe(audio: Path, api_key: str, stt: dict, keyterms: list[str],
                warnings: list[str]) -> tuple[dict | None, float]:
    """Trả (kết quả, phút Deepgram đã tính phí); ghi cảnh báo hạn mức và trạng thái dự phòng."""
    try:
        result = transcribe_deepgram(audio, api_key, stt, keyterms)
        return result, result["duration"] / 60.0
    except QuotaError as exc:
        log.warning("Deepgram không dùng được: %s", exc)

    warning = "Tài khoản Deepgram đã hết credit/hạn mức."
    if stt.get("fallback") != "local_whisper":
        warnings.append(f"{warning} Không dùng local whisper (đã tắt dự phòng).")
        return None, 0.0

    model_size = stt.get("whisper_model", "small")
    log.info("Chuyển sang faster-whisper (%s) chạy máy", model_size)
    try:
        result = transcribe_local(audio, model_size)
        warnings.append(f"{warning} Đã dùng local whisper.")
        return result, 0.0
    except Exception:
        log.exception("faster-whisper lỗi, bỏ qua thoại của video")
        warnings.append(f"{warning} Đã thử local whisper nhưng không lấy được thoại.")
        return None, 0.0


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
    AuthError được chuyển cho bên gọi để tạm dừng; chỉ QuotaError dùng local whisper.
    Nếu truyền `warnings`, thêm cảnh báo hạn mức và kết quả dự phòng vào danh sách này.
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
        start = 0
        for start in starts:
            _remove(audio)
            audio = extract_audio(downloaded, tmp / f"{video.video_id}_stt.mp3", start_s=start)
            if audio is None:
                if start == 0:
                    log.warning("Không có audio để chuyển thoại: %s", video.video_id)
                    return _save(video, "", STATUS_FAILED, [], 0.0)
                break  # tệp ngắn hơn dự kiến: giữ kết quả đoạn trước
            result, billed = _transcribe(audio, api_key, stt_settings, keyterms,
                                         warnings if warnings is not None else [])
            minutes += billed
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
