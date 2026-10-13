# -*- mode: python ; coding: utf-8 -*-
"""Build the local Streamlit launcher; mutable config stays outside the bundle."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH) / "src"
project_modules = [
    "app", "pipeline", "filters", "normalize", "db", "export_excel",
    "errors", "retry", "keys", "jev_client", "llm_client", "config", "models", "applog", "browser_setup",
]
collector_sources = sorted((root / "collectors").rglob("*.py"))
collector_modules = []
for source in collector_sources:
    parts = list(source.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    collector_modules.append(".".join(parts))

streamlit_datas, streamlit_binaries, streamlit_hiddenimports = collect_all("streamlit")
datas = streamlit_datas + [
    (str(root / f"{module}.py"), ".") for module in project_modules
]
datas += [
    (str(source), str(source.relative_to(root).parent))
    for source in collector_sources
]
datas.append((str(root / "assets"), "assets"))
for distribution in ("streamlit", "typesafe-sdk", "openai", "yt-dlp", "playwright", "keyring"):
    datas += copy_metadata(distribution)

hiddenimports = (
    project_modules
    + collector_modules
    + streamlit_hiddenimports
    + ["keyring.backends.Windows", "win32ctypes"]
    + collect_submodules("win32ctypes")
)

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root)],
    binaries=streamlit_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoCongThuc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # chỉ hiện cửa sổ ứng dụng; nhật ký ghi vào data/app.log (launcher.py)
    # Program files go to app/ so the folder root only shows the exe and user data.
    contents_directory="app",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoCongThuc",
)
