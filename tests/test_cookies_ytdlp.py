"""Test offline cho collectors.cookies và collectors.ytdlp: không mở trình duyệt, không gọi mạng."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

import config
from collectors import cookies, facebook, ytdlp
from models import Video


@pytest.fixture(autouse=True)
def _isolate_cookie_file(tmp_path, monkeypatch):
    # Không đụng tới data/fb_cookies.txt thật.
    monkeypatch.setattr(config, "COOKIE_FILE", tmp_path / "missing-cookies.txt")


def _c_user(**overrides) -> dict:
    base = {
        "name": "c_user", "value": "100012345", "domain": ".facebook.com", "path": "/",
        "expires": 1_800_000_000.0, "httpOnly": False, "secure": True, "sameSite": "None",
    }
    base.update(overrides)
    return base


def _xs(**overrides) -> dict:
    base = {
        "name": "xs", "value": "41%3Aabc", "domain": ".facebook.com", "path": "/",
        "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax",
    }
    base.update(overrides)
    return base


# ---------- cookies ----------

def test_write_netscape_layout_and_httponly_prefix(tmp_path):
    path = tmp_path / "data" / "fb.txt"  # thư mục cha chưa tồn tại
    cookies.write_netscape([_c_user(), _xs()], path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert ".facebook.com\tTRUE\t/\tTRUE\t1800000000\tc_user\t100012345" in lines
    assert "#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\txs\t41%3Aabc" in lines


def test_write_read_roundtrip(tmp_path):
    path = tmp_path / "fb.txt"
    cookies.write_netscape([_c_user(), _xs()], path)

    loaded = cookies.read_netscape(path)

    assert [
        (c["name"], c["value"], c["domain"], c["path"], c["secure"], c["httpOnly"]) for c in loaded
    ] == [
        ("c_user", "100012345", ".facebook.com", "/", True, False),
        ("xs", "41%3Aabc", ".facebook.com", "/", True, True),
    ]
    assert loaded[0]["expires"] == 1_800_000_000
    assert loaded[1]["expires"] == -1  # cookie phiên


def test_write_skips_entries_that_would_corrupt_the_file(tmp_path):
    path = tmp_path / "fb.txt"
    cookies.write_netscape(
        [_c_user(), {"name": "", "value": "x", "domain": ".facebook.com"}, _xs(value="a\tb")],
        path,
    )

    assert [c["name"] for c in cookies.read_netscape(path)] == ["c_user"]


def test_is_netscape_file_accepts_written_export(tmp_path):
    path = tmp_path / "fb.txt"
    cookies.write_netscape([_c_user(), _xs()], path)

    assert cookies.is_netscape_file(path) is True


def test_is_netscape_file_accepts_export_without_header(tmp_path):
    path = tmp_path / "fb.txt"
    path.write_text(".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t1\n", encoding="utf-8")

    assert cookies.is_netscape_file(path) is True


def test_is_netscape_file_accepts_httponly_first_line(tmp_path):
    path = tmp_path / "fb.txt"
    path.write_text("#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\txs\tv\n", encoding="utf-8")

    assert cookies.is_netscape_file(path) is True


@pytest.mark.parametrize(
    "content",
    [
        '[{"name": "c_user", "value": "1"}]',
        '{"c_user": "1"}',
        "đây chỉ là chữ thường\n",
        ".facebook.com\tTRUE\t/\n",
    ],
)
def test_is_netscape_file_rejects_other_formats(tmp_path, content):
    path = tmp_path / "fb.txt"
    path.write_text(content, encoding="utf-8")

    assert cookies.is_netscape_file(path) is False


def test_is_netscape_file_false_when_missing(tmp_path):
    assert cookies.is_netscape_file(tmp_path / "không-có.txt") is False


def test_has_login_cookies_requires_both_c_user_and_xs():
    assert cookies.has_login_cookies([_c_user(), _xs()]) is True
    assert cookies.has_login_cookies([_c_user()]) is False
    assert cookies.has_login_cookies([_xs()]) is False
    assert cookies.has_login_cookies([_c_user(), _xs(value="")]) is False
    assert cookies.has_login_cookies([]) is False


@pytest.mark.parametrize(
    "same_site, expected",
    [("no_restriction", "None"), ("lax", "Lax"), ("strict", "Strict"),
     ("unspecified", "Lax"), (None, "Lax")],
)
def test_convert_cookie_editor_maps_fields(same_site, expected):
    source = {
        "name": "xs", "value": "test-session", "domain": ".facebook.com", "path": "/videos",
        "expirationDate": 1_800_000_000.5, "secure": True, "httpOnly": True,
        "sameSite": same_site, "hostOnly": False, "storeId": "0", "id": 1,
    }
    assert cookies.convert_cookie_editor([source]) == [{
        "name": "xs", "value": "test-session", "domain": ".facebook.com", "path": "/videos",
        "expires": 1_800_000_000.5, "secure": True, "httpOnly": True, "sameSite": expected,
    }]
    assert source["expirationDate"] == 1_800_000_000.5


def test_convert_cookie_editor_session_defaults_and_missing_fields():
    result = cookies.convert_cookie_editor([
        {"name": "xs", "value": "", "domain": ".facebook.com", "session": True,
         "expirationDate": 1_800_000_000},
        {"name": "c_user", "value": "test-user", "domain": ".facebook.com"},
        {"name": "missing-value"}, {"value": "missing-name"}, None,
    ])
    assert len(result) == 2
    assert all(c["expires"] == -1 for c in result)
    assert all(c["path"] == "/" and c["sameSite"] == "Lax" for c in result)
    assert all(c["secure"] is False and c["httpOnly"] is False for c in result)
    assert result[0]["value"] == ""


@pytest.mark.parametrize("export_format", ["cookie_editor", "edit_this_cookie", "netscape"])
def test_load_cookie_file_supported_formats(tmp_path, export_format):
    path = tmp_path / "export.txt"
    if export_format == "netscape":
        cookies.write_netscape([_c_user(), _xs()], path)
    else:
        data = [
            {"name": "c_user", "value": "100012345", "domain": ".facebook.com", "path": "/",
             "expirationDate": 1_800_000_000, "secure": True, "httpOnly": False,
             "sameSite": "no_restriction", "session": False},
            {"name": "xs", "value": "41%3Aabc", "domain": ".facebook.com", "path": "/",
             "expirationDate": 1_800_000_000, "secure": True, "httpOnly": True,
             "sameSite": "lax", "session": True},
        ]
        if export_format == "edit_this_cookie":
            for index, cookie in enumerate(data):
                cookie.update({"id": index, "storeId": "0", "hostOnly": False})
        path.write_text(json.dumps(data), encoding="utf-8")
    loaded = cookies.load_cookie_file(path)
    assert cookies.has_login_cookies(loaded)
    assert loaded[0]["expires"] == 1_800_000_000
    assert loaded[1]["expires"] == -1
    assert loaded[1]["httpOnly"] is True
    assert all(c["secure"] and c["path"] == "/" and c["domain"] == ".facebook.com" for c in loaded)
    assert [c["value"] for c in loaded] == ["100012345", "41%3Aabc"]
    if export_format != "netscape":
        assert [c["sameSite"] for c in loaded] == ["None", "Lax"]


@pytest.mark.parametrize("text", ['{"c_user": "test"}', "không phải cookie"])
def test_load_cookie_file_rejects_unknown_format(tmp_path, text):
    path = tmp_path / "invalid.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        cookies.load_cookie_file(path)


@pytest.mark.parametrize("valid_login", [True, False])
def test_import_cookies_adds_verifies_and_exports(tmp_path, monkeypatch, valid_login):
    path = tmp_path / "import.txt"
    imported = [_c_user(), _xs()] if valid_login else [_c_user()]
    cookies.write_netscape(imported, path)
    calls = []
    current = cookies.load_cookie_file(path)
    output = tmp_path / "saved.txt"

    class FakeContext:
        pages: list = []

        def add_cookies(self, values):
            calls.append(("add", values))

        def cookies(self, urls):
            calls.append(("verify", urls))
            return current

    @contextlib.contextmanager
    def persistent_context(hidden):
        assert hidden is True
        yield FakeContext()

    monkeypatch.setattr(facebook, "_save_user_agent", lambda page: None)
    monkeypatch.setattr(facebook, "_first_page", lambda ctx: None)

    monkeypatch.setattr(facebook, "_persistent_context", persistent_context)
    monkeypatch.setattr(facebook, "write_netscape", lambda values: cookies.write_netscape(values, output))
    assert facebook.import_cookies(path) is valid_login
    assert calls == [("add", current), ("verify", list(facebook.FB_COOKIE_URLS))]
    assert output.exists() is valid_login
    if valid_login:
        assert cookies.read_netscape(output) == current


def test_import_cookies_invalid_file_does_not_open_browser(tmp_path, monkeypatch):
    def unexpected_browser(*args, **kwargs):
        raise AssertionError("Không được mở trình duyệt cho tệp sai")

    monkeypatch.setattr(facebook, "_persistent_context", unexpected_browser)
    assert facebook.import_cookies(tmp_path / "missing.txt") is False


@pytest.mark.parametrize("timeout", [True, False])
@pytest.mark.parametrize(
    "batches, max_rounds, expected_rounds",
    # Tab trống dừng ngay sau vòng cuộn đầu; tab có video dừng sau stall_rounds vòng không có video mới.
    [([[], [], []], 10, 1), ([["1"], [], ["2"], [], []], 10, 5),
     ([["1"], ["2"], ["3"], ["4"]], 3, 3)],
)
def test_scan_page_expect_response_timeout_stall_and_round_cap(
    monkeypatch, timeout, batches, max_rounds, expected_rounds,
):
    actions = []

    class FakePage:
        def __init__(self):
            self.rounds = 0
            self.waiting = False
            self.mouse = SimpleNamespace(wheel=self.wheel, move=lambda x, y, steps: None)
            self.listener = None

        def on(self, event, handler):
            assert event == "response"
            self.listener = handler

        def remove_listener(self, event, handler):
            assert event == "response" and handler is self.listener
            self.listener = None

        def content(self):
            return ""

        @contextlib.contextmanager
        def expect_response(self, predicate, timeout):
            assert timeout == facebook.RESPONSE_WAIT_MS
            assert predicate(SimpleNamespace(url="https://www.facebook.com/api/graphql/"))
            assert not predicate(SimpleNamespace(url="https://www.facebook.com/other"))
            actions.append("expect")
            self.waiting = True
            try:
                yield
            finally:
                self.waiting = False
            if timeout_enabled:
                raise facebook.PlaywrightTimeoutError("Hết thời gian chờ")

        def evaluate(self, script):
            assert self.waiting
            return True  # đã tới gần cuối trang: mỗi vòng chỉ một nấc lăn

        def wait_for_timeout(self, ms):
            assert self.waiting

        def wheel(self, x, y):
            assert self.waiting and x == 0 and y > 0
            actions.append("wheel")
            batch = batches[self.rounds]
            self.rounds += 1
            if batch:
                self.listener(SimpleNamespace(
                    url="https://www.facebook.com/api/graphql/", status=200,
                    text=lambda: json.dumps(batch),
                ))

    timeout_enabled = timeout
    page = FakePage()
    scanner = facebook.FacebookScanner(settings={"scan": {
        "max_scroll_rounds": max_rounds, "stall_rounds": 2,
    }})
    scanner._page = page
    monkeypatch.setattr(scanner, "_open", lambda url: None)
    monkeypatch.setattr(scanner, "_raise_if_blocked", lambda: None)
    monkeypatch.setattr(scanner, "_export_cookies", lambda: None)
    monkeypatch.setattr(facebook, "_human_pause", lambda *args: None)
    monkeypatch.setattr(facebook.graphql, "parse_initial_html", lambda html: [])
    monkeypatch.setattr(facebook.graphql, "parse_graphql_response", lambda body: [
        {"video_id": video_id, "format": "reel"} for video_id in json.loads(body)
    ])
    videos = scanner.scan_page("https://www.facebook.com/TestPage", 30, {"reel"}, 100)
    assert page.rounds == expected_rounds
    assert actions == ["expect", "wheel"] * expected_rounds
    assert page.listener is None
    assert [video["video_id"] for video in videos] == [
        video_id for batch in batches[:expected_rounds] for video_id in batch
    ]


def test_scan_page_posts_uses_main_feed_and_ignores_videos(monkeypatch):
    opened, progress = [], []
    page = SimpleNamespace(
        on=lambda *args: None, remove_listener=lambda *args: None,
        content=lambda: "feed",
    )
    scanner = facebook.FacebookScanner(settings={"scan": {
        "max_scroll_rounds": 1, "stall_rounds": 2,
    }})
    scanner._page = page
    monkeypatch.setattr(scanner, "_open", opened.append)
    monkeypatch.setattr(scanner, "_scroll_once", lambda: None)
    monkeypatch.setattr(scanner, "_raise_if_blocked", lambda: None)
    monkeypatch.setattr(scanner, "_export_cookies", lambda: None)
    monkeypatch.setattr(facebook, "_human_pause", lambda *args: None)
    post = {"video_id": "post-1", "format": "post", "caption": "Nội dung của trang"}
    monkeypatch.setattr(facebook.graphql, "parse_initial_html", lambda html: [
        {"video_id": "video-1", "format": "video"}, post,
        {"video_id": "reel-1", "format": "reel"},
    ])
    assert scanner.scan_page(
        "https://www.facebook.com/TestPage/?ref=share", 30, {"post"}, 100,
        on_progress=progress.append,
    ) == [post]
    assert opened == ["https://www.facebook.com/TestPage/"]
    assert any("Bài đăng" in message for message in progress)
    assert all("video" not in message for message in progress)


def test_scan_page_posts_scrolls_past_old_pinned_post(monkeypatch):
    monkeypatch.setattr(facebook, "is_older_than", lambda timestamp, days: timestamp == 1)
    pending_listener = {}
    page = SimpleNamespace(
        on=lambda event, handler: pending_listener.update(handler=handler),
        remove_listener=lambda *args: None, content=lambda: "feed",
    )
    scanner = facebook.FacebookScanner(settings={"scan": {
        "max_scroll_rounds": 10, "stall_rounds": 4,
    }})
    scanner._page = page
    monkeypatch.setattr(scanner, "_open", lambda url: None)
    monkeypatch.setattr(scanner, "_raise_if_blocked", lambda: None)
    monkeypatch.setattr(scanner, "_export_cookies", lambda: None)
    monkeypatch.setattr(facebook, "_human_pause", lambda *args: None)
    pinned = {"video_id": "pinned", "format": "post", "posted_at": 1}
    recent = {"video_id": "recent", "format": "post", "posted_at": 2}
    monkeypatch.setattr(facebook.graphql, "parse_initial_html", lambda html: [pinned])
    monkeypatch.setattr(facebook.graphql, "parse_graphql_response", json.loads)
    batches = iter([
        [recent],
        [{"video_id": "old-2", "format": "post", "posted_at": 1}],
        [{"video_id": "old-3", "format": "post", "posted_at": 1}],
    ])
    rounds = []

    def scroll():
        rounds.append(1)
        body = json.dumps(next(batches))
        pending_listener["handler"](SimpleNamespace(
            status=200, url="https://www.facebook.com/api/graphql/", text=lambda: body,
        ))

    monkeypatch.setattr(scanner, "_scroll_once", scroll)
    assert scanner.scan_page("https://www.facebook.com/TestPage", 30, {"post"}, 100) == [recent]
    assert len(rounds) == 3


def test_post_collector_ignores_single_old_pinned_post_and_duplicate_old_posts(monkeypatch):
    monkeypatch.setattr(facebook, "is_older_than", lambda timestamp, days: timestamp == 1)
    collector = facebook._Collector({"post"}, 30, 100)
    old = {"video_id": "pinned", "format": "post", "posted_at": 1}
    recent = {"video_id": "recent", "format": "post", "posted_at": 2}
    collector.add([old], "post")
    assert not collector.done("post")
    collector.add([old, recent, {"video_id": "old-video", "format": "video", "posted_at": 1}], "post")
    assert not collector.done("post")
    assert collector.videos() == [recent]
    assert collector.items_seen == 3
    collector.add([{"video_id": "old-2", "format": "post", "posted_at": 1}], "post")
    assert not collector.done("post")
    collector.add([{"video_id": "old-3", "format": "post", "posted_at": 1}], "post")
    assert collector.done("post")


def test_video_collector_still_stops_at_first_old_video(monkeypatch):
    monkeypatch.setattr(facebook, "is_older_than", lambda timestamp, days: True)
    collector = facebook._Collector({"video"}, 30, 100)
    collector.add([{"video_id": "old", "format": "video", "posted_at": 1}], "video")
    assert collector.done("video")


def test_post_collector_counts_only_posts():
    collector = facebook._Collector({"post"}, 30, 100)
    collector.add([{"video_id": "v", "format": "video"}, {"video_id": "r", "format": "reel"}], "post")
    assert collector.items_seen == 0 and collector.count() == 0


# ---------- yt-dlp helpers ----------

def _install_fake_ydl(monkeypatch, info=None, on_download=None) -> dict:
    """Thay yt_dlp.YoutubeDL bằng bản giả; ghi lại opts và URL. Không có mạng."""
    seen: dict = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            seen["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def extract_info(self, url, download=False):
            seen["url"] = url
            seen["download"] = download
            return dict(info or {})

        def download(self, urls):
            seen["urls"] = list(urls)
            if on_download is None:
                return 0
            return on_download(seen["opts"], urls)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return seen


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.facebook.com/reel/123456789", "https://m.facebook.com/watch/?v=123456789"),
        ("https://www.facebook.com/reel/123456789/?s=abc", "https://m.facebook.com/watch/?v=123456789"),
        ("https://web.facebook.com/reel/42", "https://m.facebook.com/watch/?v=42"),
        ("https://www.facebook.com/watch/?v=5", "https://www.facebook.com/watch/?v=5"),
        ("https://www.facebook.com/PageX/videos/777/", "https://www.facebook.com/PageX/videos/777/"),
        ("https://www.facebook.com/PageX/reels/", "https://www.facebook.com/PageX/reels/"),
    ],
)
def test_reel_url_rewritten_to_watch_url(url, expected):
    assert ytdlp._to_watch_url(url) == expected


def test_fetch_metadata_uses_watch_url_without_download(monkeypatch):
    seen = _install_fake_ydl(monkeypatch, info={
        "view_count": 10, "comment_count": 2, "repost_count": 1, "timestamp": 1_700_000_000,
        "duration": 31.5, "description": "Mô tả", "like_count": 99,
    })

    result = ytdlp.fetch_metadata("https://www.facebook.com/reel/777")

    assert seen["url"] == "https://m.facebook.com/watch/?v=777"
    assert seen["download"] is False
    assert seen["opts"]["skip_download"] is True
    assert "cookiefile" not in seen["opts"]  # chưa có tệp cookie
    assert result == {
        "view_count": 10, "comment_count": 2, "repost_count": 1, "timestamp": 1_700_000_000,
        "duration": 31.5, "description": "Mô tả",
    }


@pytest.mark.parametrize("public", [True, False])
def test_fetch_metadata_tries_anonymous_before_account(monkeypatch, tmp_path, public):
    cookie_path = tmp_path / "fb.txt"
    cookies.write_netscape([_c_user(), _xs()], cookie_path)
    ua_path = tmp_path / "ua.txt"
    ua_path.write_text("Mozilla/5.0 Edg/141\n", encoding="utf-8")
    monkeypatch.setattr(config, "COOKIE_FILE", cookie_path)
    monkeypatch.setattr(config, "BROWSER_UA_FILE", ua_path)
    attempts = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def extract_info(self, url, download=False):
            attempts.append(self.opts)
            if "cookiefile" not in self.opts and not public:
                raise ytdlp.YoutubeDLError("login required")
            return {"view_count": 5}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    assert ytdlp.fetch_metadata("https://www.facebook.com/reel/1")["view_count"] == 5
    assert "cookiefile" not in attempts[0]
    if public:
        assert len(attempts) == 1  # video công khai: tài khoản không bị dùng
    else:
        assert len(attempts) == 2
        assert attempts[1]["cookiefile"] == str(cookie_path)
        assert attempts[1]["http_headers"] == {"User-Agent": "Mozilla/5.0 Edg/141"}


def test_fetch_metadata_ignores_non_netscape_cookie_file(monkeypatch, tmp_path):
    cookie_path = tmp_path / "fb.txt"
    cookie_path.write_text('[{"name": "c_user", "value": "1"}]', encoding="utf-8")
    monkeypatch.setattr(config, "COOKIE_FILE", cookie_path)
    seen = _install_fake_ydl(monkeypatch, info={})

    ytdlp.fetch_metadata("https://www.facebook.com/reel/1")

    assert "cookiefile" not in seen["opts"]


# ---------- fill_missing ----------

FULL_INFO = {
    "view_count": 1200, "comment_count": 30, "repost_count": 4, "timestamp": 1_700_000_000,
    "duration": 45, "description": "Caption từ yt-dlp", "like_count": 999,
}


def _video(**overrides) -> Video:
    base = {"video_id": "1", "url": "https://www.facebook.com/reel/1", "page_url": "https://www.facebook.com/p"}
    base.update(overrides)
    return Video(**base)


def test_fill_missing_sets_empty_fields_from_metadata(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url):
        calls.append(url)
        return dict(FULL_INFO)

    monkeypatch.setattr(ytdlp, "fetch_metadata", fake_fetch)
    video = _video(views=500)

    ytdlp.fill_missing(video)

    assert calls == ["https://www.facebook.com/reel/1"]
    assert video.views == 500
    assert video.comments == 30
    assert video.shares == 4
    assert video.posted_at == 1_700_000_000
    assert video.duration_s == 45.0 and isinstance(video.duration_s, float)
    assert video.caption == "Caption từ yt-dlp"
    assert video.reactions is None  # like_count không phải tổng cảm xúc


def test_fill_missing_keeps_existing_values_when_fetching(monkeypatch):
    monkeypatch.setattr(ytdlp, "fetch_metadata", lambda url: dict(FULL_INFO))
    video = _video(views=500, comments=7, caption="Có sẵn", shares=None, posted_at=None, duration_s=None)

    ytdlp.fill_missing(video)

    assert (video.views, video.comments, video.caption) == (500, 7, "Có sẵn")
    assert (video.shares, video.posted_at, video.duration_s) == (4, 1_700_000_000, 45.0)


def test_fill_missing_skips_fetch_when_nothing_is_missing(monkeypatch):
    def must_not_call(url):
        raise AssertionError("Không được gọi yt-dlp khi đã đủ dữ liệu")

    monkeypatch.setattr(ytdlp, "fetch_metadata", must_not_call)
    video = _video(views=1, comments=2, shares=3, posted_at=4, duration_s=5.0, caption="x")

    ytdlp.fill_missing(video)

    assert (video.views, video.comments, video.shares, video.posted_at, video.duration_s, video.caption) == (
        1, 2, 3, 4, 5.0, "x",
    )


def test_fill_missing_ignores_absent_upstream_values(monkeypatch):
    monkeypatch.setattr(ytdlp, "fetch_metadata", lambda url: {"view_count": None, "description": ""})
    video = _video()

    ytdlp.fill_missing(video)

    assert video.views is None
    assert video.caption == ""


def test_fill_missing_survives_ytdlp_error(monkeypatch):
    def boom(url):
        raise DownloadError("video không khả dụng")

    monkeypatch.setattr(ytdlp, "fetch_metadata", boom)
    video = _video()

    ytdlp.fill_missing(video)  # không được ném lỗi

    assert video.views is None
    assert video.caption == ""


# ---------- download_audio ----------

def _write_audio(opts, ext: str = "m4a", data: bytes = b"\x00audio", fail: Exception | None = None) -> int:
    Path(opts["outtmpl"].replace("%(ext)s", ext)).write_bytes(data)
    if fail is not None:
        raise fail
    return 0


def test_download_audio_returns_file_on_success(monkeypatch, tmp_path):
    seen = _install_fake_ydl(monkeypatch, on_download=lambda opts, urls: _write_audio(opts))
    out_dir = tmp_path / "audio"  # chưa tồn tại: hàm phải tự tạo

    out = ytdlp.download_audio("https://www.facebook.com/reel/9", out_dir)

    assert out is not None
    assert out.exists() and out.suffix == ".m4a" and out.parent == out_dir
    assert seen["urls"] == ["https://m.facebook.com/watch/?v=9"]
    assert seen["opts"]["format"] == "bestaudio/best"
    assert seen["opts"]["noplaylist"] is True


def test_download_audio_counts_existing_file_even_if_ytdlp_raises(monkeypatch, tmp_path):
    fail = DownloadError("lỗi phụ đề")
    _install_fake_ydl(monkeypatch, on_download=lambda opts, urls: _write_audio(opts, fail=fail))

    out = ytdlp.download_audio("https://www.facebook.com/reel/9", tmp_path)

    assert out is not None and out.exists()


def test_download_audio_none_when_ytdlp_raises_without_file(monkeypatch, tmp_path):
    def boom(opts, urls):
        raise DownloadError("không tải được")

    _install_fake_ydl(monkeypatch, on_download=boom)

    assert ytdlp.download_audio("https://www.facebook.com/reel/9", tmp_path) is None


@pytest.mark.parametrize("ext, data", [("m4a.part", b"dang tai"), ("m4a", b"")])
def test_download_audio_ignores_partial_or_empty_files(monkeypatch, tmp_path, ext, data):
    _install_fake_ydl(monkeypatch, on_download=lambda opts, urls: _write_audio(opts, ext=ext, data=data))

    assert ytdlp.download_audio("https://www.facebook.com/reel/9", tmp_path) is None


def test_download_audio_first_seconds_falls_back_to_full_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp, "_cookie_opts", lambda: {})
    attempts = []

    def ranged_fails(opts, urls):
        attempts.append("ranged" if "download_ranges" in opts else "full")
        if "download_ranges" in opts:
            raise DownloadError("ffmpeg không cắt được đoạn đầu")
        return _write_audio(opts)

    _install_fake_ydl(monkeypatch, on_download=ranged_fails)

    out = ytdlp.download_audio("https://www.facebook.com/p/videos/9", tmp_path, first_seconds=600, ffmpeg="ffmpeg")

    assert out is not None and out.exists()
    assert attempts == ["ranged", "full"]
