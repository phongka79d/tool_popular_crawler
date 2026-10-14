"""SQLite cache for pages, videos, Jev/LLM outputs and run logs (PLAN §11.8).

Pattern adapted from reference/vyralforge/database/db.py (MIT): a `conn()` contextmanager
that commits and closes, and `INSERT ... ON CONFLICT DO UPDATE` upserts. JSON is stored as TEXT.

Database access functions take an optional `path`; the default is `config.DB_PATH`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import config
from models import Page, Video

JEV_KINDS = ("labels_v2", "suggestion_check")  # labels_v2 = jev_client.LABELS_KIND (bộ câu hỏi hiện tại)

# Schema lives in code (not a .sql file) so the PyInstaller build needs no extra data files.
SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    name            TEXT,
    followers       INTEGER,
    last_scanned_at INTEGER
);

CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,
    url               TEXT,
    page_url          TEXT,
    page_name         TEXT,
    page_followers    INTEGER,
    posted_at         INTEGER,
    format            TEXT,
    is_live           INTEGER NOT NULL DEFAULT 0,
    duration_s        REAL,
    views             INTEGER,
    reactions         INTEGER,
    comments          INTEGER,
    shares            INTEGER,
    caption           TEXT,
    transcript        TEXT,
    transcript_status TEXT,
    transcript_language TEXT,
    transcript_vi     TEXT,
    hook              TEXT,
    updated_at        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_videos_page ON videos(page_url);
CREATE INDEX IF NOT EXISTS idx_videos_posted ON videos(posted_at);

CREATE TABLE IF NOT EXISTS jev_answers (
    video_id     TEXT NOT NULL,
    model        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    usage_json   TEXT,
    created_at   INTEGER,
    PRIMARY KEY (video_id, model, kind)
);

CREATE TABLE IF NOT EXISTS llm_outputs (
    video_id    TEXT PRIMARY KEY,
    model       TEXT,
    output_json TEXT NOT NULL,
    created_at  INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER,
    finished_at INTEGER,
    params_json TEXT,
    log_json    TEXT
);
"""

# Transcript columns: an empty incoming value never erases a stored one. transcript_status
# moves together with transcript: it is replaced only when the incoming transcript is
# non-empty, or when no transcript is stored yet (e.g. "no_speech" / "failed" with no text).
_TRANSCRIPT_MERGE = """
    transcript = COALESCE(NULLIF(excluded.transcript, ''), videos.transcript),
    transcript_status = CASE
        WHEN NULLIF(excluded.transcript, '') IS NOT NULL OR NULLIF(videos.transcript, '') IS NULL
        THEN COALESCE(NULLIF(excluded.transcript_status, ''), videos.transcript_status)
        ELSE videos.transcript_status
    END,
    hook = COALESCE(NULLIF(excluded.hook, ''), videos.hook),
    transcript_language = COALESCE(NULLIF(excluded.transcript_language, ''), videos.transcript_language),
    transcript_vi = COALESCE(NULLIF(excluded.transcript_vi, ''), videos.transcript_vi),
"""

_UPSERT_VIDEO_SQL = f"""
INSERT INTO videos (
    video_id, url, page_url, page_name, page_followers, posted_at, format, is_live, duration_s,
    views, reactions, comments, shares, caption, transcript, transcript_status, transcript_language, transcript_vi, hook, updated_at
) VALUES (
    :video_id, :url, :page_url, :page_name, :page_followers, :posted_at, :format, :is_live, :duration_s,
    :views, :reactions, :comments, :shares, :caption, :transcript, :transcript_status, :transcript_language, :transcript_vi, :hook,
    :updated_at
)
ON CONFLICT(video_id) DO UPDATE SET
    url = COALESCE(NULLIF(excluded.url, ''), videos.url),
    page_url = COALESCE(NULLIF(excluded.page_url, ''), videos.page_url),
    page_name = COALESCE(NULLIF(excluded.page_name, ''), videos.page_name),
    page_followers = COALESCE(excluded.page_followers, videos.page_followers),
    posted_at = COALESCE(excluded.posted_at, videos.posted_at),
    format = COALESCE(NULLIF(excluded.format, ''), videos.format),
    is_live = MAX(videos.is_live, excluded.is_live),
    duration_s = COALESCE(excluded.duration_s, videos.duration_s),
    views = COALESCE(excluded.views, videos.views),
    reactions = COALESCE(excluded.reactions, videos.reactions),
    comments = COALESCE(excluded.comments, videos.comments),
    shares = COALESCE(excluded.shares, videos.shares),
    caption = COALESCE(NULLIF(excluded.caption, ''), videos.caption),
    {_TRANSCRIPT_MERGE}
    updated_at = excluded.updated_at
"""

_SAVE_TRANSCRIPT_SQL = f"""
INSERT INTO videos (video_id, transcript, transcript_status, transcript_language, transcript_vi, hook, updated_at)
VALUES (:video_id, :transcript, :transcript_status, :transcript_language, :transcript_vi, :hook, :updated_at)
ON CONFLICT(video_id) DO UPDATE SET
    {_TRANSCRIPT_MERGE}
    updated_at = excluded.updated_at
"""

_UPSERT_PAGE_SQL = """
INSERT INTO pages (url, name, followers, last_scanned_at)
VALUES (:url, :name, :followers, :last_scanned_at)
ON CONFLICT(url) DO UPDATE SET
    name = COALESCE(NULLIF(excluded.name, ''), pages.name),
    followers = COALESCE(excluded.followers, pages.followers),
    last_scanned_at = excluded.last_scanned_at
"""


@contextmanager
def conn(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on normal exit, always close."""
    db_path = Path(path) if path is not None else Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db(path: str | Path | None = None) -> None:
    """Create all tables and indexes. Safe to call on every start."""
    with conn(path) as c:
        c.executescript(SCHEMA)
        columns = {row["name"] for row in c.execute("PRAGMA table_info(videos)")}
        if "is_live" not in columns:
            c.execute("ALTER TABLE videos ADD COLUMN is_live INTEGER NOT NULL DEFAULT 0")
        if "transcript_language" not in columns:
            c.execute("ALTER TABLE videos ADD COLUMN transcript_language TEXT")
        if "transcript_vi" not in columns:
            c.execute("ALTER TABLE videos ADD COLUMN transcript_vi TEXT")


def upsert_page(page: Page, path: str | Path | None = None) -> None:
    """Insert or update a page; an empty name or None followers keeps the stored value."""
    with conn(path) as c:
        c.execute(
            _UPSERT_PAGE_SQL,
            {"url": page.url, "name": page.name or "", "followers": page.followers,
             "last_scanned_at": _now()},
        )


def upsert_video(video: Video, path: str | Path | None = None) -> None:
    """Insert or update a video.

    Re-running refreshes metrics and caption. A None metric, an empty caption, or an empty
    transcript/hook never overwrites a stored value.
    """
    with conn(path) as c:
        c.execute(_UPSERT_VIDEO_SQL, _video_params(video))


def get_video(video_id: str, path: str | Path | None = None) -> Video | None:
    """Return the stored collected fields of a video.

    `jev`, `llm`, `score` and `notes` are not stored here; use get_jev/get_llm for the caches.
    """
    with conn(path) as c:
        row = c.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return None if row is None else _row_to_video(row)


def get_transcript(video_id: str, path: str | Path | None = None) -> tuple[str, str] | None:
    """Return (transcript, status) for a video that has been transcribed, else None."""
    with conn(path) as c:
        row = c.execute(
            "SELECT transcript, transcript_status FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
    if row is None or not (row["transcript"] or row["transcript_status"]):
        return None
    return (row["transcript"] or "", row["transcript_status"] or "")


def save_transcript(
    video_id: str, text: str, status: str, hook: str, path: str | Path | None = None,
    transcript_language: str = "", transcript_vi: str = "",
) -> None:
    """Store transcript, language, translation and hook. Empty values never erase stored values."""
    with conn(path) as c:
        c.execute(
            _SAVE_TRANSCRIPT_SQL,
            {"video_id": video_id, "transcript": text, "transcript_status": status,
             "hook": hook, "transcript_language": transcript_language,
             "transcript_vi": transcript_vi, "updated_at": _now()},
        )

def analysis_cache_key(video: Video) -> str:
    """Separate image-informed post analysis from the existing text-only cache."""
    if video.format == "post" and video.transcript_status == "images" and video.transcript:
        digest = hashlib.sha256(video.transcript.encode("utf-8")).hexdigest()
        return f"{video.video_id}:images:{digest}"
    return video.video_id



def get_jev(
    video_id: str, model: str, kind: str, path: str | Path | None = None
) -> dict | None:
    """Return the cached Jev answers for (video, model, kind), or None.

    Only the answers are returned. Usage stays in `usage_json` for accounting and is not
    re-counted on a cache hit.
    """
    _check_jev_kind(kind)
    with conn(path) as c:
        row = c.execute(
            "SELECT answers_json FROM jev_answers WHERE video_id = ? AND model = ? AND kind = ?",
            (video_id, model, kind),
        ).fetchone()
    return None if row is None else json.loads(row["answers_json"])


def save_jev(
    video_id: str,
    model: str,
    kind: str,
    answers: dict,
    usage: dict | None,
    path: str | Path | None = None,
) -> None:
    """Cache raw Jev answers. Saving again for the same key replaces the old answers."""
    _check_jev_kind(kind)
    with conn(path) as c:
        c.execute(
            """
            INSERT INTO jev_answers (video_id, model, kind, answers_json, usage_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id, model, kind) DO UPDATE SET
                answers_json = excluded.answers_json,
                usage_json = excluded.usage_json,
                created_at = excluded.created_at
            """,
            (video_id, model, kind, _dumps(answers), _dumps(usage or {}), _now()),
        )


def get_llm(video_id: str, path: str | Path | None = None) -> dict | None:
    """Return the cached LLM output for a video, or None."""
    with conn(path) as c:
        row = c.execute(
            "SELECT output_json FROM llm_outputs WHERE video_id = ?", (video_id,)
        ).fetchone()
    return None if row is None else json.loads(row["output_json"])


def save_llm(video_id: str, model: str, output: dict, path: str | Path | None = None) -> None:
    """Cache the LLM output for a video. Saving again replaces the old output."""
    with conn(path) as c:
        c.execute(
            """
            INSERT INTO llm_outputs (video_id, model, output_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                model = excluded.model,
                output_json = excluded.output_json,
                created_at = excluded.created_at
            """,
            (video_id, model, _dumps(output), _now()),
        )


def start_run(params: dict, path: str | Path | None = None) -> int:
    """Record the start of a run and return its id."""
    with conn(path) as c:
        cur = c.execute(
            "INSERT INTO runs (started_at, params_json) VALUES (?, ?)",
            (_now(), _dumps(params)),
        )
        return int(cur.lastrowid or 0)


def finish_run(run_id: int, log: dict, path: str | Path | None = None) -> None:
    """Record the end of a run and its log. Raises ValueError for an unknown run id."""
    with conn(path) as c:
        cur = c.execute(
            "UPDATE runs SET finished_at = ?, log_json = ? WHERE id = ?",
            (_now(), _dumps(log), run_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Không tìm thấy lần chạy id={run_id}")


def _check_jev_kind(kind: str) -> None:
    if kind not in JEV_KINDS:
        raise ValueError(f"kind không hợp lệ: {kind!r}; phải là một trong {JEV_KINDS}")


def _now() -> int:
    return int(time.time())


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_json_default)


def _json_default(obj: Any) -> Any:
    # Run params carry sets (e.g. RunParams.formats); store them as sorted lists.
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return str(obj)


def _video_params(video: Video) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "url": video.url,
        "page_url": video.page_url,
        "page_name": video.page_name,
        "page_followers": video.page_followers,
        "posted_at": video.posted_at,
        "format": video.format,
        "is_live": int(video.is_live),
        "duration_s": video.duration_s,
        "views": video.views,
        "reactions": video.reactions,
        "comments": video.comments,
        "shares": video.shares,
        "caption": video.caption,
        "transcript": video.transcript,
        "transcript_status": video.transcript_status,
        "transcript_language": video.transcript_language,
        "transcript_vi": video.transcript_vi,
        "hook": video.hook,
        "updated_at": _now(),
    }


def _row_to_video(row: sqlite3.Row) -> Video:
    return Video(
        video_id=row["video_id"],
        url=row["url"] or "",
        page_url=row["page_url"] or "",
        page_name=row["page_name"] or "",
        page_followers=row["page_followers"],
        posted_at=row["posted_at"],
        format=row["format"] or "video",
        is_live=bool(row["is_live"]),
        duration_s=row["duration_s"],
        views=row["views"],
        reactions=row["reactions"],
        comments=row["comments"],
        shares=row["shares"],
        caption=row["caption"] or "",
        transcript=row["transcript"] or "",
        transcript_status=row["transcript_status"] or "",
        transcript_language=row["transcript_language"] or "",
        transcript_vi=row["transcript_vi"] or "",
        hook=row["hook"] or "",
    )
