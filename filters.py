"""Lọc theo lượt xem hoặc tổng tương tác và tính Điểm công thức."""
from __future__ import annotations

import statistics

from models import Video

MIN_VIDEOS_FOR_MEDIAN = 5
NOTE_TOO_FEW_FOR_MEDIAN = f"Chưa đủ {MIN_VIDEOS_FOR_MEDIAN} video để tính trung vị"
NOTE_ZERO_MEDIAN = "Trung vị view của page bằng 0, không tính được hệ số trung vị"
_MEDIAN_NOTES = (NOTE_TOO_FEW_FOR_MEDIAN, NOTE_ZERO_MEDIAN)



def compute_metrics(videos: list[Video]) -> None:
    """Tính chỉ số tại chỗ; trung vị riêng theo kênh và loại nội dung."""
    groups: dict[tuple[str, bool], list[Video]] = {}
    post_notes = ("Chưa đủ 5 bài đăng để tính trung vị",
                  "Trung vị tương tác của page bằng 0, không tính được hệ số trung vị")
    for video in videos:
        known = [part for part in (video.reactions, video.comments, video.shares) if part is not None]
        video.interactions = sum(known) if known else None
        groups.setdefault((video.page_url, video.format == "post"), []).append(video)
    for (_, is_post), group in groups.items():
        values = [v.interactions if is_post else v.views for v in group]
        known = [value for value in values if value is not None]
        notes = post_notes if is_post else _MEDIAN_NOTES
        median = statistics.median(known) if len(known) >= MIN_VIDEOS_FOR_MEDIAN else None
        note = notes[0] if median is None else notes[1] if median == 0 else None
        for video, value in zip(group, values):
            video.ratio_follow = _safe_div(video.views, video.page_followers)
            video.ratio_median = _safe_div(value, median)
            video.engagement = _engagement(video)
            video.share_rate = _safe_div(video.shares, video.views)
            video.notes = [n for n in video.notes if n not in (*_MEDIAN_NOTES, *post_notes)]
            if note is not None:
                video.notes.append(note)


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _engagement(video: Video) -> float | None:
    parts = (video.reactions, video.comments, video.shares)
    if video.views is None or any(part is None for part in parts):
        return None
    return _safe_div(sum(parts), video.views)


def passes(video: Video, min_views: int = 0, min_interactions: int = 0,
           min_ratio_follow: float = 0, match_all: bool = True) -> bool:
    """Ngưỡng bao gồm giá trị bằng; 0 tắt lọc, số liệu chưa biết không đạt.

    Bài đăng chỉ dùng tương tác. Video dùng lượt xem và tỷ lệ lượt xem/follower:
    `match_all` yêu cầu mọi điều kiện đang bật cùng đạt, ngược lại chỉ cần một.
    """
    if video.format == "post":
        return min_interactions <= 0 or (video.interactions is not None and video.interactions >= min_interactions)
    results = []
    if min_views > 0:
        results.append(video.views is not None and video.views >= min_views)
    if min_ratio_follow > 0:
        ratio = _safe_div(video.views, video.page_followers)
        results.append(ratio is not None and ratio >= min_ratio_follow)
    if not results:
        return True
    return all(results) if match_all else any(results)


def apply_filter(videos: list[Video], min_views: int = 0, min_interactions: int = 0,
                 min_ratio_follow: float = 0, match_all: bool = True) -> list[Video]:
    return [video for video in videos
            if passes(video, min_views, min_interactions, min_ratio_follow, match_all)]


def formula_score(
    ratio_median: float | None,
    replicable_p: float | None,
    hook_strength: int | None,
    relevant_p: float | None,
    weights: dict,
    jev_viral: float | None = None,
) -> float:
    """Điểm công thức 0–100 theo PLAN §6:

        diem = w_ratio·min(ratio_median/cap, 1) + w_replicable·replicable_p
               + w_hook·(hook_strength/2) + w_relevant·relevant_p + w_jev·jev_viral

    weights là settings["score_weights"]. Đầu vào None tính bằng 0; xác suất và hook được kẹp về miền hợp lệ.
    """
    cap = weights["ratio_median_cap"]
    if cap <= 0:
        raise ValueError("ratio_median_cap phải lớn hơn 0")

    ratio_part = _clamp01(ratio_median / cap) if ratio_median is not None else 0.0
    replicable = _clamp01(replicable_p) if replicable_p is not None else 0.0
    hook = _clamp01(hook_strength / 2) if hook_strength is not None else 0.0
    relevant = _clamp01(relevant_p) if relevant_p is not None else 0.0

    score = (
        weights["ratio_median"] * ratio_part
        + weights["replicable"] * replicable
        + weights["hook_strength"] * hook
        + weights["relevant"] * relevant
        + weights.get("jev_viral", 0) * (_clamp01(jev_viral) if jev_viral is not None else 0.0)
    )
    return float(min(max(score, 0.0), 100.0))


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)
