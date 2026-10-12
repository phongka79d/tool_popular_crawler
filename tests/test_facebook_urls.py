"""Offline regression tests for Facebook page tab URL normalization."""
from __future__ import annotations

import pytest

from collectors.facebook import tab_url


@pytest.mark.parametrize("tab", ["reels", "videos"])
@pytest.mark.parametrize(
    "page_url",
    [
        "https://www.facebook.com/PageX",
        "https://www.facebook.com/PageX/",
        "https://www.facebook.com/PageX/?ref=bookmarks#about",
        "https://m.facebook.com/PageX/",
        "https://web.facebook.com/PageX?ref=share#about",
        "http://mbasic.facebook.com/PageX/",
        "https://facebook.com/pg/PageX",
        "https://www.facebook.com/pg/PageX/?ref=bookmarks#about",
    ],
)
def test_vanity_tab_url(page_url: str, tab: str) -> None:
    assert tab_url(page_url, tab) == f"https://www.facebook.com/PageX/{tab}/"


@pytest.mark.parametrize(
    ("tab", "sk"),
    [("reels", "reels_tab"), ("videos", "videos")],
)
@pytest.mark.parametrize(
    "page_url",
    [
        "https://www.facebook.com/profile.php?id=123456",
        "https://www.facebook.com/profile.php?ref=share&id=123456&sk=about#intro",
        "https://m.facebook.com/profile.php?id=123456&ref=bookmarks",
        "https://www.facebook.com/people/Page-Name/123456",
        "https://www.facebook.com/people/Page-Name/123456/?ref=share#about",
    ],
)
def test_profile_tab_url(page_url: str, tab: str, sk: str) -> None:
    assert tab_url(page_url, tab) == f"https://www.facebook.com/profile.php?id=123456&sk={sk}"
