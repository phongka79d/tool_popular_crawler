"""Paths and settings loading. Works both from source and from a PyInstaller build."""
from __future__ import annotations

import json
import os
import shutil
import sys
import re
import unicodedata
from pathlib import Path

# Frozen exe: data lives next to VideoCongThuc.exe; source: next to this file.
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
PROFILE_DIR = ROOT / "profile"
MODELS_DIR = ROOT / "models"  # faster-whisper tự tải model vào đây khi cần lần đầu
DB_PATH = DATA_DIR / "cache.db"
COOKIE_FILE = DATA_DIR / "fb_cookies.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
BROWSER_UA_FILE = DATA_DIR / "browser_ua.txt"  # UA thật của trình duyệt quét, dùng lại cho yt-dlp


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, PROFILE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def edge_path() -> str | None:
    """msedge.exe của Microsoft Edge (cài cho máy hoặc cho người dùng), None nếu máy không có."""
    for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if root:
            exe = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.is_file():
                return str(exe)
    return shutil.which("msedge")


def load_json(name: str) -> dict:
    """Load config/<name> (e.g. 'taxonomy.json')."""
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


TAXONOMY_GROUPS = {
    "topic": "Chủ đề", "hook_type": "Kiểu hook", "structure": "Cấu trúc", "cta": "CTA",
}


def load_taxonomy() -> dict:
    return load_json("taxonomy.json")


def load_default_taxonomy() -> dict:
    return load_json("taxonomy.default.json")


def label_code(name: str, used: set[str]) -> str:
    """Generate a stable ASCII snake_case code, unique across all groups."""
    text = unicodedata.normalize("NFKD", name.lower().replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    base = re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "nhan"
    code = base
    suffix = 2
    while code in used:
        code = f"{base}_{suffix}"
        suffix += 1
    return code


def taxonomy_rows(taxonomy: dict, group: str) -> list[dict]:
    """Editable rows; escape choices are displayed separately, read-only."""
    return [
        {"code": code, "name": taxonomy["labels"][code], "description": description}
        for code, description in taxonomy[group].items()
        if code not in {"khac", "khong_co"}
    ]


def save_taxonomy(groups: dict[str, list[dict]]) -> dict:
    """Validate all editor rows before writing; preserve codes and fixed escapes."""
    current = load_taxonomy()
    defaults = load_default_taxonomy()
    result = {key: value for key, value in current.items() if key not in TAXONOMY_GROUPS}
    result["labels"] = {
        code: name for code, name in current["labels"].items()
        if not any(code in current[group] for group in TAXONOMY_GROUPS)
    }
    used = set(current["labels"]) | set(defaults["labels"])
    for group, title in TAXONOMY_GROUPS.items():
        rows = groups.get(group, [])
        if len(rows) < 2:
            raise ValueError(f"{title}: cần ít nhất 2 nhãn (không tính Khác / Không có CTA).")
        names = {defaults["labels"][code].casefold() for code in ("khac", "khong_co") if code in defaults[group]}
        choices = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            description = str(row.get("description") or "").strip()
            if not name or not description:
                raise ValueError(f"{title}: tên hiển thị và mô tả cho Jev không được để trống.")
            if name.casefold() in names:
                raise ValueError(f"{title}: tên nhãn bị trùng: {name}.")
            names.add(name.casefold())
            code = row.get("code")
            if code not in current[group] or code in {"khac", "khong_co"}:
                code = label_code(name, used)
            if code in choices:
                raise ValueError(f"{title}: nhãn bị trùng, hãy xóa dòng lặp.")
            used.add(code)
            choices[code] = description
            result["labels"][code] = name
        for code in ("khong_co", "khac"):
            if code in defaults[group]:
                choices[code] = defaults[group][code]
                result["labels"][code] = defaults["labels"][code]
        result[group] = choices
    (CONFIG_DIR / "taxonomy.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return result


def reset_taxonomy() -> dict:
    """Restore the shipped file verbatim, including its fixed escape choices."""
    source = CONFIG_DIR / "taxonomy.default.json"
    (CONFIG_DIR / "taxonomy.json").write_bytes(source.read_bytes())
    return load_taxonomy()


def load_settings() -> dict:
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_lines(rel_path: str) -> list[str]:
    """Non-empty, non-comment lines of a text file relative to ROOT (e.g. 'config/channels.txt')."""
    p = ROOT / rel_path
    if not p.exists():
        return []
    return [s for s in (l.strip() for l in p.read_text(encoding="utf-8").splitlines()) if s and not s.startswith("#")]
