"""Offline tests cho ngưỡng lượt xem, tương tác và Điểm công thức."""
from __future__ import annotations


import pytest

from filters import (
    NOTE_TOO_FEW_FOR_MEDIAN,
    NOTE_ZERO_MEDIAN,
    apply_filter,
    compute_metrics,
    formula_score,
    passes,
)
from models import Video

# Trọng số như settings["score_weights"] mặc định.
WEIGHTS = {"ratio_median": 40, "ratio_median_cap": 5, "replicable": 25, "hook_strength": 20, "relevant": 15, "jev_viral": 20}


def make_video(video_id: str = "v1", page_url: str = "https://www.facebook.com/page1", **fields) -> Video:
    return Video(video_id=video_id, url=f"https://www.facebook.com/reel/{video_id}", page_url=page_url, **fields)


def make_page(page_url: str, views: list[int | None]) -> list[Video]:
    return [make_video(f"{page_url}-{i}", page_url=page_url, views=v) for i, v in enumerate(views)]


# ---------------------------------------------------------------- compute_metrics


def test_ratio_follow_engagement_and_share_rate() -> None:
    video = make_video(views=10_000, page_followers=2_000, reactions=300, comments=150, shares=50)
    compute_metrics([video])
    assert video.ratio_follow == pytest.approx(5.0)
    assert video.engagement == pytest.approx(500 / 10_000)
    assert video.share_rate == pytest.approx(50 / 10_000)


def test_ratio_median_needs_five_videos_with_views() -> None:
    videos = make_page("p", [100, 200, 300, 400])
    videos.append(make_video("no-views", page_url="p", views=None))  # không tính vì thiếu view
    compute_metrics(videos)
    for video in videos:
        assert video.ratio_median is None
        assert NOTE_TOO_FEW_FOR_MEDIAN in video.notes


def test_ratio_median_computed_with_exactly_five_videos() -> None:
    videos = make_page("p", [100, 200, 300, 400, 500])  # trung vị = 300
    compute_metrics(videos)
    assert videos[4].ratio_median == pytest.approx(500 / 300)
    assert videos[0].ratio_median == pytest.approx(100 / 300)
    assert all(NOTE_TOO_FEW_FOR_MEDIAN not in v.notes for v in videos)


def test_ratio_median_is_computed_per_page() -> None:
    page_a = make_page("a", [100] * 5)
    page_b = make_page("b", [1000] * 5)
    compute_metrics(page_a + page_b)
    # Nếu tính chung cả hai page thì trung vị là 550 và kết quả sai.
    assert all(v.ratio_median == pytest.approx(1.0) for v in page_a + page_b)


def test_notes_are_not_duplicated_and_cleared_when_enough_videos() -> None:
    videos = make_page("p", [100, 200, 300, 400])
    compute_metrics(videos)
    compute_metrics(videos)
    assert videos[0].notes.count(NOTE_TOO_FEW_FOR_MEDIAN) == 1

    videos.append(make_video("v5", page_url="p", views=500))
    compute_metrics(videos)
    assert all(NOTE_TOO_FEW_FOR_MEDIAN not in v.notes for v in videos)
    assert videos[-1].ratio_median == pytest.approx(500 / 300)


@pytest.mark.parametrize("followers", [0, None])
def test_ratio_follow_is_none_without_positive_followers(followers: int | None) -> None:
    video = make_video(views=1_000, page_followers=followers)
    compute_metrics([video])
    assert video.ratio_follow is None


def test_zero_views_gives_zero_ratio_follow_and_no_division_by_zero() -> None:
    video = make_video(views=0, page_followers=1_000, reactions=0, comments=0, shares=0)
    compute_metrics([video])
    assert video.ratio_follow == 0.0
    assert video.engagement is None
    assert video.share_rate is None


def test_zero_median_leaves_ratio_median_empty_with_note() -> None:
    videos = make_page("p", [0, 0, 0, 0, 100])  # trung vị = 0
    compute_metrics(videos)
    assert all(v.ratio_median is None for v in videos)
    assert all(NOTE_ZERO_MEDIAN in v.notes for v in videos)


def test_missing_views_leaves_view_based_metrics_empty() -> None:
    video = make_video(views=None, page_followers=1_000, reactions=1, comments=1, shares=1)
    compute_metrics([video])
    assert video.ratio_follow is None
    assert video.engagement is None
    assert video.share_rate is None


def test_engagement_needs_every_component() -> None:
    video = make_video(views=1_000, reactions=10, comments=None, shares=5)
    compute_metrics([video])
    assert video.engagement is None
    assert video.share_rate == pytest.approx(5 / 1_000)


def test_compute_metrics_on_empty_list_is_noop() -> None:
    compute_metrics([])


@pytest.mark.parametrize("views,expected", [(50_000, True), (49_999, False), (None, False)])
def test_view_threshold_inclusive_and_unknown_fails(views, expected):
    assert passes(make_video(views=views), min_views=50_000) is expected


def test_zero_threshold_disables_filter():
    assert passes(make_video(views=None), min_views=0)
    assert passes(make_video(format="post", interactions=None), min_interactions=0)


def test_apply_filter_preserves_order():
    videos = [make_video("a", views=60_000), make_video("b", views=1), make_video("c", views=50_000)]
    assert [v.video_id for v in apply_filter(videos, min_views=50_000)] == ["a", "c"]


@pytest.mark.parametrize("views,followers,match_all,expected", [
    (60_000, 10_000, True, True),     # cả hai đạt
    (60_000, 20_000, True, False),    # ratio 3 < 5
    (60_000, 20_000, False, True),    # OR: views đạt
    (10_000, 1_000, True, False),     # views thấp
    (10_000, 1_000, False, True),     # OR: ratio 10 đạt
    (10_000, 3_000, False, False),    # cả hai trượt
    (60_000, None, True, False),      # follower chưa biết: ratio trượt
    (60_000, None, False, True),      # OR: views vẫn đạt
    (None, 1_000, False, False),      # views chưa biết trượt cả hai
])
def test_views_and_ratio_conditions(views, followers, match_all, expected):
    video = make_video(views=views, page_followers=followers)
    assert passes(video, min_views=50_000, min_ratio_follow=5, match_all=match_all) is expected


def test_ratio_threshold_inclusive_and_alone():
    assert passes(make_video(views=5_000, page_followers=1_000), min_ratio_follow=5)
    assert not passes(make_video(views=4_999, page_followers=1_000), min_ratio_follow=5)
    assert passes(make_video(views=1, page_followers=None), match_all=False)  # không điều kiện nào bật


def test_post_ignores_ratio():
    post = make_video(format="post", views=None, page_followers=None, interactions=250)
    assert passes(post, min_interactions=200, min_ratio_follow=10)
    assert not passes(make_video(format="post", interactions=10), min_interactions=200, min_ratio_follow=10, match_all=False)


@pytest.mark.parametrize("kind,expected", [("video", True), ("reel", False),
                                          ("video_live", True), ("reel_live", False)])
def test_length_limits_are_independent_and_live_uses_base(kind, expected):
    video = make_video(format=kind, duration_s=120, views=100_000)
    limits = {"video": (60, None), "reel": (None, 90)}
    assert passes(video, min_views=50_000, match_all=False, length_limits=limits) is expected


def test_length_boundaries_order_counts_and_unknown_note():
    videos = [make_video(str(index), format="reel", duration_s=duration)
              for index, duration in enumerate((30, 90, 91, None, 29))]
    notes = []
    kept = apply_filter(videos, length_limits={"reel": (30, 90)}, length_notes=notes)
    assert [video.video_id for video in kept] == ["0", "1", "3"]
    assert notes == ["Bỏ 1 reel dài hơn 90 giây.", "Bỏ 1 reel ngắn hơn 30 giây."]
    assert any("Chưa biết thời lượng" in note for note in videos[3].notes)
    apply_filter(videos, length_limits={"reel": (30, 90)})
    assert sum("Chưa biết thời lượng" in note for note in videos[3].notes) == 1


def test_no_length_limits_preserve_defaults_and_posts_ignore_them():
    video = make_video(duration_s=None)
    assert apply_filter([video]) == [video]
    assert video.notes == []
    post = make_video(format="post", duration_s=1, interactions=200)
    assert passes(post, min_interactions=200, length_limits={"post": (180, None), "video": (180, None)})
    assert post.notes == []


@pytest.mark.parametrize("parts,total", [((10, 20, 30), 60), ((10, None, 5), 15), ((None, None, None), None), ((0, None, None), 0)])
def test_interactions_sum_known_components(parts, total):
    video = make_video(format="post", reactions=parts[0], comments=parts[1], shares=parts[2])
    compute_metrics([video])
    assert video.interactions == total


@pytest.mark.parametrize("interactions,expected", [(200, True), (199, False), (None, False)])
def test_post_threshold_uses_interactions(interactions, expected):
    assert passes(make_video(format="post", views=100_000, interactions=interactions), min_interactions=200) is expected


def test_post_median_uses_interactions_per_page():
    posts = [make_video(str(i), format="post", reactions=i * 100) for i in range(1, 6)]
    compute_metrics(posts)
    assert posts[-1].ratio_median == pytest.approx(500 / 300)


def test_jev_viral_adds_weighted_score():
    assert formula_score(None, None, None, None, WEIGHTS, 0.5) == 10
    assert formula_score(None, None, None, None, WEIGHTS, 2) == 20


# ---------------------------------------------------------------- formula_score


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((5.0, 1.0, 2, 1.0), 100.0),  # tối đa
        ((0.0, 0.0, 0, 0.0), 0.0),  # tối thiểu
        ((None, None, None, None), 0.0),  # None tính bằng 0
        ((5.0, 0.0, 0, 0.0), 40.0),  # đúng ngưỡng cap: đủ 40
        ((4.99, 0.0, 0, 0.0), 39.92),  # sát dưới cap
        ((10.0, 0.0, 0, 0.0), 40.0),  # vượt cap vẫn chỉ 40
        ((2.5, 0.0, 0, 0.0), 20.0),
        ((None, 1.0, 0, 0.0), 25.0),
        ((None, 0.0, 1, 0.0), 10.0),  # hook 1/2 -> 10
        ((None, 0.0, 2, 0.0), 20.0),  # hook 2/2 -> 20
        ((None, 0.0, 0, 0.5), 7.5),
        ((3.0, 1.0, 1, 1.0), 74.0),  # ví dụ: 24 + 25 + 10 + 15
    ],
)
def test_formula_score_matches_plan_formula(args: tuple, expected: float) -> None:
    assert formula_score(*args, WEIGHTS) == pytest.approx(expected)


def test_formula_score_clamps_total_to_100() -> None:
    heavy = {"ratio_median": 60, "ratio_median_cap": 5, "replicable": 25, "hook_strength": 20, "relevant": 15}
    assert formula_score(5.0, 1.0, 2, 1.0, heavy) == 100.0


def test_formula_score_clamps_out_of_range_inputs() -> None:
    assert formula_score(-3.0, None, None, None, WEIGHTS) == 0.0
    assert formula_score(None, 1.7, 0, -0.2, WEIGHTS) == pytest.approx(25.0)
    assert formula_score(None, 0.0, 5, 0.0, WEIGHTS) == pytest.approx(20.0)


def test_formula_score_uses_custom_weights() -> None:
    custom = {"ratio_median": 50, "ratio_median_cap": 10, "replicable": 20, "hook_strength": 20, "relevant": 10}
    # 50·(5/10) + 20·1 + 20·1 + 10·1 = 75
    assert formula_score(5.0, 1.0, 2, 1.0, custom) == pytest.approx(75.0)


def test_formula_score_rejects_non_positive_cap() -> None:
    bad = {**WEIGHTS, "ratio_median_cap": 0}
    with pytest.raises(ValueError):
        formula_score(3.0, 1.0, 1, 1.0, bad)
