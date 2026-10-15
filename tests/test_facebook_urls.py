"""Offline regression tests for Facebook page tab URL normalization."""
from __future__ import annotations

import pytest

from backend.collectors.facebook import page_url_problem, tab_url

VANITY_URLS = [
    "https://www.facebook.com/PageX",
    "https://www.facebook.com/PageX/",
    "https://www.facebook.com/PageX/?ref=bookmarks#about",
    "https://m.facebook.com/PageX/",
    "https://web.facebook.com/PageX?ref=share#about",
    "http://mbasic.facebook.com/PageX/",
    "https://facebook.com/pg/PageX",
    "https://www.facebook.com/pg/PageX/?ref=bookmarks#about",
]
PROFILE_URLS = [
    "https://www.facebook.com/profile.php?id=123456",
    "https://www.facebook.com/profile.php?ref=share&id=123456&sk=about#intro",
    "https://m.facebook.com/profile.php?id=123456&ref=bookmarks",
    "https://www.facebook.com/people/Page-Name/123456",
    "https://www.facebook.com/people/Page-Name/123456/?ref=share#about",
]


@pytest.mark.parametrize("page_url", VANITY_URLS + PROFILE_URLS)
def test_every_scannable_page_url_is_accepted(page_url: str) -> None:
    assert page_url_problem(page_url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com/groups/1528487012172019?locale=vi_VN",
        "https://www.facebook.com/reel/123",
        "https://www.facebook.com/watch/?v=123",
        "https://www.facebook.com/share/r/abc/",
        "https://www.facebook.com/PageX/videos/123/",
        "https://www.facebook.com/profile.php",
        "https://www.facebook.com/",
        "https://www.youtube.com/@kenh",
        "facebook.com/PageX",
    ],
)
def test_non_page_links_are_rejected_with_reason(url: str) -> None:
    assert page_url_problem(url)


@pytest.mark.parametrize("tab", ["reels", "videos"])
@pytest.mark.parametrize("page_url", VANITY_URLS)
def test_vanity_tab_url(page_url: str, tab: str) -> None:
    assert tab_url(page_url, tab) == f"https://www.facebook.com/PageX/{tab}/"


@pytest.mark.parametrize(
    ("tab", "sk"),
    [("reels", "reels_tab"), ("videos", "videos")],
)
@pytest.mark.parametrize("page_url", PROFILE_URLS)
def test_profile_tab_url(page_url: str, tab: str, sk: str) -> None:
    assert tab_url(page_url, tab) == f"https://www.facebook.com/profile.php?id=123456&sk={sk}"


@pytest.mark.parametrize("page_url", VANITY_URLS)
def test_vanity_posts_tab_opens_main_feed(page_url: str) -> None:
    assert tab_url(page_url, "posts") == "https://www.facebook.com/PageX/"


@pytest.mark.parametrize("page_url", PROFILE_URLS)
def test_profile_posts_tab_opens_main_feed_without_sk(page_url: str) -> None:
    assert tab_url(page_url, "posts") == "https://www.facebook.com/profile.php?id=123456"


@pytest.mark.parametrize("page_url", VANITY_URLS + PROFILE_URLS)
@pytest.mark.parametrize("tab", ["reels", "videos", "posts"])
def test_capture_tool_uses_scanner_tab_urls(page_url: str, tab: str) -> None:
    from tools.capture_feed import tab_url as capture_tab_url

    assert capture_tab_url(page_url, tab) == tab_url(page_url, tab)
