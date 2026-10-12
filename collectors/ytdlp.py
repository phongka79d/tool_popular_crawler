"""Bổ sung chỉ số video và tải audio bằng yt-dlp như thư viện (PLAN §11.3).

yt-dlp là nguồn dự phòng: chỉ điền các trường còn trống, không ghi đè số đã lấy từ GraphQL.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import yt_dlp
from yt_dlp.utils import YoutubeDLError

import config
from collectors.cookies import is_netscape_file
from models import Video

logger = logging.getLogger(__name__)

_REEL_ID_RE = re.compile(r"facebook\.com/reel/(\d+)", re.IGNORECASE)
_PARTIAL_SUFFIXES = frozenset({".part", ".ytdl", ".temp"})

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
    """Dùng tệp cookie Netscape đã xuất từ profile Playwright; không đọc cookie của Chrome (PLAN §11.3)."""
    path = config.COOKIE_FILE
    if not path.exists():
        return {}
    if not is_netscape_file(path):
        logger.warning("Tệp cookie %s không đúng định dạng Netscape; bỏ qua cookie.", path)
        return {}
    return {"cookiefile": str(path)}


def fetch_metadata(url: str) -> dict:
    """Metadata của một video, không tải file.

    Trả về view_count, comment_count, repost_count, timestamp, duration, description.
    Khóa nào yt-dlp không có thì giá trị là None.
    """
    opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True, **_cookie_opts()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_to_watch_url(url), download=False) or {}
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


def download_audio(url: str, out_dir: Path) -> Path | None:
    """Tải audio (bestaudio) vào out_dir.

    Coi là thành công khi có file đã tải xong, kể cả khi yt-dlp báo lỗi
    (ví dụ phụ đề hỏng; PLAN §11.5). Không có file thì trả None.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = _to_watch_url(url)
    stem = "audio_" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]
    opts = {
        # bestaudio là ưu tiên; /best cho video chỉ có luồng ghép, transcript.extract_audio tách tiếng sau.
        "format": "bestaudio/best",
        "outtmpl": os.path.join(str(out), f"{stem}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([target])
    except Exception as exc:  # noqa: BLE001 - yt-dlp có thể lỗi dù file đã có; quyết định theo file
        logger.warning("yt-dlp báo lỗi khi tải audio (%s): %s", url, exc)
    found = _find_download(out, stem)
    if found is None:
        logger.warning("Không tải được audio: %s", url)
    return found
