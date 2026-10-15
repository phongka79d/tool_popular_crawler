"""Nhập cookie JSON/Netscape và xuất phiên Facebook cho yt-dlp (PLAN §11.1, §11.3).

Tệp cookie chứa phiên đăng nhập: chỉ để trong data/, không gửi cho người khác.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from backend.core import config

logger = logging.getLogger(__name__)

NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
# yt-dlp (và curl) đánh dấu cookie HttpOnly bằng tiền tố này trên đầu dòng.
HTTPONLY_PREFIX = "#HttpOnly_"
LOGIN_COOKIES = ("c_user", "xs")

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_BOOL_FIELDS = ("TRUE", "FALSE")
_NETSCAPE_FIELD_COUNT = 7
_SAME_SITES = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}


def _expiry(value: float | None) -> int:
    """Playwright ghi -1 cho cookie phiên; Netscape ghi 0."""
    if value is None:
        return 0
    seconds = int(float(value))
    return seconds if seconds > 0 else 0


def _has_control(text: str) -> bool:
    return "\t" in text or "\n" in text or "\r" in text


def _format_line(cookie: dict) -> str | None:
    name = str(cookie.get("name") or "")
    domain = str(cookie.get("domain") or "")
    if not name or not domain:
        return None
    fields = [
        domain,
        "TRUE" if domain.startswith(".") else "FALSE",
        str(cookie.get("path") or "/"),
        "TRUE" if cookie.get("secure") else "FALSE",
        str(_expiry(cookie.get("expires"))),
        name,
        str(cookie.get("value") or ""),
    ]
    if any(_has_control(field) for field in fields):
        return None
    prefix = HTTPONLY_PREFIX if cookie.get("httpOnly") else ""
    return prefix + "\t".join(fields)


def write_netscape(cookies: list[dict], path: Path | str = config.COOKIE_FILE) -> None:
    """Ghi cookie từ context.cookies() của Playwright thành tệp Netscape.

    Ghi tạm rồi thay thế để yt-dlp không đọc phải tệp dở dang.
    """
    target = Path(path)
    lines = [NETSCAPE_HEADER, "# Phiên đăng nhập Facebook: không chia sẻ tệp này.", ""]
    for cookie in cookies:
        line = _format_line(cookie)
        if line is None:
            logger.warning("Bỏ qua cookie không hợp lệ: %s", cookie.get("name"))
            continue
        lines.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def read_netscape(path: Path | str = config.COOKIE_FILE) -> list[dict]:
    """Đọc tệp Netscape thành dict cùng khóa với cookie của Playwright (expires -1 = phiên)."""
    cookies: list[dict] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        http_only = line.startswith(HTTPONLY_PREFIX)
        if http_only:
            line = line[len(HTTPONLY_PREFIX):]
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != _NETSCAPE_FIELD_COUNT:
            logger.warning("Bỏ qua dòng cookie sai định dạng (%d trường)", len(fields))
            continue
        domain, _include_sub, cookie_path, secure, expires, name, value = fields
        seconds = int(float(expires)) if _NUMBER_RE.fullmatch(expires) else 0
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path,
            "expires": seconds if seconds > 0 else -1,
            "httpOnly": http_only,
            "secure": secure == "TRUE",
        })
    return cookies


def convert_cookie_editor(data: list[dict]) -> list[dict]:
    """Đổi Cookie-Editor/EditThisCookie sang cookie Playwright, bỏ khóa riêng của tiện ích."""
    converted: list[dict] = []
    for cookie in data:
        if not isinstance(cookie, dict) or "name" not in cookie or "value" not in cookie:
            continue
        converted.append({
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie.get("domain", ""),
            "path": cookie.get("path", "/"),
            "expires": -1 if cookie.get("session") else cookie.get("expirationDate", -1),
            "secure": bool(cookie.get("secure", False)),
            "httpOnly": bool(cookie.get("httpOnly", False)),
            "sameSite": _SAME_SITES.get(str(cookie.get("sameSite") or "").lower(), "Lax"),
        })
    return converted


def load_cookie_file(path: Path | str) -> list[dict]:
    """Đọc JSON của Cookie-Editor/EditThisCookie hoặc Netscape để nhập vào Playwright.

    Tệp không đúng định dạng gây ValueError; lỗi đọc tệp được giữ nguyên.
    Không đưa nội dung cookie vào thông báo lỗi.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if not _looks_netscape(text):
            raise ValueError("Tệp cookie không đúng định dạng JSON hoặc Netscape.") from None
        return read_netscape(path)
    if not isinstance(data, list):
        raise ValueError("Tệp cookie JSON phải là danh sách cookie.")
    return convert_cookie_editor(data)


def _is_data_line(line: str) -> bool:
    if line.startswith(HTTPONLY_PREFIX):
        line = line[len(HTTPONLY_PREFIX):]
    fields = line.split("\t")
    return (
        len(fields) == _NETSCAPE_FIELD_COUNT
        and fields[1] in _BOOL_FIELDS
        and fields[3] in _BOOL_FIELDS
        and _NUMBER_RE.fullmatch(fields[4]) is not None
    )


def _looks_netscape(text: str) -> bool:
    # Bỏ dòng trống và thụt đầu dòng; giữ nguyên tab cuối (giá trị rỗng).
    lines = [line.lstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    first = lines[0]
    if first.startswith(("{", "[")):  # JSON (EditThisCookie, Cookie-Editor...)
        return False
    if "Netscape" in first or "HTTP Cookie File" in first:
        return True
    # Một số trình xuất bỏ header nhưng vẫn giữ các trường cách nhau bằng tab.
    for line in lines:
        if line.startswith("#") and not line.startswith(HTTPONLY_PREFIX):
            continue
        return _is_data_line(line)
    return False


def is_netscape_file(path: Path | str = config.COOKIE_FILE) -> bool:
    """True nếu tệp có dạng cookie Netscape (có header, hoặc dòng dữ liệu 7 trường)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _looks_netscape(text)


def has_login_cookies(cookies: list[dict]) -> bool:
    """True khi có đủ c_user và xs với giá trị khác rỗng."""
    present = {cookie.get("name") for cookie in cookies if cookie.get("value")}
    return all(name in present for name in LOGIN_COOKIES)
