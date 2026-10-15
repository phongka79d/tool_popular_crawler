from pathlib import Path
from unittest.mock import Mock

import pytest

from backend import main
from backend.api import Bridge, app_state, channels, common, logs, results, scan, services, taxonomy


BRIDGE_CALLS = [
    ("get_app_state", app_state, ()),
    ("get_services", services, ()),
    ("connect_service", services, ("llm", "", "https://example.com")),
    ("save_service", services, ("llm", "", {})),
    ("check_keys", services, (False,)),
    ("reset_configuration", services, ()),
    ("get_channels", channels, ()),
    ("save_channels", channels, ("",)),
    ("start_login", channels, ()),
    ("get_login_state", channels, ()),
    ("get_taxonomy", taxonomy, ()),
    ("save_taxonomy", taxonomy, ({},)),
    ("reset_taxonomy", taxonomy, ()),
    ("get_logs", logs, (None, False)),
    ("open_log_file", logs, (None,)),
    ("get_scan_options", scan, ()),
    ("preview_scan", scan, ({},)),
    ("set_read_images", scan, (False,)),
    ("accept_terms", scan, ()),
    ("start_scan", scan, ({},)),
    ("stop_scan", scan, ()),
    ("answer_question", scan, ("continue",)),
    ("get_scan_state", scan, (0,)),
    ("list_results", results, ()),
    ("get_result_summary", results, ("result.xlsx",)),
    ("delete_result", results, ("result.xlsx",)),
    ("open_result", results, ("result.xlsx",)),
    ("open_output_folder", results, ()),
]


def _complete_bundle(path: Path) -> Path:
    for name in ("base_library.zip", "ffmpeg.exe", "frontend/index.html"):
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
    return path


def test_complete_bundle_has_no_problems(tmp_path):
    bundle = _complete_bundle(tmp_path)
    assert main.bundle_problems(bundle, Path("C:/VideoCongThuc/VideoCongThuc.exe")) == []


def test_partially_extracted_bundle_names_missing_files(tmp_path):
    bundle = _complete_bundle(tmp_path)
    (bundle / "ffmpeg.exe").unlink()
    (bundle / "frontend/index.html").unlink()
    assert main.bundle_problems(bundle, Path("C:/VideoCongThuc/VideoCongThuc.exe")) == [
        "thiếu app\\ffmpeg.exe", "thiếu app\\frontend\\index.html"
    ]


def test_bundle_requires_files_not_directories(tmp_path):
    bundle = _complete_bundle(tmp_path)
    (bundle / "ffmpeg.exe").unlink()
    (bundle / "ffmpeg.exe").mkdir()
    assert main.bundle_problems(bundle, Path("C:/VideoCongThuc/VideoCongThuc.exe")) == ["thiếu app\\ffmpeg.exe"]


@pytest.mark.parametrize("exe", [
    r"C:\Users\A\AppData\Local\Temp\Temp1_VideoCongThuc.zip\VideoCongThuc\VideoCongThuc.exe",
    r"C:\Users\A\AppData\Local\Temp\Rar$EXa1234.5678\VideoCongThuc\VideoCongThuc.exe",
    r"C:\Users\A\AppData\Local\Temp\7zO1234\VideoCongThuc\VideoCongThuc.exe",
])
def test_running_from_inside_zip_is_reported(tmp_path, exe):
    assert main.bundle_problems(_complete_bundle(tmp_path), Path(exe)) == [
        "đang chạy trực tiếp bên trong file ZIP"
    ]


def test_unreadable_bundle_dir_is_reported(tmp_path):
    problems = main.bundle_problems(tmp_path / "missing", Path("C:/VideoCongThuc/VideoCongThuc.exe"))
    assert len(problems) == 1 and problems[0].startswith("không đọc được thư mục")


def test_bridge_exposes_exact_contract_methods():
    expected = {name for name, _, _ in BRIDGE_CALLS} | {
        "pick_cookie_file_and_import", "save_result_as", "open_url"
    }
    bridge = Bridge()
    exposed = {
        name for name in dir(bridge)
        if not name.startswith("_") and callable(getattr(bridge, name))
        and getattr(getattr(bridge, name), "_serializable", True)
    }
    assert exposed == expected
    assert callable(bridge.attach)


@pytest.mark.parametrize("name,module,args", BRIDGE_CALLS, ids=[row[0] for row in BRIDGE_CALLS])
def test_bridge_delegates_and_converts_exceptions(monkeypatch, name, module, args):
    target = Mock(return_value={"ok": True, "message": "Đã xử lý"})
    monkeypatch.setattr(module, name, target)
    bridge = Bridge()
    assert getattr(bridge, name)(*args) == target.return_value
    target.assert_called_once_with(*args)
    failure = RuntimeError("Lỗi kiểm tra")
    target.side_effect = failure
    error_message = Mock(return_value="Thông báo đã che khóa")
    monkeypatch.setattr(common, "error_message", error_message)
    assert getattr(bridge, name)(*args) == {"ok": False, "error": "Thông báo đã che khóa"}
    error_message.assert_called_once_with(failure)


def test_cookie_dialog_imports_selected_file(monkeypatch):
    import webview

    bridge = Bridge()
    window = Mock()
    window.create_file_dialog.return_value = ("cookies.json",)
    bridge.attach(window)
    importer = Mock(return_value={"ok": True, "message": "Đã nhập cookie"})
    monkeypatch.setattr(channels, "import_cookies", importer)
    assert bridge.pick_cookie_file_and_import() == importer.return_value
    importer.assert_called_once_with("cookies.json")
    window.create_file_dialog.assert_called_once_with(
        webview.FileDialog.OPEN, allow_multiple=False, file_types=("Tệp cookie (*.json;*.txt)",)
    )


def test_save_dialog_copies_selected_result(monkeypatch):
    import webview

    bridge = Bridge()
    window = Mock()
    window.create_file_dialog.return_value = ("D:/copy.xlsx",)
    bridge.attach(window)
    saver = Mock(return_value={"ok": True})
    monkeypatch.setattr(results, "save_result_copy", saver)
    assert bridge.save_result_as("result.xlsx") == {"ok": True}
    saver.assert_called_once_with("result.xlsx", "D:/copy.xlsx")
    window.create_file_dialog.assert_called_once_with(
        webview.FileDialog.SAVE, save_filename="result.xlsx", file_types=("Bảng tính Excel (*.xlsx)",)
    )


@pytest.mark.parametrize("method,args", [("pick_cookie_file_and_import", ()), ("save_result_as", ("result.xlsx",))])
def test_cancelled_native_dialog_is_success(method, args):
    bridge = Bridge()
    window = Mock()
    window.create_file_dialog.return_value = None
    bridge.attach(window)
    assert getattr(bridge, method)(*args) == {"ok": True, "cancelled": True}


@pytest.mark.parametrize("url", ["file:///C:/private.txt", "javascript:alert(1)", "https:///missing-host"])
def test_open_url_rejects_non_web_links(monkeypatch, url):
    from backend import api

    opener = Mock()
    monkeypatch.setattr(api.webbrowser, "open", opener)
    assert Bridge().open_url(url)["ok"] is False
    opener.assert_not_called()


def test_open_url_uses_default_browser(monkeypatch):
    from backend import api

    opener = Mock(return_value=True)
    monkeypatch.setattr(api.webbrowser, "open", opener)
    assert Bridge().open_url("https://example.com/guide") == {"ok": True}
    opener.assert_called_once_with("https://example.com/guide")
