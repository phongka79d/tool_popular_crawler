"""Chuẩn hóa số đếm và thời gian.

- parse_count: đổi chữ trên giao diện Facebook ("12K", "1,2 Tr", "12.345") thành số nguyên.
- Thời gian: giờ Việt Nam là UTC+7 cố định, không cần cơ sở dữ liệu múi giờ.
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

VN_TZ = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")

_SECONDS_PER_DAY = 86_400

# Hậu tố -> hệ số nhân. Khóa là chữ thường, dạng NFC.
_UNIT_MULTIPLIERS: dict[str, int] = {
    # nghìn (Facebook tiếng Việt hiển thị "12N")
    "k": 1_000, "n": 1_000, "nghìn": 1_000, "nghin": 1_000, "ngàn": 1_000, "ngan": 1_000,
    # triệu
    "m": 1_000_000, "tr": 1_000_000, "triệu": 1_000_000, "trieu": 1_000_000,
    # tỷ
    "b": 1_000_000_000, "tỷ": 1_000_000_000, "ty": 1_000_000_000,
}

# Dài nhất trước để "nghìn" thắng "n". (?!\w) sau hậu tố chặn các từ như "người", "bình", "nam".
_UNIT_PATTERN = "|".join(sorted((re.escape(u) for u in _UNIT_MULTIPLIERS), key=len, reverse=True))

# Số có thể có dấu "." hoặc "," phân cách; không đứng sau chữ, số, "." "," hoặc "-".
_COUNT_RE = re.compile(
    r"(?<![\w.,-])([0-9]+(?:[.,][0-9]+)*)(?:\s*(" + _UNIT_PATTERN + r")(?!\w))?"
)
_PLAIN_INT_RE = re.compile(r"[0-9]+")
_DECIMAL_RE = re.compile(r"[0-9]+[.,][0-9]+")
_THOUSANDS_RE = re.compile(r"[0-9]{1,3}(?:[.,][0-9]{3})+")


def parse_count(text: str) -> int | None:
    """Đổi chữ số đếm thành số nguyên; trả về None nếu không đọc được.

    Quy tắc:
    - Hậu tố k/n/nghìn/ngàn = x1.000; tr/triệu/m = x1.000.000; tỷ/b = x1.000.000.000.
      Không phân biệt hoa thường, có hoặc không có khoảng trắng trước hậu tố.
    - Có hậu tố: "." hoặc "," là dấu thập phân ("1.2K", "1,2 Tr"). Làm tròn nửa lên.
    - Không hậu tố: nhóm đúng 3 chữ số sau "." hoặc "," là hàng nghìn ("12.345", "1.234.567").
      Số lẻ không hậu tố ("1,5") không phải số đếm, trả về None.
    - Lấy số đọc được đầu tiên trong chuỗi, nên "12K lượt xem" = 12000.
    """
    if not text:
        return None
    normalized = unicodedata.normalize("NFC", text).lower()
    for match in _COUNT_RE.finditer(normalized):
        value = _count_from_token(match.group(1), match.group(2))
        if value is not None:
            return value
    return None


def _count_from_token(token: str, unit: str | None) -> int | None:
    if unit is None:
        if _PLAIN_INT_RE.fullmatch(token):
            return int(token)
        if _THOUSANDS_RE.fullmatch(token):
            return int(token.replace(".", "").replace(",", ""))
        return None
    multiplier = _UNIT_MULTIPLIERS[unit]
    if _PLAIN_INT_RE.fullmatch(token):
        return int(token) * multiplier
    if _DECIMAL_RE.fullmatch(token):
        amount = Decimal(token.replace(",", ".")) * multiplier
        return int(amount.to_integral_value(rounding=ROUND_HALF_UP))
    return None


def to_vn_datetime(ts: int) -> datetime:
    """Unix seconds -> datetime theo giờ Việt Nam (UTC+7)."""
    return datetime.fromtimestamp(ts, tz=VN_TZ)


def to_iso(ts: int) -> str:
    """Unix seconds -> chuỗi ISO 8601 theo giờ Việt Nam, ví dụ '2026-10-12T00:30:00+07:00'."""
    return to_vn_datetime(ts).isoformat(timespec="seconds")


def is_older_than(ts: int, days: int, now: int | None = None) -> bool:
    """True nếu bài đăng lúc `ts` đã cũ hơn `days` ngày (đúng bằng ngưỡng thì chưa cũ hơn).

    `now` mặc định là thời điểm hiện tại. So sánh theo giây unix, không phụ thuộc múi giờ.
    """
    current = int(time.time()) if now is None else now
    return current - ts > days * _SECONDS_PER_DAY
