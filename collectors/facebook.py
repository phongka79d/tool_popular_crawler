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
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page as PwPage
from playwright.sync_api import Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config
from collectors import graphql
from collectors.cookies import has_login_cookies, load_cookie_file, write_netscape
from errors import BrowserUnavailable, LoginRequired
from models import Page
from normalize import is_older_than, parse_count

logger = logging.getLogger(__name__)

SEL: dict = config.load_json("selectors.json")
_TABS: tuple[tuple[str, str], ...] = tuple(SEL["tabs"].items())
_TAB_LABELS = {"reel": "Reels", "video": "Video"}

FB_HOME = "https://www.facebook.com/"
FB_COOKIE_URLS = ("https://www.facebook.com/", "https://m.facebook.com/", "https://web.facebook.com/")
LOCALE = "vi-VN"
GRAPHQL_MARK = "/api/graphql/"
NAV_TIMEOUT_MS = 60_000
RESPONSE_WAIT_MS = 12_000
HEADER_WAIT_MS = 8_000            # chờ phần đầu trang (tên, follower) hiện sau khi mở page
WHEEL_STEP_PX = (250, 650)        # mỗi nấc lăn chuột
WHEEL_GAP_MS = (120, 480)         # nghỉ giữa các nấc
WHEEL_MAX_STEPS = 14              # tối đa mỗi vòng cuộn
NEAR_BOTTOM_PX = 1500             # tới gần cuối trang thì Facebook tải thêm
WINDOW_SIZE = "1366,900"
# Cửa sổ thật nhưng đặt ngoài màn hình: cùng đường render với trình duyệt người dùng (không phải
# headless shell), và tắt cơ chế giảm tốc cửa sổ bị che để trang vẫn cuộn, tải bình thường.
HIDDEN_WINDOW_ARGS = (
    "--window-position=-32000,-32000",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-features=CalculateNativeWinOcclusion",
)
LOGIN_POLL_S = 2.0
LOGIN_REQUIRED_MSG = "Phiên Facebook đã hết hạn hoặc bị checkpoint. Vào Cài đặt → Đăng nhập Facebook."
# Edge chuyển lệnh mở sang phiên đang chạy cùng profile rồi thoát; Playwright chỉ báo trình duyệt đã đóng.
_PROFILE_BUSY_MARK = "Target page, context or browser has been closed"
PROFILE_BUSY_MSG = ("Trình duyệt của tool đang mở ở nơi khác (một cửa sổ Video Công Thức khác, hoặc cửa sổ "
                    "đăng nhập Facebook). Đóng các cửa sổ đó rồi thử lại; nếu vẫn lỗi, khởi động lại máy.")


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


_FB_HOSTS = frozenset({"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "mbasic.facebook.com"})
# Đoạn đầu đường dẫn không phải page: nhóm, bài viết, video lẻ, tính năng của Facebook.
_NOT_PAGE_SEGMENTS = frozenset({
    "watch", "events", "marketplace", "gaming", "reel", "reels", "share", "story.php", "permalink.php",
    "photo", "photo.php", "photos", "video.php", "hashtag", "search", "messages", "friends", "stories",
    "live", "ads", "business", "help", "login", "login.php", "home.php", "notifications", "bookmarks",
})


def page_url_problem(url: str) -> str | None:
    """Lý do link không phải trang chính của một page/profile Facebook; None nếu dùng được.

    Chỉ hỗ trợ page (fanpage): nhóm không có tab Reels/Video và không có số follower.
    """
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in _FB_HOSTS:
        return "Không phải link Facebook (cần dạng https://www.facebook.com/ten-page)."
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return "Thiếu tên page sau facebook.com/."
    head = parts[0].lower()
    if head == "groups":
        return "Link nhóm (group) không được hỗ trợ. Chỉ dùng link page (fanpage)."
    if head in _NOT_PAGE_SEGMENTS:
        return "Đây là link bài viết/video/tính năng, không phải page. Mở page rồi chép link trang chính."
    if head == "profile.php":
        return None if parse_qs(parsed.query).get("id") else "Link profile.php thiếu id=."
    if head == "people":
        return None if len(parts) == 3 else "Link /people/ phải có dạng /people/ten/ID."
    if head == "pg":
        return None if len(parts) == 2 else "Link /pg/ phải có dạng /pg/ten-page."
    if len(parts) != 1:
        return "Dùng link trang chính của page (https://www.facebook.com/ten-page), không kèm /videos, /posts..."
    return None


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


def _near_bottom(page: PwPage) -> bool:
    try:
        return bool(page.evaluate(
            f"window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - {NEAR_BOTTOM_PX}"
        ))
    except PlaywrightError:
        return True


def _save_user_agent(page: PwPage) -> None:
    """Lưu UA thật của trình duyệt để yt-dlp gửi cùng UA khi phải dùng cookie (tránh 1 phiên, 2 thiết bị)."""
    try:
        config.BROWSER_UA_FILE.write_text(page.evaluate("navigator.userAgent"), encoding="utf-8")
    except (PlaywrightError, OSError) as exc:
        logger.warning("Không lưu được User-Agent của trình duyệt: %s", exc)



def _launch_options(hidden: bool) -> dict:
    """Tùy chọn mở trình duyệt giống người dùng thật nhất có thể.

    - Edge cài sẵn của Windows (channel msedge) khi có: trình duyệt thương mại đủ codec video, GPU thật,
      cập nhật tự động; không có Edge thì dùng Chromium của Playwright.
    - Luôn chạy có cửa sổ (không headless): UA không chứa "HeadlessChrome"; quét thì cửa sổ nằm ngoài màn hình.
    - Bỏ cờ tự động hóa (--enable-automation, AutomationControlled) để navigator.webdriver là false
      và không hiện thanh "đang bị điều khiển bởi phần mềm tự động".
    - Kích thước cửa sổ thật (no_viewport) thay cho viewport cố định 1280x720 của Playwright.
    """
    args = ["--disable-blink-features=AutomationControlled", f"--window-size={WINDOW_SIZE}"]
    if hidden:
        args += HIDDEN_WINDOW_ARGS
    options: dict = {
        "headless": False,
        "locale": LOCALE,
        "no_viewport": True,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
    }
    if config.edge_path():
        options["channel"] = "msedge"
    return options


@contextlib.contextmanager
def _persistent_context(hidden: bool) -> Iterator[BrowserContext]:
    """Mở profile trình duyệt ở config.PROFILE_DIR, giữ phiên đăng nhập giữa các lần chạy.

    Đăng nhập (hidden=False) và quét (hidden=True) dùng cùng trình duyệt, cùng profile, cùng dấu vân tay,
    để Facebook thấy một thiết bị duy nhất.
    """
    config.ensure_dirs()
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(str(config.PROFILE_DIR), **_launch_options(hidden))
        except PlaywrightError as exc:
            if _PROFILE_BUSY_MARK not in str(exc):
                raise
            logger.warning("Profile trình duyệt đang được dùng: %s", exc)
            raise BrowserUnavailable("facebook", PROFILE_BUSY_MSG) from exc
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
    with _persistent_context(hidden=False) as ctx:
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
                    _save_user_agent(page)
                    logger.info("Đã đăng nhập Facebook và lưu cookie.")
                    return True
            except PlaywrightError:
                logger.info("Cửa sổ đăng nhập đã đóng trước khi đăng nhập xong.")
                return False
            time.sleep(LOGIN_POLL_S)
    logger.warning("Hết thời gian chờ đăng nhập Facebook.")
    return False


def import_cookies(path: Path | str) -> bool:
    """Nhập Cookie-Editor, EditThisCookie hoặc Netscape vào profile và lưu cho yt-dlp.

    Chỉ xuất cookie khi context có đủ c_user và xs của Facebook.
    Tệp không đọc được, cookie không hợp lệ hoặc thiếu phiên đăng nhập trả False.
    """
    try:
        imported = load_cookie_file(path)
        if not imported:
            logger.warning("Tệp cookie không chứa cookie để nhập.")
            return False
        with _persistent_context(hidden=True) as ctx:
            ctx.add_cookies(imported)
            current = ctx.cookies(list(FB_COOKIE_URLS))
            if not has_login_cookies(current):
                logger.warning("Cookie đã nhập thiếu c_user hoặc xs của Facebook.")
                return False
            write_netscape(current)
            _save_user_agent(_first_page(ctx))
    except (OSError, ValueError, PlaywrightError):
        logger.warning("Không nhập được cookie Facebook. Kiểm tra tệp cookie và trình duyệt.")
        return False
    logger.info("Đã nhập và lưu cookie Facebook.")
    return True


class _Collector:
    """Gom video đúng định dạng và nằm trong số ngày quét; bỏ trùng theo video_id."""

    def __init__(self, formats: set[str], days: int, max_videos: int) -> None:
        self._formats = formats
        self._days = days
        self.limit = max_videos
        self.items_seen = 0  # mọi video đọc được, kể cả khác định dạng hoặc quá cũ
        self._by_id: dict[str, dict] = {}
        self._old_formats: set[str] = set()

    def add(self, items: list[dict], tab_format: str) -> None:
        for item in items:
            video_id = item.get("video_id")
            if video_id:
                self.items_seen += 1
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
        return len(self._by_id) >= self.limit

    def done(self, tab_format: str) -> bool:
        return tab_format in self._old_formats

    def videos(self) -> list[dict]:
        return list(self._by_id.values())[: self.limit]


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

    def __init__(self, hidden: bool = True, settings: dict | None = None) -> None:
        self.hidden = hidden
        self.settings = settings if settings is not None else config.load_settings()
        self._stack = contextlib.ExitStack()
        self._page: PwPage | None = None

    def __enter__(self) -> FacebookScanner:
        ctx = self._stack.enter_context(_persistent_context(self.hidden))
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
            _save_user_agent(self._require_page())
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
        page = self._require_page()
        header = graphql.parse_page_header(page.content())
        if not header["name"] or header["followers"] is None:
            # Phần đầu trang (tên, follower) đến sau domcontentloaded: chờ dòng follower hiện rồi đọc lại.
            with contextlib.suppress(PlaywrightError):
                page.locator(SEL["page"]["followers_text"]).first.wait_for(timeout=HEADER_WAIT_MS)
            later = graphql.parse_page_header(page.content())
            header = {"name": header["name"] or later["name"],
                      "followers": header["followers"] if header["followers"] is not None else later["followers"]}
        name = str(header.get("name") or "").strip() or self._first_text(SEL["page"]["name"])
        followers = _as_count(header.get("followers"))
        if followers is None:
            followers = self._followers_from_text()
        if not name:
            logger.warning("Không đọc được tên page %s", page_url)
        return Page(url=page_url, name=name, followers=followers)

    def _scroll_once(self) -> None:
        """Một vòng cuộn như người dùng: đưa chuột vào feed rồi lăn từng nấc tới gần cuối trang."""
        page = self._require_page()
        try:
            with page.expect_response(lambda resp: GRAPHQL_MARK in resp.url, timeout=RESPONSE_WAIT_MS):
                page.mouse.move(random.randint(350, 950), random.randint(250, 700), steps=random.randint(4, 12))
                for _ in range(WHEEL_MAX_STEPS):
                    page.mouse.wheel(0, random.randint(*WHEEL_STEP_PX))
                    page.wait_for_timeout(random.randint(*WHEEL_GAP_MS))
                    if _near_bottom(page):
                        break
        except PlaywrightTimeoutError:
            logger.debug("Không thấy phản hồi GraphQL sau khi cuộn.")

    def _scan_tab(
        self,
        tab_url: str,
        tab_format: str,
        collector: _Collector,
        pending: list[Response],
        stop_event: threading.Event | None,
        report: Callable[[str], None],
    ) -> str:
        """Cuộn một tab tới khi có lý do dừng; trả lý do đó để báo tiến độ."""
        scan = self.settings["scan"]
        label = _TAB_LABELS.get(tab_format, tab_format)
        found_before = collector.count()
        seen_before = collector.items_seen
        self._open(tab_url)
        _human_pause(scan, stop_event)
        _drain(pending, collector, tab_format)
        collector.add(graphql.parse_initial_html(self._require_page().content()), tab_format)
        stall = 0
        max_rounds = int(scan["max_scroll_rounds"])
        for round_no in range(1, max_rounds + 1):
            if _stopped(stop_event):
                return "đã dừng theo yêu cầu"
            if collector.full():
                return f"đã đủ {collector.limit} video"
            before = collector.count()
            self._scroll_once()
            self._raise_if_blocked()
            _drain(pending, collector, tab_format)
            report(f"Tab {label} · cuộn lần {round_no}: đã thấy {collector.count() - found_before} video")
            if collector.done(tab_format):
                return "đã tới video cũ hơn số ngày quét"
            if collector.items_seen == seen_before:
                # Tab trống hoặc page không xem được: không chờ thêm các vòng cuộn (mỗi vòng tới 20 giây).
                return "tab không có video nào"
            stall = 0 if collector.count() > before else stall + 1
            if stall >= int(scan["stall_rounds"]):
                return f"không có video mới sau {stall} lần cuộn"
            _human_pause(scan, stop_event)
        return f"đã cuộn tối đa {max_rounds} lần"

    def scan_page(
        self,
        page_url: str,
        days: int,
        formats: set[str],
        max_videos: int,
        stop_event: threading.Event | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[dict]:
        """Quét tab Reels và/hoặc Video của page, trả về các dict từ graphql.flatten (đã bỏ trùng).

        Chỉ giữ video đúng định dạng và không cũ hơn `days` ngày. Dừng khi hết cuộn mới (stall),
        tab không có video nào, đạt số vòng tối đa, đủ max_videos, gặp video cũ, hoặc stop_event được bật.
        `on_progress` nhận từng bước (mở tab, mỗi vòng cuộn, lý do dừng) để hiện cho người dùng.
        """
        tabs = [(fmt, tab) for fmt, tab in _TABS if fmt in formats]
        if not tabs or max_videos <= 0:
            return []
        report = on_progress or (lambda message: None)
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
                label = _TAB_LABELS.get(fmt, fmt)
                url = tab_url(page_url, tab)
                logger.info("Quét tab %s của %s", tab, page_url)
                report(f"Tab {label}: đang mở…")
                found_before = collector.count()
                reason = self._scan_tab(url, fmt, collector, pending, stop_event, report)
                found = collector.count() - found_before
                logger.info("Tab %s của %s: %d video, dừng vì %s", tab, page_url, found, reason)
                report(f"Tab {label} xong: {found} video, dừng vì {reason}")
        finally:
            page.remove_listener("response", on_response)
            self._export_cookies()
        return collector.videos()

    def polite_page_pause(self, stop_event: threading.Event | None = None) -> None:
        """Nghỉ 30–60 giây giữa các page (PLAN §4). stop_event bật thì thoát ngay."""
        scan = self.settings["scan"]
        _pause(random.uniform(scan["page_delay_min_s"], scan["page_delay_max_s"]), stop_event)
