"""Paths and settings loading. Works both from source and from a PyInstaller build."""
from __future__ import annotations

import json
import sys
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


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, PROFILE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_json(name: str) -> dict:
    """Load config/<name> (e.g. 'taxonomy.json')."""
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


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
