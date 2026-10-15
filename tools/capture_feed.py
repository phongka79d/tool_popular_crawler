"""Capture a Facebook page's Reels, Videos or main posts feed as offline fixtures.

Run from the repository root::

    .venv/Scripts/python tools/capture_feed.py https://www.facebook.com/TenTrang --tab reels
    .venv/Scripts/python tools/capture_feed.py https://www.facebook.com/profile.php?id=1 --tab videos --scrolls 20

A visible browser opens with the same profile that CollectBrowser uses (config.PROFILE_DIR).
Log in there first if the tab needs it. The script scrolls the tab and writes
tests/fixtures/live/<slug>_<tab>_<timestamp>/ containing:

- graphql_NNN.txt: body of each successful /api/graphql/ response, in arrival order
- initial_page.html: HTML of the first page load (its data-sjs blobs feed parse_initial_html)
- index.json: capture metadata; request URLs are stored without their query strings

WARNING: captured files can contain account-specific data (names, IDs, other people's posts).
tests/fixtures/live/ is gitignored. NEVER commit these files. Anonymize them before copying
anything into tests/fixtures/.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import Page, Response, sync_playwright  # noqa: E402

from backend.core import config  # noqa: E402
from backend.collectors.cookies import has_login_cookies  # noqa: E402
from backend.collectors.facebook import _launch_options, tab_url as facebook_tab_url  # noqa: E402

log = logging.getLogger("capture_feed")

FB_ORIGIN = "https://www.facebook.com"
GRAPHQL_MARKER = "/api/graphql/"
TABS = ("reels", "videos", "posts")
LIVE_DIR = config.ROOT / "tests" / "fixtures" / "live"
SCROLL_STEP_JS = "window.scrollBy(0, Math.max(800, window.innerHeight * 2))"


def tab_url(page_url: str, tab: str) -> str:
    """Use the scanner's URL routing, with posts opening the page's main feed."""
    parts = urlsplit(_with_scheme(page_url.strip()))
    path = re.sub(r"/(reels|videos|posts)/?$", "", parts.path)
    source = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
    return facebook_tab_url(source, tab)


def page_slug(page_url: str) -> str:
    """Filesystem-safe name for the page, taken from its vanity name or profile id."""
    parts = urlsplit(_with_scheme(page_url.strip()))
    query = parse_qs(parts.query)
    if parts.path.rstrip("/") == "/profile.php" and query.get("id"):
        raw = query["id"][0]
    else:
        segments = [seg for seg in parts.path.split("/") if seg and seg not in TABS]
        raw = segments[0] if segments else "page"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)[:60] or "page"


def capture(page_url: str, tab: str, scrolls: int, pause: float) -> Path:
    """Open the tab, scroll it, and write the captured responses. Returns the output folder."""
    target = tab_url(page_url, tab)
    responses: list[tuple[str, str]] = []

    def on_response(response: Response) -> None:
        if GRAPHQL_MARKER not in response.url or response.status != 200:
            return
        try:
            body = response.text()
        except PlaywrightError as exc:
            log.warning("Không đọc được nội dung phản hồi GraphQL: %s", exc)
            return
        responses.append((response.url, body))

    with sync_playwright() as pw:
        # Cùng trình duyệt và tùy chọn với tool: profile/ chỉ nên được một loại trình duyệt dùng.
        ctx = pw.chromium.launch_persistent_context(str(config.PROFILE_DIR), **_launch_options(hidden=False))
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", on_response)
            log.info("Đang mở %s", target)
            nav = page.goto(target, wait_until="domcontentloaded", timeout=60_000)
            initial_html = _initial_html(nav, page)
            for _ in range(scrolls):
                page.wait_for_timeout(int(pause * 1000))
                page.evaluate(SCROLL_STEP_JS)
            page.wait_for_timeout(int(pause * 1000))
            logged_in = has_login_cookies(ctx.cookies([FB_ORIGIN]))
        finally:
            ctx.close()

    if not logged_in:
        log.warning("Chưa thấy cookie đăng nhập (c_user, xs). Vẫn ghi lại; kết quả là phản hồi khi chưa đăng nhập.")
    if not responses:
        log.warning("Không bắt được phản hồi GraphQL nào. Kiểm tra lại URL tab hoặc đăng nhập.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = LIVE_DIR / f"{page_slug(page_url)}_{tab}_{stamp}"
    _write_capture(out_dir, page_url, target, tab, initial_html, responses, logged_in)
    return out_dir


def _with_scheme(url: str) -> str:
    return url if "://" in url else f"https://{url}"


def _initial_html(nav: Response | None, page: Page) -> str:
    """Raw HTML of the first load (the data-sjs blobs), or the live DOM if the response is unavailable."""
    if nav is not None:
        try:
            return nav.text()
        except PlaywrightError as exc:
            log.warning("Không đọc được HTML lần tải đầu: %s; dùng DOM hiện tại.", exc)
    return page.content()


def _write_capture(
    out_dir: Path,
    page_url: str,
    target: str,
    tab: str,
    initial_html: str,
    responses: list[tuple[str, str]],
    logged_in: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for number, (_, body) in enumerate(responses, start=1):
        (out_dir / f"graphql_{number:03d}.txt").write_text(body, encoding="utf-8")
    (out_dir / "initial_page.html").write_text(initial_html, encoding="utf-8")
    index = {
        "page_url": page_url,
        "tab": tab,
        "tab_url": target,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "logged_in": logged_in,
        "graphql_requests": [url.split("?", 1)[0] for url, _ in responses],
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghi lại GraphQL của tab Reels, Videos hoặc feed Bài đăng để làm fixture offline.")
    parser.add_argument("page_url", help="URL trang Facebook, ví dụ https://www.facebook.com/TenTrang")
    parser.add_argument("--tab", required=True, choices=TABS, help="Tab cần ghi: reels, videos hoặc posts (feed chính)")
    parser.add_argument("--scrolls", type=int, default=12, help="Số lần cuộn xuống (mặc định 12)")
    parser.add_argument("--pause", type=float, default=4.0, help="Thời gian chờ giữa các lần cuộn, tính bằng giây (mặc định 4.0)")
    args = parser.parse_args(argv)
    if args.scrolls < 0 or args.pause < 0:
        parser.error("--scrolls và --pause không được âm")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        out_dir = capture(args.page_url, args.tab, args.scrolls, args.pause)
    except PlaywrightError as exc:
        log.error("Lỗi trình duyệt (profile có thể đang được dùng bởi cửa sổ khác): %s", exc)
        return 1
    print(f"Đã ghi fixture vào {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
