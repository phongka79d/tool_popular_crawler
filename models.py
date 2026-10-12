"""Shared data records passed between pipeline steps."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    url: str
    name: str = ""
    followers: int | None = None


@dataclass
class Video:
    # --- collected (collectors/facebook.py, collectors/ytdlp.py) ---
    video_id: str                     # Facebook post/video id; cache key
    url: str                          # permalink
    page_url: str
    page_name: str = ""
    page_followers: int | None = None
    posted_at: int | None = None      # unix seconds (UTC)
    format: str = "video"             # "reel" | "video"
    duration_s: float | None = None
    views: int | None = None
    reactions: int | None = None
    comments: int | None = None
    shares: int | None = None
    caption: str = ""
    # --- computed by filters.compute_metrics ---
    ratio_follow: float | None = None
    ratio_median: float | None = None
    engagement: float | None = None
    share_rate: float | None = None
    # --- transcript (collectors/transcript.py) ---
    transcript: str = ""
    transcript_status: str = ""       # "ok" | "no_speech" | "failed" | ""
    hook: str = ""
    # --- analysis ---
    jev: dict = field(default_factory=dict)   # jev_client.interpret_labels() output
    score: float | None = None                # Điểm công thức 0-100
    llm: dict = field(default_factory=dict)   # llm_client.write_analysis() output, suggestions already checked
    notes: list[str] = field(default_factory=list)
