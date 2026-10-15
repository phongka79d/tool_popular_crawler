"""Computed setup journey and browser readiness for the desktop shell."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from backend.core import config, keys
from backend.collectors import browser_setup
from backend.api import channels, services
from backend.api.common import SERVICE_LABELS

logger = logging.getLogger("app.api.state")
_lock = threading.Lock()
_browser_ready = False
_browser_error: str | None = None


def prepare_browser() -> None:
    global _browser_ready, _browser_error
    try:
        if config.edge_path() is None:
            browser_setup.ensure_chromium()
    except Exception:
        logger.exception("Không chuẩn bị được trình duyệt quét")
        with _lock:
            _browser_ready = False
            _browser_error = "Không thể tải trình duyệt Chromium. Kiểm tra mạng, dung lượng ổ đĩa và mở lại ứng dụng."
    else:
        with _lock:
            _browser_ready = True
            _browser_error = None


@dataclass(frozen=True)
class _Guide:
    configured: dict[str, bool]
    channel_count: int
    fb_ready: bool
    running: bool
    has_result: bool
    question: bool

    @property
    def missing(self) -> list[str]:
        return [SERVICE_LABELS[name] for name in ("jev", "llm") if not self.configured[name]]

    @property
    def setup_done(self) -> bool:
        return self.channel_count > 0 and self.fb_ready


def _journey(guide: _Guide) -> list[dict]:
    ai = "done" if not guide.missing else "current"
    setup = "done" if guide.setup_done else ("current" if ai == "done" else "pending")
    if guide.running:
        scan = "current"
    elif guide.has_result:
        scan = "done"
    else:
        scan = "current" if ai == "done" and setup == "done" else "pending"
    return [{"title": title, "state": state} for title, state in
            (("1 · Dịch vụ AI", ai), ("2 · Kênh & Facebook", setup), ("3 · Chạy quét", scan))]


def _next_step(guide: _Guide) -> dict:
    if guide.question:
        text, page = "Quét đang chờ bạn chọn cách xử lý ở tab Chạy quét.", "scan"
    elif guide.running:
        text, page = "Đang quét. Theo dõi tiến độ ở tab Chạy quét.", "scan"
    elif guide.missing:
        text = f"Kết nối Jev và LLM ở tab Cài đặt để quét. Còn thiếu: {', '.join(guide.missing)}. Deepgram chỉ cần cho video."
        page = "settings"
    elif not guide.setup_done:
        todo = [text for text, done in (("thêm kênh cần quét", guide.channel_count > 0),
                                        ("đăng nhập Facebook", guide.fb_ready)) if not done]
        text, page = f"Hoàn tất bước 2 ở tab Cài đặt: {' và '.join(todo)}.", "settings"
    elif guide.has_result:
        text, page = "Đã có file Excel mới. Xem thống kê và mở file ở tab Kết quả.", "results"
    else:
        text, page = "Mọi thứ đã sẵn sàng. Ở tab Chạy quét, chọn loại quét và ngưỡng rồi bấm Bắt đầu quét.", "scan"
    return {"text": text, "page": page}


def scan_locked() -> bool:
    settings = config.load_settings()
    return any(not services._configured(name, settings, keys.get_key(name)) for name in ("jev", "llm"))


def get_app_state() -> dict:
    from backend.api import scan

    settings = config.load_settings()
    configured = {name: services._configured(name, settings, keys.get_key(name)) for name in SERVICE_LABELS}
    guide = _Guide(configured=configured, channel_count=len(channels.saved_channels()),
                   fb_ready=channels.facebook_logged_in(), running=scan.is_running(),
                   has_result=scan.has_result(), question=scan.has_question())
    logging_in = channels.is_logging_in()
    with _lock:
        browser = {"ready": _browser_ready, "error": _browser_error}
    return {"ok": True, "storage_secure": keys.storage_secure(), "browser": browser,
            "guide": {"configured": configured, "channel_count": guide.channel_count, "fb_ready": guide.fb_ready,
                      "running": guide.running, "has_result": guide.has_result, "question": guide.question,
                      "missing": guide.missing, "setup_done": guide.setup_done},
            "journey": _journey(guide), "next_step": _next_step(guide), "scan_locked": bool(guide.missing),
            "logging_in": logging_in, "busy": guide.running or logging_in}
