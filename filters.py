"""Lọc viral bằng code thuần (PLAN §5) và Điểm công thức (PLAN §6).

Jev không tham gia bước này: mọi phép tính, so sánh ngưỡng và cộng điểm đều nằm ở đây.
"""
from __future__ import annotations

import logging
import statistics

from models import Video

log = logging.getLogger(__name__)

MIN_VIDEOS_FOR_MEDIAN = 5
NOTE_TOO_FEW_FOR_MEDIAN = f"Chưa đủ {MIN_VIDEOS_FOR_MEDIAN} video để tính trung vị"
NOTE_ZERO_MEDIAN = "Trung vị view của page bằng 0, không tính được hệ số trung vị"
_MEDIAN_NOTES = (NOTE_TOO_FEW_FOR_MEDIAN, NOTE_ZERO_MEDIAN)

# Chỉ số có thể dùng làm điều kiện lọc (ngưỡng tối thiểu).
RULE_METRICS = frozenset(
    {"views", "ratio_follow", "ratio_median", "share_rate", "engagement", "shares", "comments", "reactions"}
)

PRESETS: dict[str, dict] = {
    "viral_tuyet_doi": {"label": "Viral tuyệt đối", "rules": {"views": 50_000}},
    "vuot_tep_follower": {"label": "Vượt tệp follower", "rules": {"ratio_follow": 5}},
    "bung_no_manh": {"label": "Bùng nổ mạnh", "rules": {"ratio_follow": 10}},
    "no_bat_thuong": {
        "label": "Nổ bất thường của kênh (khuyên dùng)",
        "rules": {"ratio_median": 3},
    },
    "dang_chia_se": {
        "label": "Nội dung đáng chia sẻ",
        "rules": {"share_rate": 0.01, "views": 10_000},
    },
    "tu_nhap": {"label": "Tự nhập", "rules": {}},
}


def compute_metrics(videos: list[Video]) -> None:
    """Gán ratio_follow, ratio_median, engagement, share_rate cho từng video, tại chỗ.

    Trung vị view được tính riêng cho từng page_url trong đợt quét. Cần ít nhất
    MIN_VIDEOS_FOR_MEDIAN video có view; nếu không thì ratio_median = None và ghi chú vào video.
    Mọi phép chia đều an toàn với None và 0: mẫu số bằng 0 hoặc thiếu thì kết quả là None.
    """
    groups: dict[str, list[Video]] = {}
    for video in videos:
        groups.setdefault(video.page_url, []).append(video)

    for group in groups.values():
        views = [v.views for v in group if v.views is not None]
        if len(views) < MIN_VIDEOS_FOR_MEDIAN:
            median: float | None = None
            note: str | None = NOTE_TOO_FEW_FOR_MEDIAN
        else:
            median = statistics.median(views)
            note = NOTE_ZERO_MEDIAN if median == 0 else None

        for video in group:
            video.ratio_follow = _safe_div(video.views, video.page_followers)
            video.ratio_median = _safe_div(video.views, median)
            video.engagement = _engagement(video)
            video.share_rate = _safe_div(video.shares, video.views)
            video.notes = [n for n in video.notes if n not in _MEDIAN_NOTES]
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


def passes(video: Video, rules: dict) -> bool:
    """True nếu video đạt TẤT CẢ ngưỡng trong rules (AND).

    Chỉ số của video bằng None thì không đạt. Ngưỡng None nghĩa là không đặt điều kiện.
    Chỉ số không có trong RULE_METRICS là lỗi lập trình nên báo ValueError.
    """
    for metric, minimum in rules.items():
        if metric not in RULE_METRICS:
            raise ValueError(f"Chỉ số lọc không hợp lệ: {metric}")
        if minimum is None:
            continue
        value = getattr(video, metric)
        if value is None or value < minimum:
            return False
    return True


def apply_filter(videos: list[Video], rules: dict) -> list[Video]:
    """Giữ lại các video đạt rules, giữ nguyên thứ tự."""
    return [video for video in videos if passes(video, rules)]


def page_allowed(followers: int | None, min_followers: int) -> bool:
    """Page có đủ quy mô để quét không (PLAN §5, bộ lọc quy mô page).

    min_followers <= 0 thì tắt bộ lọc. Không đọc được số follower (None) thì cho quét và ghi cảnh báo.
    """
    if min_followers <= 0:
        return True
    if followers is None:
        log.warning("Không đọc được số follower của page; vẫn đưa vào quét")
        return True
    return followers >= min_followers


def formula_score(
    ratio_median: float | None,
    replicable_p: float | None,
    hook_strength: int | None,
    relevant_p: float | None,
    weights: dict,
) -> float:
    """Điểm công thức 0–100 theo PLAN §6:

        diem = w_ratio·min(ratio_median/cap, 1) + w_replicable·replicable_p
               + w_hook·(hook_strength/2) + w_relevant·relevant_p

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
    )
    return float(min(max(score, 0.0), 100.0))


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)
