"""Test offline cho collectors.cookies và collectors.ytdlp: không mở trình duyệt, không gọi mạng."""
from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

import config
from collectors import cookies, ytdlp
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


def test_fetch_metadata_passes_netscape_cookiefile(monkeypatch, tmp_path):
    cookie_path = tmp_path / "fb.txt"
    cookies.write_netscape([_c_user(), _xs()], cookie_path)
    monkeypatch.setattr(config, "COOKIE_FILE", cookie_path)
    seen = _install_fake_ydl(monkeypatch, info={})

    ytdlp.fetch_metadata("https://www.facebook.com/reel/1")

    assert seen["opts"]["cookiefile"] == str(cookie_path)


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
