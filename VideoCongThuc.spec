# -*- mode: python ; coding: utf-8 -*-
"""Build the pywebview desktop app; mutable user data stays outside app/."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = collect_data_files("webview") + [
    (str(root / "backend" / "assets"), "assets"),
    (str(root / "frontend"), "frontend"),
]
for distribution in ("typesafe-sdk", "openai", "yt-dlp", "playwright", "keyring", "pywebview"):
    datas += copy_metadata(distribution)

# Keep the original webview/lib/ hierarchy, including per-architecture WebView2Loader.dll.
binaries = collect_dynamic_libs("webview")
binaries += collect_dynamic_libs("clr_loader")
datas += collect_data_files("pythonnet")
binaries += collect_dynamic_libs("pythonnet")
hiddenimports = (
    collect_submodules("backend")
    + ["keyring.backends.Windows", "win32ctypes",
       "webview.platforms.edgechromium", "webview.platforms.winforms", "clr_loader", "pythonnet"]
    + collect_submodules("win32ctypes")
)

a = Analysis(
    [str(root / "backend" / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit", "pandas", "pyarrow", "altair", "matplotlib", "tkinter",
              "faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers",
              "huggingface_hub", "hf_xet"],
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
    console=False,  # Nhật ký ghi vào data/app.log (backend/main.py).
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
