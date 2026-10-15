"""Offline tests for collectors/graphql.py, using the synthetic fixtures in tests/fixtures/."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from backend.collectors import graphql as gql

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_TEXT = (FIXTURES / "graphql_sample.txt").read_text(encoding="utf-8")
PAGE_HTML = (FIXTURES / "initial_page.html").read_text(encoding="utf-8")

REEL = {
    "video_id": "700000000000001",
    "url": "https://www.facebook.com/reel/700000000000001",
    "posted_at": 1790600000,
    "caption": "3 sai lầm khi bán thuốc không kê đơn khiến khách không quay lại",
    "views": 152300,
    "reactions": 4120,
    "comments": 348,
    "shares": 1520,
    "duration_s": 27.48,
    "format": "reel",
    "is_live": False,
}

VIDEO = {
    "video_id": "700000000000002",
    "url": "https://www.facebook.com/TramDuocMau/videos/700000000000002/",
    "posted_at": 1790500000,
    "caption": "Cách đọc nhãn thuốc trước khi tư vấn cho khách lớn tuổi",
    "views": 88210,
    "reactions": 2431,
    "comments": 23,
    "shares": 57,
    "duration_s": 61.437,
    "format": "video",
    "is_live": False,
}

HTML_REEL = {
    "video_id": "700000000000011",
    "url": "https://www.facebook.com/reel/700000000000011",
    "posted_at": 1790200000,
    "caption": "Mẹo bảo quản thuốc nhỏ mắt sau khi mở nắp",
    "views": 6540,
    "reactions": 96,
    "comments": 12,
    "shares": 4,
    "duration_s": 19.96,
    "format": "reel",
    "is_live": False,
}

HTML_VIDEO = {
    "video_id": "700000000000013",
    "url": "https://www.facebook.com/TramDuocMau/videos/700000000000013/",
    "posted_at": 1790100000,
    "caption": "Hướng dẫn pha dung dịch sát khuẩn đúng nồng độ",
    "views": 2051000,
    "reactions": 455,
    "comments": 9,
    "shares": 3000,
    "duration_s": 73.0,
    "format": "video",
    "is_live": False,
    "_approx_counts": {"shares"},
}


def _sample_stories() -> list[dict]:
    return gql.extract_stories(gql.split_json_values(SAMPLE_TEXT))


def _story(stories: list[dict], post_id: str) -> dict:
    return next(story for story in stories if story["post_id"] == post_id)


def _video_story(
    *,
    post_id: str = "700000000000100",
    url: str | None = None,
    feedback: dict | None = None,
    media: str = "Video",
    media_extra: dict | None = None,
) -> dict:
    media_node = {"__typename": media, "id": "800000000000100", **(media_extra or {})}
    story: dict = {
        "__typename": "Story",
        "post_id": post_id,
        "creation_time": 1790000000,
        "attachments": [{"styles": {"attachment": {"media": media_node}}}],
    }
    if url is not None:
        story["permalink_url"] = url
    if feedback is not None:
        story["comet_sections"] = {
            "feedback": {
                "story": {
                    "story_ufi_container": {
                        "story": {
                            "feedback_context": {
                                "feedback_target_with_context": {
                                    "comet_ufi_summary_and_actions_renderer": {"feedback": feedback}
                                }
                            }
                        }
                    }
                }
            }
        }
    return story


def _reactions_of(feedback: dict) -> int | None:
    return gql.flatten(_video_story(feedback=feedback))["reactions"]


def test_split_json_values_splits_concatenated_objects_and_skips_garbage():
    text = 'for (;;);{"a": 1}{"b": [2, 3]}\n {"c": "}{"}'
    assert gql.split_json_values(text) == [{"a": 1}, {"b": [2, 3]}, {"c": "}{"}]


def test_split_json_values_drops_scalars_and_truncated_values():
    assert gql.split_json_values('"x" 42 {"a": 1') == []


def test_split_fixture_response_into_four_objects():
    values = gql.split_json_values(SAMPLE_TEXT)
    assert len(values) == 4
    assert all(isinstance(value, dict) for value in values)


def test_extract_stories_keeps_first_per_post_id_and_skips_nested_stories():
    ids = [story["post_id"] for story in _sample_stories()]
    # 001 appears again later with stale counts; 005 is only nested inside share 004.
    assert ids == ["700000000000001", "700000000000002", "700000000000003", "700000000000004"]


def test_extract_stories_dedups_numeric_and_string_post_ids():
    first = {"__typename": "Story", "post_id": 42, "creation_time": 1}
    second = {"__typename": "Story", "post_id": "42", "creation_time": 2}
    assert gql.extract_stories([first, [second]]) == [first]


def test_flatten_reel_returns_exact_fields():
    assert gql.flatten(_story(_sample_stories(), "700000000000001")) == REEL


def test_flatten_video_returns_exact_fields():
    assert gql.flatten(_story(_sample_stories(), "700000000000002")) == VIDEO


def test_flatten_keeps_photo_post_and_share_with_own_message():
    photo = gql.flatten(_story(_sample_stories(), "700000000000003"))
    assert photo == {
        "video_id": "700000000000003",
        "url": "https://www.facebook.com/TramDuocMau/posts/pfbid0SyntheticPhotoPost",
        "posted_at": 1790400000,
        "caption": "Lịch khám sức khỏe đầu năm, mời quý khách đặt hẹn",
        "views": None, "reactions": 40, "comments": None, "shares": 3,
        "duration_s": None, "format": "post",
        "is_live": False, "image_urls": ["https://scontent.example.invalid/synthetic-photo-3.jpg"],
    }
    share = gql.flatten(_story(_sample_stories(), "700000000000004"))
    assert share["format"] == "post"
    assert share["caption"] == "Chia sẻ từ trang khác"


def test_flatten_drops_pure_reshare_without_own_message():
    story = _story(_sample_stories(), "700000000000004")
    del story["comet_sections"]["content"]["story"]["message"]
    assert gql.flatten(story) is None


@pytest.mark.parametrize("media", [None, "Photo", "ExternalUrl"])
def test_flatten_keeps_text_photo_and_link_posts(media):
    story = _video_story(media=media)
    story["message"] = {"text": "Nội dung của trang"}
    if media is None:
        story["attachments"] = []
    record = gql.flatten(story)
    assert record["format"] == "post"
    assert record["caption"] == "Nội dung của trang"
    assert record["url"] == "https://www.facebook.com/700000000000100"
    assert record["views"] is None and record["duration_s"] is None
    assert record["reactions"] is None and record["comments"] is None and record["shares"] is None


@pytest.mark.parametrize("media", [None, "Photo"])
def test_flatten_drops_post_without_text_but_keeps_captionless_video(media):
    post = _video_story(media=media)
    post.pop("message", None)
    if media is None:
        post["attachments"] = []
    assert gql.flatten(post) is None
    video = _video_story()
    video.pop("message", None)
    assert gql.flatten(video)["format"] in {"reel", "video"}


def test_flatten_requires_post_id():
    assert gql.flatten({"__typename": "Story", "attachments": []}) is None


def test_parse_graphql_response_returns_each_post_or_video_once():
    videos = gql.parse_graphql_response(SAMPLE_TEXT)
    assert [video["video_id"] for video in videos] == [
        "700000000000001", "700000000000002", "700000000000003", "700000000000004",
    ]
    assert videos[0]["views"] == 152300  # the stale duplicate (999) must not win


@pytest.mark.parametrize(
    ("feedback", "expected"),
    [
        (
            {
                "video_view_count": 10,
                "video_view_count_renderer": {"feedback": {"video_view_count": 20, "play_count": 30}},
            },
            10,
        ),
        ({"video_view_count_renderer": {"feedback": {"video_view_count": 20, "play_count": 30}}}, 20),
        ({"video_view_count_renderer": {"feedback": {"play_count": 30}}}, 30),
        ({"reaction_count": {"count": 1}}, None),
    ],
)
def test_views_fallback_order(feedback, expected):
    assert gql.flatten(_video_story(feedback=feedback))["views"] == expected


def test_views_order_comes_from_config():
    paths = dataclasses.replace(
        gql.load_paths(),
        views=[["video_view_count_renderer", "feedback", "play_count"], ["video_view_count"]],
    )
    feedback = {"video_view_count": 10, "video_view_count_renderer": {"feedback": {"play_count": 30}}}
    assert gql.flatten(_video_story(feedback=feedback), paths)["views"] == 30


@pytest.mark.parametrize(
    ("edge", "expected"),
    [
        ({"reaction_count": 7, "node": {"id": "1635855486666999", "localized_name": "Thích"}}, 7),
        ({"reaction_count": 3, "node": {"id": "0", "localized_name": "Phẫn nộ"}}, 3),
        ({"reaction_count": 9, "node": {"id": "0", "localized_name": "Lạ"}}, None),
    ],
)
def test_reactions_from_top_reactions_by_id_then_name(edge, expected):
    assert _reactions_of({"top_reactions": {"edges": [edge]}}) == expected


def test_reactions_total_beats_top_reaction_sum():
    feedback = {
        "reaction_count": {"count": 50},
        "top_reactions": {"edges": [{"reaction_count": 10, "node": {"id": "1635855486666999"}}]},
    }
    assert _reactions_of(feedback) == 50


def test_reactions_empty_edges_mean_zero_and_missing_means_none():
    assert _reactions_of({"top_reactions": {"edges": []}}) == 0
    assert _reactions_of({}) is None


def test_shares_prefer_logged_in_then_logged_out_then_localized():
    def shares(feedback: dict) -> int | None:
        return gql.flatten(_video_story(feedback=feedback))["shares"]

    logged_in = {
        "adaptive_ufi_action_renderers": [{"feedback": {"share_count": {"count": 5}}}],
        "share_count": {"count": 9},
    }
    assert shares(logged_in) == 5
    assert shares({"share_count": {"count": 9}}) == 9
    assert shares({"i18n_share_count": "1,2 Tr"}) == 1200000
    assert shares({}) is None


def test_video_without_feedback_keeps_unknown_counts_as_none():
    result = gql.flatten(_video_story(feedback=None, url="https://www.facebook.com/x/videos/1/"))
    assert result is not None
    assert result["views"] is None
    assert result["reactions"] is None
    assert result["comments"] is None
    assert result["shares"] is None


def test_duration_prefers_milliseconds_then_seconds():
    ms = gql.flatten(_video_story(media_extra={"playable_duration_in_ms": 61437, "length_in_second": 61}))
    seconds = gql.flatten(_video_story(media_extra={"length_in_second": 73}))
    none = gql.flatten(_video_story())
    assert ms["duration_s"] == 61.437
    assert seconds["duration_s"] == 73.0
    assert none["duration_s"] is None


def test_format_is_reel_only_when_permalink_has_reel_marker():
    reel = gql.flatten(_video_story(url="https://www.facebook.com/reel/1"))
    video = gql.flatten(_video_story(url="https://www.facebook.com/x/videos/1/"))
    assert reel["format"] == "reel"
    assert video["format"] == "video"


def test_missing_permalink_uses_fallback_url_and_video_format():
    result = gql.flatten(_video_story(post_id="700000000000100"))
    assert result["url"] == "https://www.facebook.com/watch/?v=700000000000100"
    assert result["format"] == "video"


def test_reels_tab_story_takes_counters_from_deferred_fragments_by_node_id():
    """Reels tab: the Story holds media and rounded views; @defer payloads with the same node id
    hold comments, shares and reactions. post_id may differ from the reel's media id."""
    story = {
        "__typename": "Story", "id": "UzpfSTpSZWVsOjE=", "post_id": "700000000000300",
        "creation_time": 1790700000, "message": {"text": "Mẹo bảo quản thuốc mùa nồm"},
        "attachments": [{"media": {
            "__typename": "Video", "id": "800000000000300", "length_in_second": 31.5,
            "play_count_reduced": "3,8K",
            "permalink_url": "https://www.facebook.com/reel/800000000000300/",
        }}],
    }
    feed = {"data": {"node": {"aggregated_fb_shorts": {"edges": [{"profile_reel_node": {"node": story}}]}}}}
    comments_fragment = {"label": "FBReelsFeedbackBar$defer", "data": {
        "id": "UzpfSTpSZWVsOjE=", "feedback": {"total_comment_count": 92, "share_count_reduced": "16"},
    }}
    reactions_fragment = {"label": "FBUnifiedVideoFeedbackBar$defer", "data": {
        "id": "UzpfSTpSZWVsOjE=",
        "fb_reel_react_button": {"story": {"feedback": {"unified_reactors": {"count": 691}}}},
    }}
    other = {"data": {"id": "unrelated", "feedback": {"total_comment_count": 1}}}
    text = "\n".join(json.dumps(v) for v in (feed, other, comments_fragment, reactions_fragment))
    assert gql.parse_graphql_response(text) == [{
        "video_id": "700000000000300",
        "url": "https://www.facebook.com/reel/800000000000300/",
        "posted_at": 1790700000,
        "caption": "Mẹo bảo quản thuốc mùa nồm",
        "views": 3800,
        "reactions": 691,
        "comments": 92,
        "shares": 16,
        "duration_s": 31.5,
        "format": "reel",
        "is_live": False,
        "_approx_counts": {"views", "shares"},
    }]


def test_parse_initial_html_reads_only_data_sjs_blobs():
    assert gql.parse_initial_html(PAGE_HTML) == [HTML_REEL, {
        "video_id": "700000000000012",
        "url": "https://www.facebook.com/TramDuocMau/posts/pfbid0SyntheticPhotoHtml",
        "posted_at": 1790150000,
        "caption": "Thông báo lịch nghỉ lễ của nhà thuốc",
        "views": None, "reactions": 21, "comments": None, "shares": 1,
        "duration_s": None, "format": "post",
        "is_live": False, "image_urls": ["https://scontent.example.invalid/synthetic-photo-12.jpg"],
    }, HTML_VIDEO]


def test_parse_page_header_reads_page_node_from_initial_html():
    assert gql.parse_page_header(PAGE_HTML) == {"name": "Trạm Dược Mẫu", "followers": 18420}


def test_parse_page_header_without_page_node_returns_empty_values():
    assert gql.parse_page_header("<html></html>") == {"name": "", "followers": None}


def test_parse_page_header_reads_new_style_page_name_from_header_renderer_user():
    # Page kiểu mới có __typename "User", giống mọi tài khoản khác trong HTML (tác giả bài, người xem).
    # Chỉ user của profile_header_renderer là page; viewer là tài khoản phụ đang đăng nhập.
    payload = json.dumps({"data": {
        "feed": {"owning_profile": {"__typename": "User", "name": "Trang Khác"}},
        "user": {"profile_header_renderer": {
            "__typename": "XFBProfileEntityConvergenceHeaderRenderer",
            "viewer": {"actor": {"__typename": "User", "name": "Tài khoản phụ"}},
            "user": {"__isProfile": "User", "name": "Nhà Thuốc Mẫu"},
        }},
    }}, ensure_ascii=False)
    assert gql.parse_page_header(payload) == {"name": "Nhà Thuốc Mẫu", "followers": None}


@pytest.mark.parametrize(("text", "count"), [
    ("1,1\u00a0triệu người theo dõi", 1_100_000),
    ("680K người theo dõi", 680_000),
    ("202K người theo dõi", 202_000),
    ("111K người theo dõi", 111_000),
    ("111 N người theo dõi", 111_000),
    ("1.1M followers", 1_100_000),
    ("2,3 tr người theo dõi", 2_300_000),
    ("12.345 followers", 12_345),
])
@pytest.mark.parametrize("typename", ["User", None])
def test_page_header_social_context_live_shapes(text, count, typename):
    profile = {
        "name": "Trang Mẫu",
        "profile_social_context": {"content": [
            {"text": {"text": "93 đang theo dõi"}, "uri": "https://example.invalid/following/"},
            {"text": {"text": text}, "uri": "https://example.invalid/followers/"},
        ]},
    }
    if typename:
        profile["__typename"] = typename
    html = '<script data-sjs>' + json.dumps({"data": {"user": profile}}) + '</script>'
    assert gql.parse_page_header(html) == {"name": "Trang Mẫu", "followers": count}


def test_page_header_followers_link_without_localized_label():
    payload = {"data": {"user": {"name": "Trang Mẫu", "profile_social_context": {"content": [
        {"text": {"text": "45K lượt thích"}, "uri": "https://example.invalid/likes/"},
        {"text": {"text": "202K"}, "uri": "https://example.invalid/followers/?locale=en"},
    ]}}}}
    assert gql.parse_page_header(json.dumps(payload))["followers"] == 202_000


@pytest.mark.parametrize("exact", [
    {"follower_count": 202_345}, {"followers_count": "202345"},
    {"followers": {"count": 202_345}}, {"subscribers": {"count": 202_345}},
])
def test_page_header_exact_count_overrides_earlier_rounded_text(exact):
    values = [
        {"profile_social_context": {"content": [{"text": {"text": "202K followers"}}]}},
        {"__typename": "Page", "name": "Trang Mẫu", **exact},
    ]
    assert gql.parse_page_header(json.dumps(values))["followers"] == 202_345


def test_page_header_renderer_reads_user_count_not_viewer_or_story():
    payload = {"data": {
        "story": {"__typename": "Story", "author": {"__typename": "Page", "followers_count": 999}},
        "header": {
            "__typename": "XFBProfileEntityConvergenceHeaderRenderer",
            "viewer": {"actor": {"__typename": "Page", "followers_count": 888}},
            "user": {"name": "Trang Mẫu", "follower_count": 123},
        },
    }}
    assert gql.parse_page_header(json.dumps(payload)) == {"name": "Trang Mẫu", "followers": 123}


def test_page_header_does_not_use_following_likes_or_facepile_counts():
    payload = {"profile_social_context": {
        "facepile_profile_count": 42,
        "content": [{"text": {"text": "45K lượt thích"}}, {"text": {"text": "93 đang theo dõi"}}],
    }}
    assert gql.parse_page_header(json.dumps(payload))["followers"] is None


def test_page_header_reads_deferred_graphql_fragment():
    body = 'for (;;);' + json.dumps({"data": {"name": "Trang Mẫu", "profile_social_context": {
        "content": [{"text": {"text": "680K người theo dõi"}}],
    }}})
    assert gql.parse_page_header(body) == {"name": "Trang Mẫu", "followers": 680_000}


def _channel_tile(video_id: str, url: str) -> dict:
    """One Videos-tab tile as Facebook sends it (trimmed real capture): the video node is not a Story."""
    return {"node": {"id": video_id, "channel_tab_thumbnail_renderer": {
        "__typename": "ChannelTabVideoThumbnailWithReactionsRenderer",
        "video": {
            "id": video_id,
            "canonical_uri_with_fallback": url,
            "publish_time": 1791527855,
            "play_count": 1512408,
            "post_play_count": 540335,
            "savable_title": {"text": "Mẹ ăn gì để con khỏe?"},
            "video_thumbnail_overlays_renderer": {
                "__typename": "VideoHomeVideoThumbnailOverlaysDefaultRenderer",
                "video": {"playable_duration_in_ms": 101471, "playable_duration": 102, "id": video_id},
            },
            "feedback": {"id": "ZmVlZGJhY2s6MQ==", "reaction_count": {"count": 691}, "i18n_reaction_count": "691"},
        },
    }}}


def test_videos_tab_tiles_become_records_with_play_count_as_views():
    payload = json.dumps({"data": {"node": {"__typename": "VirtualVideosChannel", "all_videos": {"edges": [
        _channel_tile("1098563256480613", "https://www.facebook.com/Trang/videos/1098563256480613/"),
        _channel_tile("2947279425652566", "https://www.facebook.com/reel/2947279425652566/"),
    ]}}}}, ensure_ascii=False)

    videos = gql.parse_graphql_response(payload)

    assert [(v["video_id"], v["format"]) for v in videos] == [
        ("1098563256480613", "video"), ("2947279425652566", "reel")]
    assert videos[0] == {
        "video_id": "1098563256480613",
        "url": "https://www.facebook.com/Trang/videos/1098563256480613/",
        "posted_at": 1791527855,
        "caption": "Mẹ ăn gì để con khỏe?",
        "views": 1512408,  # play_count (tổng lượt xem), không phải post_play_count
        "reactions": 691,
        "comments": None,  # tile không có: để yt-dlp bổ sung
        "shares": None,
        "duration_s": pytest.approx(101.471),
        "format": "video",
        "is_live": False,
    }


def test_recent_videos_tab_detects_replay_for_exclusion():
    # Sanitized Pharmacity /videos/ HTML: a three-hour broadcast replay and a reel.
    replay = _channel_tile("1001", "https://www.facebook.com/Example/videos/1001/")
    video = replay["node"]["channel_tab_thumbnail_renderer"]["video"]
    video["savable_title"] = {"text": "Example broadcast replay"}
    video["publish_time"] = 1791777617
    video["video_thumbnail_overlays_renderer"]["video"].update({
        "id": "1001", "playable_duration_in_ms": 10819930,
        "playable_duration": 10820, "broadcast_status": "VOD_READY",
        "is_live_streaming": False,
    })
    reel = _channel_tile("1002", "https://www.facebook.com/reel/1002/")
    reel["node"]["channel_tab_thumbnail_renderer"]["video"]["savable_title"] = {"text": "Example reel"}
    html = '<script data-sjs>' + json.dumps({
        "data": {"node": {"__typename": "VirtualVideosChannel",
                          "all_videos": {"edges": [replay, reel]}}},
    }) + "</script>"

    records = gql.parse_initial_html(html)

    assert [(row["video_id"], row["format"], row["is_live"]) for row in records] == [
        ("1001", "video", True), ("1002", "reel", False),
    ]
    assert records[0]["posted_at"] == 1791777617
    assert records[0]["duration_s"] == pytest.approx(10819.93)


def test_config_loads_and_every_alternative_is_a_non_empty_path():
    def alternatives(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from alternatives(item)
        elif isinstance(value, list) and value and all(isinstance(x, list) for x in value):
            yield from value

    data = dataclasses.asdict(gql.load_paths())
    checked = list(alternatives(data))
    assert checked
    for path in checked:
        assert path, "a path must not be empty"
        assert all(isinstance(key, (str, int)) for key in path)


@pytest.mark.parametrize("status,streaming,expected", [
    (None, False, False), ("", False, False), ("VOD_READY", False, True),
    ("LIVE", False, True), (None, True, True),
])
@pytest.mark.parametrize("reel", [False, True])
def test_live_status_from_story_and_channel_shapes(status, streaming, expected, reel):
    url = "https://www.facebook.com/reel/123/" if reel else "https://www.facebook.com/Page/videos/123/"
    media = {"__typename": "Video", "broadcast_status": status, "is_live_streaming": streaming}
    story = {"__typename": "Story", "post_id": "123", "permalink_url": url,
             "attachments": [{"media": media}]}
    tile = _channel_tile("123", url)
    video = tile["node"]["channel_tab_thumbnail_renderer"]["video"]
    video["video_thumbnail_overlays_renderer"]["video"].update(media)
    for record in (gql.flatten(story), gql.flatten_channel_video(video)):
        assert record["is_live"] is expected
        assert record["format"] == ("reel" if reel else "video")


def test_live_status_missing_is_false():
    assert gql.flatten(_video_story())["is_live"] is False
    assert gql.flatten_channel_video({"id": "123"})["is_live"] is False


def test_tile_live_evidence_enriches_existing_story():
    story = _video_story(post_id="123")
    tile = _channel_tile("123", "https://www.facebook.com/Page/videos/123/")
    tile["node"]["channel_tab_thumbnail_renderer"]["video"]["video_thumbnail_overlays_renderer"]["video"]["broadcast_status"] = "VOD_READY"
    records = gql.parse_graphql_response(json.dumps([story, tile]))
    assert len(records) == 1
    assert records[0]["is_live"] is True


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_counters_replace_reduced_counters_across_batches(reverse):
    from backend.collectors.facebook import _Collector
    story = _video_story(url="https://www.facebook.com/reel/123", feedback={
        "play_count_reduced": "454K", "i18n_reaction_count": "1K",
        "total_comment_count": "2K", "share_count_reduced": 3000,
    })
    tile = _channel_tile("123", "https://www.facebook.com/reel/123")
    video = tile["node"]["channel_tab_thumbnail_renderer"]["video"]
    video["play_count"] = 454108
    video["feedback"] = {"reaction_count": {"count": 1008},
                         "total_comment_count": 2011, "share_count": {"count": 3007}}
    batches = [gql.parse_graphql_response(json.dumps(story)), gql.parse_graphql_response(json.dumps(tile))]
    collector = _Collector({"reel"}, 10000, 100)
    for batch in reversed(batches) if reverse else batches:
        collector.add(batch, "reel")
    row, = collector.videos()
    assert tuple(row[field] for field in ("views", "reactions", "comments", "shares")) == (454108, 1008, 2011, 3007)
    assert "_approx_counts" not in row


def test_counter_alternatives_choose_exact_over_earlier_display_value():
    record = gql.flatten(_video_story(feedback={"video_view_count": "454K", "play_count": 454108}))
    assert record["views"] == 454108
    assert "views" not in record.get("_approx_counts", ())


def test_story_tile_merge_prefers_exact_counters():
    story = _video_story(post_id="123", feedback={"play_count_reduced": "454K"})
    tile = _channel_tile("123", "https://www.facebook.com/reel/123")
    records = gql.parse_graphql_response(json.dumps([story, tile]))
    assert len(records) == 1
    assert records[0]["views"] == 1512408
    assert "views" not in records[0].get("_approx_counts", ())


def test_display_reaction_edges_are_marked_approximate():
    record = gql.flatten(_video_story(feedback={
        "top_reactions": {"edges": [{"reaction_count": "1K", "node": {"id": "1635855486666999"}}]},
    }))
    assert record["reactions"] == 1000
    assert "reactions" in record["_approx_counts"]
