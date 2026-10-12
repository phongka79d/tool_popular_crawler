"""Đăng nhập Facebook và quét video của page bằng Playwright (PLAN §4, §11.1–§11.2).

Chỉ số lấy từ phản hồi GraphQL mà trình duyệt nhận khi cuộn và từ JSON nhúng trong HTML ban đầu
(qua collectors.graphql). Các selector và tên tab nằm trong config/selectors.json.
"""
from __future__ import annotations

import contextlib
import logging
import random
import re
import threading
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page as PwPage
from playwright.sync_api import Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config
from collectors import graphql
from collectors.cookies import has_login_cookies, write_netscape
from errors import LoginRequired
from models import Page
from normalize import is_older_than, parse_count

logger = logging.getLogger(__name__)

SEL: dict = config.load_json("selectors.json")
_TABS: tuple[tuple[str, str], ...] = tuple(SEL["tabs"].items())

FB_HOME = "https://www.facebook.com/"
FB_COOKIE_URLS = ("https://www.facebook.com/", "https://m.facebook.com/", "https://web.facebook.com/")
LOCALE = "vi-VN"
GRAPHQL_MARK = "/api/graphql/"
NAV_TIMEOUT_MS = 60_000
RESPONSE_WAIT_MS = 8_000
WHEEL_PX = (600, 1200)
LOGIN_POLL_S = 2.0
LOGIN_REQUIRED_MSG = "Phiên Facebook đã hết hạn hoặc bị checkpoint. Vào Cài đặt → Đăng nhập Facebook."


def _is_blocked_url(url: str) -> bool:
    path = urlsplit(url).path
    return any(path.startswith(prefix) for prefix in SEL["login"]["blocked_path_prefixes"])


def _stopped(stop_event: threading.Event | None) -> bool:
    return stop_event is not None and stop_event.is_set()


def _pause(seconds: float, stop_event: threading.Event | None = None) -> None:
    """Nghỉ; nếu có stop_event thì thoát ngay khi stop_event được bật."""
    if stop_event is None:
        time.sleep(seconds)
    else:
        stop_event.wait(seconds)


def _human_pause(scan_cfg: dict, stop_event: threading.Event | None) -> None:
    _pause(random.uniform(scan_cfg["delay_min_s"], scan_cfg["delay_max_s"]), stop_event)


def _as_count(value: object) -> int | None:
    if isinstance(value, str):
        return parse_count(value)
    return value if isinstance(value, int) else None


def tab_url(page_url: str, tab: str) -> str:
    """URL tab chuẩn www: vanity/pg dùng đường dẫn, profile/people giữ ID qua query.

    `tab` là "reels" hoặc "videos"; bỏ tham số theo dõi và fragment của URL đầu vào.
    """
    parsed = urlsplit(page_url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if path == "profile.php":
        profile_id = parse_qs(parsed.query)["id"][0]
    elif len(parts) == 3 and parts[0] == "people":
        profile_id = parts[2]
    else:
        if len(parts) == 2 and parts[0] == "pg":
            path = parts[1]
        return f"{FB_HOME}{path}/{tab}/"
    query = urlencode({"id": profile_id, "sk": "reels_tab" if tab == "reels" else "videos"})
    return f"{FB_HOME}profile.php?{query}"


def _first_page(ctx: BrowserContext) -> PwPage:
    return ctx.pages[0] if ctx.pages else ctx.new_page()


@contextlib.contextmanager
def _persistent_context(headless: bool) -> Iterator[BrowserContext]:
    """Mở profile Playwright ở config.PROFILE_DIR, giữ phiên đăng nhập giữa các lần chạy."""
    config.ensure_dirs()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(config.PROFILE_DIR), headless=headless, locale=LOCALE)
        try:
            yield ctx
        finally:
            with contextlib.suppress(PlaywrightError):
                ctx.close()


def login_interactive(timeout_s: int = 600) -> bool:
    """Mở Chromium có giao diện để người dùng tự đăng nhập.

    Khi thấy c_user và xs (và không ở checkpoint hay trang đăng nhập) thì xuất cookie
    và trả True. Hết giờ hoặc người dùng đóng cửa sổ thì trả False.
    """
    deadline = time.monotonic() + timeout_s
    with _persistent_context(headless=False) as ctx:
        page = _first_page(ctx)
        try:
            page.goto(FB_HOME, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightError as exc:
            logger.warning("Không tải được trang đăng nhập Facebook: %s", exc)
        while time.monotonic() < deadline:
            try:
                cookies = ctx.cookies(list(FB_COOKIE_URLS))
                if has_login_cookies(cookies) and not _is_blocked_url(page.url):
                    write_netscape(cookies)
                    logger.info("Đã đăng nhập Facebook và lưu cookie.")
                    return True
            except PlaywrightError:
                logger.info("Cửa sổ đăng nhập đã đóng trước khi đăng nhập xong.")
                return False
            time.sleep(LOGIN_POLL_S)
    logger.warning("Hết thời gian chờ đăng nhập Facebook.")
    return False


class _Collector:
    """Gom video đúng định dạng và nằm trong số ngày quét; bỏ trùng theo video_id."""

    def __init__(self, formats: set[str], days: int, max_videos: int) -> None:
        self._formats = formats
        self._days = days
        self._max = max_videos
        self._by_id: dict[str, dict] = {}
        self._old_formats: set[str] = set()

    def add(self, items: list[dict], tab_format: str) -> None:
        for item in items:
            video_id = item.get("video_id")
            fmt = item.get("format")
            if not video_id or fmt not in self._formats:
                continue
            posted_at = item.get("posted_at")
            if posted_at is not None and is_older_than(posted_at, self._days):
                # Gặp video cũ hơn số ngày quét thì dừng cuộn tab đó (PLAN §4).
                if fmt == tab_format:
                    self._old_formats.add(tab_format)
                continue
            existing = self._by_id.get(video_id)
            if existing is None:
                self._by_id[video_id] = dict(item)
                continue
            for key, value in item.items():
                if existing.get(key) in (None, "") and value not in (None, ""):
                    existing[key] = value

    def count(self) -> int:
        return len(self._by_id)

    def full(self) -> bool:
        return len(self._by_id) >= self._max

    def done(self, tab_format: str) -> bool:
        return tab_format in self._old_formats

    def videos(self) -> list[dict]:
        return list(self._by_id.values())[: self._max]


def _drain(pending: list[Response], collector: _Collector, tab_format: str) -> None:
    """Đọc nội dung các phản hồi GraphQL đã nhận. Đọc ở vòng lặp chính, không trong event handler."""
    responses = list(pending)
    pending.clear()
    for resp in responses:
        try:
            body = resp.text()
        except PlaywrightError as exc:
            logger.debug("Bỏ qua phản hồi GraphQL không đọc được: %s", exc)
            continue
        collector.add(graphql.parse_graphql_response(body), tab_format)


class FacebookScanner:
    """Context manager: mở profile Playwright đã đăng nhập để kiểm tra và quét page."""

    def __init__(self, headless: bool = True, settings: dict | None = None) -> None:
        self.headless = headless
        self.settings = settings if settings is not None else config.load_settings()
        self._stack = contextlib.ExitStack()
        self._page: PwPage | None = None

    def __enter__(self) -> FacebookScanner:
        ctx = self._stack.enter_context(_persistent_context(self.headless))
        self._page = _first_page(ctx)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stack.close()
        self._page = None

    def _require_page(self) -> PwPage:
        if self._page is None:
            raise RuntimeError("FacebookScanner chỉ dùng được trong khối with.")
        return self._page

    def _cookies(self) -> list[dict]:
        return self._require_page().context.cookies(list(FB_COOKIE_URLS))

    def _raise_if_blocked(self) -> None:
        page = self._require_page()
        if _is_blocked_url(page.url) or not has_login_cookies(self._cookies()):
            raise LoginRequired("facebook", LOGIN_REQUIRED_MSG)

    def _open(self, url: str) -> None:
        self._require_page().goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self._raise_if_blocked()

    def _first_text(self, selector: str) -> str:
        loc = self._require_page().locator(selector).first
        try:
            if loc.count() == 0:
                return ""
            return (loc.inner_text(timeout=3000) or "").strip()
        except PlaywrightError as exc:
            logger.debug("Không đọc được chữ của selector %s: %s", selector, exc)
            return ""

    def _followers_from_text(self) -> int | None:
        text = self._first_text(SEL["page"]["followers_text"])
        match = re.search(SEL["page"]["followers_pattern"], text, re.IGNORECASE)
        return parse_count(match.group(1)) if match else None

    def _export_cookies(self) -> None:
        """Ghi lại cookie sau mỗi lần quét để giữ phiên mới nhất cho yt-dlp."""
        try:
            cookies = self._cookies()
        except PlaywrightError as exc:
            logger.warning("Không đọc được cookie để lưu: %s", exc)
            return
        if has_login_cookies(cookies):
            write_netscape(cookies)
        else:
            logger.warning("Thiếu c_user hoặc xs; không cập nhật tệp cookie.")

    def check_login(self) -> None:
        """Raise LoginRequired nếu thiếu cookie đăng nhập, hoặc Facebook chuyển sang checkpoint hay trang đăng nhập."""
        if not has_login_cookies(self._cookies()):
            raise LoginRequired("facebook", LOGIN_REQUIRED_MSG)
        self._open(FB_HOME)

    def get_page_info(self, page_url: str) -> Page:
        """Tên và số follower của page. Ưu tiên JSON trong HTML, sau đó dùng selector dự phòng."""
        self._open(page_url)
        header = graphql.parse_page_header(self._require_page().content())
        name = str(header.get("name") or "").strip() or self._first_text(SEL["page"]["name"])
        followers = _as_count(header.get("followers"))
        if followers is None:
            followers = self._followers_from_text()
        return Page(url=page_url, name=name, followers=followers)

    def _scroll_once(self) -> None:
        page = self._require_page()
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.mouse.wheel(0, random.randint(*WHEEL_PX))
        try:
            page.wait_for_response(lambda resp: GRAPHQL_MARK in resp.url, timeout=RESPONSE_WAIT_MS)
        except PlaywrightTimeoutError:
            logger.debug("Không thấy phản hồi GraphQL sau khi cuộn.")

    def _scan_tab(
        self,
        tab_url: str,
        tab_format: str,
        collector: _Collector,
        pending: list[Response],
        stop_event: threading.Event | None,
    ) -> None:
        scan = self.settings["scan"]
        self._open(tab_url)
        _human_pause(scan, stop_event)
        _drain(pending, collector, tab_format)
        collector.add(graphql.parse_initial_html(self._require_page().content()), tab_format)
        stall = 0
        for _ in range(int(scan["max_scroll_rounds"])):
            if _stopped(stop_event) or collector.full():
                return
            before = collector.count()
            self._scroll_once()
            self._raise_if_blocked()
            _drain(pending, collector, tab_format)
            if collector.done(tab_format):
                return
            stall = 0 if collector.count() > before else stall + 1
            if stall >= int(scan["stall_rounds"]):
                return
            _human_pause(scan, stop_event)

    def scan_page(
        self,
        page_url: str,
        days: int,
        formats: set[str],
        max_videos: int,
        stop_event: threading.Event | None = None,
    ) -> list[dict]:
        """Quét tab Reels và/hoặc Video của page, trả về các dict từ graphql.flatten (đã bỏ trùng).

        Chỉ giữ video đúng định dạng và không cũ hơn `days` ngày. Dừng khi hết cuộn mới (stall),
        đạt số vòng tối đa, đủ max_videos, gặp video cũ, hoặc stop_event được bật.
        """
        tabs = [(fmt, tab) for fmt, tab in _TABS if fmt in formats]
        if not tabs or max_videos <= 0:
            return []
        page = self._require_page()
        collector = _Collector(set(formats), days, max_videos)
        pending: list[Response] = []

        def on_response(resp: Response) -> None:
            if resp.status == 200 and GRAPHQL_MARK in resp.url:
                pending.append(resp)

        page.on("response", on_response)
        try:
            for fmt, tab in tabs:
                if collector.full() or _stopped(stop_event):
                    break
                url = tab_url(page_url, tab)
                logger.info("Quét tab %s của %s", tab, page_url)
                self._scan_tab(url, fmt, collector, pending, stop_event)
        finally:
            page.remove_listener("response", on_response)
            self._export_cookies()
        return collector.videos()

    def polite_page_pause(self, stop_event: threading.Event | None = None) -> None:
        """Nghỉ 30–60 giây giữa các page (PLAN §4). stop_event bật thì thoát ngay."""
        scan = self.settings["scan"]
        _pause(random.uniform(scan["page_delay_min_s"], scan["page_delay_max_s"]), stop_event)
