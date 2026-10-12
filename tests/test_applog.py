"""Nhật ký ứng dụng: không bao giờ ghi API key nguyên văn; bộ lọc lỗi giữ nguyên traceback."""
import pytest

import applog

STORED = "dg-secret-0123456789abcd"
TYPED = "sk-typed-but-not-saved-9876"


@pytest.fixture(autouse=True)
def stored_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(applog.keys, "get_key", lambda name: STORED if name == "deepgram" else None)
    monkeypatch.setattr(applog, "_secret_cache", (float("-inf"), ()))
    monkeypatch.setattr(applog, "_extra_secrets", set())
    monkeypatch.setattr(applog.config, "COOKIE_FILE", tmp_path / "fb_cookies.txt")


def test_stored_and_protected_keys_are_masked_in_every_written_line(tmp_path):
    applog.protect([TYPED, "abc", None])
    target = tmp_path / "app.log"
    with target.open("w", encoding="utf-8") as raw:
        stream = applog._RedactingStream(raw)
        stream.write(f"Deepgram 401 for key {STORED}\n")
        stream.writelines([f"LLM rejected {TYPED}\n", "abc stays readable\n"])
    text = target.read_text(encoding="utf-8")
    assert STORED not in text and TYPED not in text
    assert "••••abcd" in text and "••••9876" in text
    assert "abc stays readable" in text


def test_problem_filter_keeps_tracebacks_with_their_record(tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        "2026-10-12 11:32:43,001 INFO pipeline: Kênh 1/1: mở trang\n"
        "2026-10-12 11:32:44,002 ERROR app.ui: Lỗi không mong đợi: ValueError\n"
        "Traceback (most recent call last):\n"
        "ValueError: hỏng\n"
        "2026-10-12 11:32:45,003 WARNING pipeline: Không tải được audio\n",
        encoding="utf-8",
    )
    assert applog.read_records(problems_only=True, path=log) == [
        "2026-10-12 11:32:44,002 ERROR app.ui: Lỗi không mong đợi: ValueError\n"
        "Traceback (most recent call last):\nValueError: hỏng",
        "2026-10-12 11:32:45,003 WARNING pipeline: Không tải được audio",
    ]
    assert len(applog.read_records(path=log)) == 3
    assert applog.read_records(path=tmp_path / "missing.log") == []


def test_short_known_secrets_only(monkeypatch):
    monkeypatch.setattr(applog.keys, "get_key", lambda name: "a7Z9" if name == "llm" else "abc")
    applog.protect(["p4Q8", "xy"])
    assert applog.redact("a7Z9 p4Q8 abc xy short common words") == "•••• •••• abc xy short common words"


def test_facebook_login_cookies_refresh_after_ten_seconds(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(applog.time, "monotonic", lambda: now[0])
    path = applog.config.COOKIE_FILE
    def write_cookie(value):
        path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t123456\n"
            f"#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\txs\t{value}\n"
            ".facebook.com\tTRUE\t/\tTRUE\t0\tlocale\tvi_VN\n",
            encoding="utf-8",
        )
    write_cookie("old-cookie-secret")
    assert "123456" not in applog.redact("123456 old-cookie-secret vi_VN")
    assert "old-cookie-secret" not in applog.redact("old-cookie-secret")
    assert applog.redact("vi_VN") == "vi_VN"
    write_cookie("new-cookie-secret")
    now[0] = 109.0
    assert applog.redact("new-cookie-secret") == "new-cookie-secret"
    now[0] = 110.0
    assert "new-cookie-secret" not in applog.redact("new-cookie-secret")
