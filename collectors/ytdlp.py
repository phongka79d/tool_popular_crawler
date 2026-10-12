"""Bổ sung chỉ số video và tải audio bằng yt-dlp như thư viện (PLAN §11.3).

yt-dlp là nguồn dự phòng: chỉ điền các trường còn trống, không ghi đè số đã lấy từ GraphQL.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

import yt_dlp
from yt_dlp.utils import YoutubeDLError, download_range_func

import config
from collectors.cookies import is_netscape_file
from models import Video

logger = logging.getLogger(__name__)

_REEL_ID_RE = re.compile(r"facebook\.com/reel/(\d+)", re.IGNORECASE)
_PARTIAL_SUFFIXES = frozenset({".part", ".ytdl", ".temp"})
# Tải lần lượt từng video như người xem, kể cả khi pipeline phân tích nhiều video cùng lúc.
_DOWNLOAD_LOCK = threading.Lock()

# Trường của Video <- (khóa trong info của yt-dlp, kiểu). like_count không dùng:
# đó là số người thích, không phải tổng các loại cảm xúc (PLAN §11.3).
_FILL_FIELDS: dict[str, tuple[str, Callable]] = {
    "views": ("view_count", int),
    "comments": ("comment_count", int),
    "shares": ("repost_count", int),
    "posted_at": ("timestamp", int),
    "duration_s": ("duration", float),
    "caption": ("description", str),
}


def _to_watch_url(url: str) -> str:
    """Link /reel/<id> không hiện đủ bình luận; đổi sang /watch/?v=<id> (crawler-social ADR 0002)."""
    match = _REEL_ID_RE.search(url)
    if match is None:
        return url
    return f"https://m.facebook.com/watch/?v={match.group(1)}"


def _is_empty(value: object) -> bool:
    return value is None or value == ""


def _cookie_opts() -> dict:
    """Cookie Netscape đã xuất từ profile trình duyệt của tool, kèm đúng User-Agent của trình duyệt đó.

    Không đọc cookie của Chrome (PLAN §11.3). Cùng cookie nhưng khác UA trông như phiên bị đánh cắp,
    nên gửi UA đã lưu khi quét/đăng nhập.
    """
    path = config.COOKIE_FILE
    if not path.exists():
        return {}
    if not is_netscape_file(path):
        logger.warning("Tệp cookie %s không đúng định dạng Netscape; bỏ qua cookie.", path)
        return {}
    opts: dict = {"cookiefile": str(path)}
    try:
        user_agent = config.BROWSER_UA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        user_agent = ""
    if user_agent:
        opts["http_headers"] = {"User-Agent": user_agent}
    return opts


class _YdlLog:
    """Thông báo của yt-dlp đi vào logging (data/app.log), không in thẳng ra stdout/stderr.

    Lỗi cuối cùng được chỗ gọi ghi WARNING kèm lý do; ở đây chỉ giữ chi tiết ở mức INFO.
    """

    def debug(self, msg: str) -> None:  # yt-dlp gửi cả thông báo info qua debug
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        logger.info("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.info("yt-dlp: %s", msg)


# Chung cho mọi lượt gọi: không thanh tiến trình, không in ra console.
_QUIET_OPTS = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YdlLog()}


def _with_account_fallback(run: Callable[[dict], object]) -> object:
    """Chạy yt-dlp không cookie trước (video công khai không cần tài khoản, tài khoản không bị dính
    vào lượt tải); chỉ khi lỗi mới thử lại bằng cookie của tài khoản phụ."""
    try:
        return run({})
    except YoutubeDLError:
        account = _cookie_opts()
        if not account:
            raise
        return run(account)


def fetch_metadata(url: str) -> dict:
    """Metadata của một video, không tải file.

    Trả về view_count, comment_count, repost_count, timestamp, duration, description.
    Khóa nào yt-dlp không có thì giá trị là None.
    """
    def run(extra: dict) -> dict:
        opts = {**_QUIET_OPTS, "skip_download": True, "noplaylist": True,
                "sleep_interval_requests": 1, **extra}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(_to_watch_url(url), download=False) or {}

    info = _with_account_fallback(run)
    return {key: info.get(key) for key, _cast in _FILL_FIELDS.values()}


def fill_missing(video: Video) -> None:
    """Điền các trường còn trống (None hoặc chuỗi rỗng) từ yt-dlp. Không ghi đè giá trị đã có."""
    if not any(_is_empty(getattr(video, attr)) for attr in _FILL_FIELDS):
        return
    try:
        info = fetch_metadata(video.url)
    except YoutubeDLError as exc:
        logger.warning("yt-dlp không đọc được metadata của %s: %s", video.video_id, exc)
        return
    for attr, (key, cast) in _FILL_FIELDS.items():
        value = info.get(key)
        if _is_empty(getattr(video, attr)) and not _is_empty(value):
            setattr(video, attr, cast(value))


def _find_download(out_dir: Path, stem: str) -> Path | None:
    """File tải xong có tên bắt đầu bằng stem; bỏ file tạm .part và file rỗng."""
    candidates = sorted(
        path
        for path in out_dir.glob(f"{stem}.*")
        if path.is_file() and path.suffix.lower() not in _PARTIAL_SUFFIXES and path.stat().st_size > 0
    )
    return candidates[0] if candidates else None


def download_audio(url: str, out_dir: Path, first_seconds: int | None = None,
                   ffmpeg: str | None = None) -> Path | None:
    """Tải audio (bestaudio) vào out_dir.

    Coi là thành công khi có file đã tải xong, kể cả khi yt-dlp báo lỗi
    (ví dụ phụ đề hỏng; PLAN §11.5). Không có file thì trả None.
    `first_seconds` (cần `ffmpeg`): chỉ tải chừng ấy giây đầu, cho video dài như livestream
    (3 giờ là ~95 MB audio, 10 phút ~5 MB). Tải đoạn đầu không được thì tải cả audio.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = _to_watch_url(url)
    stem = "audio_" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]

    def run(extra: dict) -> Path:
        opts = {
            **_QUIET_OPTS,
            # bestaudio là ưu tiên; /best cho video chỉ có luồng ghép, transcript.extract_audio tách tiếng sau.
            "format": "bestaudio/best",
            "outtmpl": os.path.join(str(out), f"{stem}.%(ext)s"),
            "noplaylist": True,
            # Nghỉ ngẫu nhiên trước mỗi lượt tải như người xem lần lượt từng video.
            "sleep_interval": 2,
            "max_sleep_interval": 6,
            **extra,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([target])
        except YoutubeDLError as exc:
            # yt-dlp có thể lỗi dù file đã có (ví dụ phụ đề hỏng); quyết định theo file.
            if _find_download(out, stem) is None:
                raise
            logger.warning("yt-dlp báo lỗi nhưng đã có audio (%s): %s", url, exc)
        found = _find_download(out, stem)
        if found is None:
            raise YoutubeDLError("không có file audio")
        return found

    attempts: list[dict] = [{}]
    if first_seconds and ffmpeg:
        attempts.insert(0, {"download_ranges": download_range_func(None, [(0, first_seconds)]),
                            "ffmpeg_location": ffmpeg})
    with _DOWNLOAD_LOCK:
        for number, section in enumerate(attempts, 1):
            try:
                return _with_account_fallback(lambda extra: run({**section, **extra}))
            except Exception as exc:  # noqa: BLE001 - mọi lỗi tải đều quy về "không có audio"
                if number < len(attempts):
                    logger.warning("Không tải được %s giây đầu (%s): %s; tải cả audio", first_seconds, url, exc)
                else:
                    logger.warning("Không tải được audio (%s): %s", url, exc)
    return None
