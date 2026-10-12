"""Offline tests cho filters: compute_metrics, PRESETS (AND), page_allowed, formula_score."""
from __future__ import annotations

import logging

import pytest

from filters import (
    NOTE_TOO_FEW_FOR_MEDIAN,
    NOTE_ZERO_MEDIAN,
    PRESETS,
    RULE_METRICS,
    apply_filter,
    compute_metrics,
    formula_score,
    page_allowed,
    passes,
)
from models import Video

# Trọng số như settings["score_weights"] mặc định.
WEIGHTS = {"ratio_median": 40, "ratio_median_cap": 5, "replicable": 25, "hook_strength": 20, "relevant": 15}
PRESET_KEYS_WITH_RULES = [key for key, preset in PRESETS.items() if preset["rules"]]


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
    assert NOTE_TOO_FEW_FOR_MEDIAN == "Chưa đủ 5 video để tính trung vị"


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


# ---------------------------------------------------------------- PRESETS and passes


def test_presets_have_label_and_known_metrics() -> None:
    assert set(PRESETS) == {
        "viral_tuyet_doi",
        "vuot_tep_follower",
        "bung_no_manh",
        "no_bat_thuong",
        "dang_chia_se",
        "tu_nhap",
    }
    for preset in PRESETS.values():
        assert preset["label"]
        assert set(preset["rules"]) <= RULE_METRICS


def test_recommended_preset_is_ratio_median_three() -> None:
    assert PRESETS["no_bat_thuong"]["rules"] == {"ratio_median": 3}


def _video_meeting(rules: dict) -> Video:
    video = make_video()
    for metric, minimum in rules.items():
        setattr(video, metric, minimum)
    return video


@pytest.mark.parametrize("key", PRESET_KEYS_WITH_RULES)
def test_preset_passes_when_every_rule_is_met(key: str) -> None:
    rules = PRESETS[key]["rules"]
    assert passes(_video_meeting(rules), rules)


@pytest.mark.parametrize("key", PRESET_KEYS_WITH_RULES)
def test_preset_fails_when_any_single_rule_is_missed(key: str) -> None:
    rules = PRESETS[key]["rules"]
    for missed in rules:
        video = _video_meeting(rules)
        setattr(video, missed, rules[missed] * 0.99)
        assert not passes(video, rules), f"{key} phải loại khi thiếu {missed}"


def test_viral_tuyet_doi_threshold_is_inclusive() -> None:
    rules = PRESETS["viral_tuyet_doi"]["rules"]
    assert passes(make_video(views=50_000), rules) is True
    assert passes(make_video(views=49_999), rules) is False


def test_vuot_tep_follower_threshold_is_inclusive() -> None:
    rules = PRESETS["vuot_tep_follower"]["rules"]
    assert passes(make_video(ratio_follow=5.0), rules) is True
    assert passes(make_video(ratio_follow=4.99), rules) is False


def test_bung_no_manh_threshold_is_inclusive() -> None:
    rules = PRESETS["bung_no_manh"]["rules"]
    assert passes(make_video(ratio_follow=10.0), rules) is True
    assert passes(make_video(ratio_follow=9.99), rules) is False


def test_no_bat_thuong_threshold_is_inclusive() -> None:
    rules = PRESETS["no_bat_thuong"]["rules"]
    assert passes(make_video(ratio_median=3.0), rules) is True
    assert passes(make_video(ratio_median=2.99), rules) is False


def test_dang_chia_se_requires_both_share_rate_and_views() -> None:
    rules = PRESETS["dang_chia_se"]["rules"]
    assert passes(make_video(share_rate=0.02, views=5_000), rules) is False
    assert passes(make_video(share_rate=0.005, views=20_000), rules) is False
    assert passes(make_video(share_rate=0.01, views=10_000), rules) is True


def test_tu_nhap_has_no_preset_threshold() -> None:
    assert PRESETS["tu_nhap"]["rules"] == {}
    assert passes(make_video(views=0), PRESETS["tu_nhap"]["rules"])


def test_user_rules_combine_with_and() -> None:
    rules = {"views": 1_000, "ratio_median": 3}
    assert passes(make_video(views=2_000, ratio_median=3.5), rules) is True
    assert passes(make_video(views=2_000, ratio_median=2.5), rules) is False
    assert passes(make_video(views=500, ratio_median=5.0), rules) is False


def test_missing_metric_fails_the_rule() -> None:
    video = make_video(views=60_000, ratio_median=None)
    assert passes(video, {"views": 50_000, "ratio_median": 3}) is False


def test_none_threshold_means_no_condition() -> None:
    assert passes(make_video(views=None), {"views": None}) is True


def test_unknown_metric_raises() -> None:
    with pytest.raises(ValueError):
        passes(make_video(views=1), {"likes": 1})


def test_apply_filter_keeps_only_passing_videos_in_order() -> None:
    videos = [
        make_video("a", views=60_000),
        make_video("b", views=1_000),
        make_video("c", views=50_000),
    ]
    kept = apply_filter(videos, PRESETS["viral_tuyet_doi"]["rules"])
    assert [v.video_id for v in kept] == ["a", "c"]


# ---------------------------------------------------------------- page_allowed


def test_page_allowed_min_zero_disables_the_filter() -> None:
    assert page_allowed(0, 0) is True
    assert page_allowed(5, 0) is True
    assert page_allowed(None, 0) is True


def test_page_allowed_threshold_is_inclusive() -> None:
    assert page_allowed(100_000, 100_000) is True
    assert page_allowed(99_999, 100_000) is False


def test_page_allowed_unknown_followers_is_allowed_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="filters"):
        assert page_allowed(None, 100_000) is True
    assert any(record.levelno == logging.WARNING for record in caplog.records)


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
