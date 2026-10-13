"""Chuẩn bị Chromium dùng chung cho cửa sổ ứng dụng và trình duyệt quét."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import applog


def browsers_installed(executable: Path) -> bool:
    """Chỉ nhận bản tải đã giải nén hoàn tất."""
    return executable.is_file() and (executable.parents[1] / "INSTALLATION_COMPLETE").is_file()


def ensure_chromium() -> Path:
    if getattr(sys, "frozen", False):
        # Đặt trước khi Playwright tính executable_path, không chỉ cho subprocess cài đặt.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if browsers_installed(executable):
        return executable
    command = compute_driver_executable()
    print("Đang tải Chromium lần đầu (~150 MB), vui lòng chờ...", flush=True)
    result = subprocess.run([*command, "install", "chromium", "--no-shell"],
                            env=get_driver_env(), stdout=sys.stdout, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or not browsers_installed(executable):
        applog.log.error("Tải Chromium thất bại (mã %s); thiếu %s", result.returncode, executable)
        raise RuntimeError("Không thể tải Chromium. Kiểm tra mạng và dung lượng ổ đĩa rồi thử lại.")
    return executable
