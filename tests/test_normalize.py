"""Offline tests cho normalize.parse_count và các hàm thời gian (giờ VN UTC+7)."""
from __future__ import annotations

import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.core.normalize import is_older_than, parse_count, to_iso, to_vn_datetime

UTC = timezone.utc
DAY = 86_400


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Plain integers
        ("0", 0),
        ("123", 123),
        # EN suffixes (K, M, B)
        ("12K", 12_000),
        ("12k", 12_000),
        ("12 K", 12_000),
        ("1.2K", 1_200),
        ("1.2M", 1_200_000),
        ("1.2m", 1_200_000),
        ("1.5B", 1_500_000_000),
        ("1.234K", 1_234),
        # VN suffixes: N / nghìn / ngàn
        ("3 N", 3_000),
        ("12N", 12_000),
        ("2 nghìn", 2_000),
        ("2 ngàn", 2_000),
        ("2 nghin", 2_000),
        # VN suffixes: Tr / triệu
        ("1,2 Tr", 1_200_000),
        ("1,2 tr", 1_200_000),
        ("1,5 triệu", 1_500_000),
        ("1,5 trieu", 1_500_000),
        ("1,2345 Tr", 1_234_500),
        # Tỷ / B
        ("1,5 tỷ", 1_500_000_000),
        ("1,5 ty", 1_500_000_000),
        ("1,5 B", 1_500_000_000),
        # Dot / comma thousands separators (no suffix)
        ("12.345", 12_345),
        ("1.234.567", 1_234_567),
        ("1,234,567", 1_234_567),
        ("12,345", 12_345),
        # Rounding (half up) when a decimal and suffix produce a fraction
        ("1.2345K", 1_235),
        # Surrounding words
        ("12K lượt xem", 12_000),
        ("lượt xem 12K", 12_000),
        ("12 lượt xem", 12),
        ("12 người", 12),
        ("12 bình luận", 12),
        ("12 ngày", 12),
        ("12 nam", 12),
        ("12 trong", 12),
        ("12K · 3 bình luận", 12_000),
    ],
)
def test_parse_count_formats(text: str, expected: int) -> None:
    assert parse_count(text) == expected


def test_parse_count_accepts_decomposed_unicode() -> None:
    decomposed = unicodedata.normalize("NFD", "1,5 triệu")
    assert decomposed != "1,5 triệu"
    assert parse_count(decomposed) == 1_500_000
    assert parse_count(unicodedata.normalize("NFD", "1,5 tỷ")) == 1_500_000_000


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "lượt xem",
        "K",
        "Tr",
        "1,5",  # số lẻ không có hậu tố không phải số đếm
        "1.5",
        "1234.567",  # nhóm hàng nghìn sai
        "1.2.3K",  # hai dấu thập phân
        "v1.2",  # số đứng sau chữ không được đọc
        "-5",  # số đếm không âm
    ],
)
def test_parse_count_returns_none_for_garbage(text: str) -> None:
    assert parse_count(text) is None


def test_to_vn_datetime_uses_fixed_utc_plus_7() -> None:
    dt = to_vn_datetime(0)
    assert dt.utcoffset() == timedelta(hours=7)
    assert (dt.year, dt.month, dt.day, dt.hour) == (1970, 1, 1, 7)


def test_to_vn_datetime_rolls_day_at_vn_midnight() -> None:
    # 17:30 UTC ngày 11/10 là 00:30 ngày 12/10 theo giờ Việt Nam.
    ts = int(datetime(2026, 10, 11, 17, 30, tzinfo=UTC).timestamp())
    assert to_vn_datetime(ts).date() == date(2026, 10, 12)


def test_to_iso_formats_with_plus_07_offset() -> None:
    ts = int(datetime(2026, 10, 11, 17, 30, tzinfo=UTC).timestamp())
    assert to_iso(ts) == "2026-10-12T00:30:00+07:00"


def test_is_older_than_boundary_is_exclusive() -> None:
    now = 1_000_000_000
    assert is_older_than(now - 3 * DAY, 3, now=now) is False  # đúng ngưỡng: chưa cũ hơn
    assert is_older_than(now - 3 * DAY - 1, 3, now=now) is True
    assert is_older_than(now, 3, now=now) is False


def test_is_older_than_uses_current_time_by_default() -> None:
    assert is_older_than(0, 1) is True
    assert is_older_than(int(time.time()), 1) is False
