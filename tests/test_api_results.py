from datetime import datetime
from pathlib import Path

import pytest
from backend.api import results, scan


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(results.config, "OUTPUT_DIR", output)
    monkeypatch.setattr(results, "_cache", results.OrderedDict())
    monkeypatch.setattr(scan, "_session", scan._new_session())
    return output


def test_summary_views_topics_scores(monkeypatch, output_dir):
    (output_dir / "report.xlsx").touch()
    data = {"kind": "video", "created": datetime(2026, 10, 12, 10, 30), "items": [
        {"title": "A", "views": 100, "topic": "Dược", "score": 19, "page": "One"},
        {"title": "B", "views": 200, "topic": "Dược", "score": 80, "page": "Two"},
        {"title": "C", "views": None, "topic": "", "score": None, "page": "One"}]}
    monkeypatch.setattr(results.export_excel, "read_summary", lambda path: data)
    summary = results.get_result_summary("report.xlsx")["summary"]
    assert [row["value"] for row in summary["top"]] == [200, 100]
    assert sum(row["value"] for row in summary["topics"]) == 3
    assert next(row["value"] for row in summary["topics"] if row["label"] == "Dược") == 2
    assert sum(row["value"] for row in summary["distribution"]) == 2
    assert (summary["count"], summary["pages"], summary["reach"], summary["avg_score"]) == (3, 2, 300, 49.5)
    assert summary["created"] == "12/10/2026 10:30" and summary["has_scores"]


def test_posts_use_interactions_limit_top():
    items = [{"title": "Trùng tiêu đề", "views": 1000 - index, "interactions": index,
              "topic": "A", "score": 50} for index in range(12)]
    summary = results._summary({"kind": "post", "items": items})
    assert summary["metric_label"] == "Tương tác"
    assert len(summary["top"]) == 10
    assert [row["value"] for row in summary["top"]] == list(range(11, 1, -1))
    assert len({row["label"] for row in summary["top"]}) == 10
    assert summary["reach"] == sum(range(12))


def test_missing_metrics_not_zero():
    summary = results._summary({"items": [{"title": "A"}]})
    assert summary["reach"] is None and summary["avg_score"] is None
    assert summary["has_scores"] is False
    assert results._summary({}) is None


def test_file_summary_path_mtime_cache_key(monkeypatch, output_dir):
    path = output_dir / "test.xlsx"
    path.write_bytes(b"example")
    calls = []
    def cached(name, mtime):
        calls.append((name, mtime))
        return {"count": 3}
    monkeypatch.setattr(results, "_cached_summary", cached)
    assert results._file_summary(path) == {"count": 3}
    assert calls == [(str(path.resolve()), path.stat().st_mtime_ns)]
    assert results._file_summary(output_dir / "missing.xlsx") == {}
    assert results.summary_count(path) == 3


def test_cache_reuses_only_matching_path_and_mtime(monkeypatch, output_dir):
    calls = []
    monkeypatch.setattr(results.export_excel, "read_summary", lambda path: calls.append(path) or {"count": len(calls)})
    first = results._cached_summary(str(output_dir / "a.xlsx"), 1)
    first["count"] = 999
    assert results._cached_summary(str(output_dir / "a.xlsx"), 1)["count"] == 1
    assert results._cached_summary(str(output_dir / "a.xlsx"), 2)["count"] == 2
    assert results._cached_summary(str(output_dir / "b.xlsx"), 2)["count"] == 3


@pytest.mark.parametrize("name", ["rapport.xlsx", "RAPPORT.XLSX"])
def test_safe_excel_accepts_plain_files(output_dir, name):
    assert results._named_path(name) == (output_dir / name).resolve()


@pytest.mark.parametrize("name", ["../rapport.xlsx", "../output_elsewhere/rapport.xlsx", "rapport.csv",
                                  "rapport.xlsx.exe", ".", "nested/rapport.xlsx", "nested/../rapport.xlsx",
                                  "nested\\rapport.xlsx", "C:\\rapport.xlsx", "rapport.xlsx:stream", ""])
def test_safe_excel_rejects_traversal_extensions_and_nested_names(output_dir, name):
    with pytest.raises(ValueError):
        results._named_path(name)
    assert not results.get_result_summary(name)["ok"]


@pytest.mark.parametrize("relative", ["../rapport.xlsx", "nested/rapport.xlsx", "rapport.csv", "."])
def test_safe_excel_path_rejects_outside_and_nested(output_dir, relative):
    with pytest.raises(ValueError):
        results._safe_excel_path(output_dir / relative, output_dir)


def test_safe_excel_checks_resolved_target(monkeypatch, output_dir):
    link, outside = output_dir / "link.xlsx", output_dir.parent / "outside.xlsx"
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        outside if path == link else original(path, *args, **kwargs))
    with pytest.raises(ValueError):
        results._named_path("link.xlsx")


def test_delete_only_selected_and_clears_scan_result(output_dir):
    target, other = output_dir / "selected.xlsx", output_dir / "other.xlsx"
    target.write_bytes(b"selected")
    other.write_bytes(b"other")
    scan._session["scan_result"] = str(target)
    assert results.delete_result(target.name)["ok"]
    assert not target.exists() and other.read_bytes() == b"other"
    assert not scan.has_result()


def test_delete_locked_file_preserved(monkeypatch, output_dir):
    target = output_dir / "locked.xlsx"
    target.write_bytes(b"locked")
    def locked(path):
        raise PermissionError("locked")
    monkeypatch.setattr(Path, "unlink", locked)
    response = results.delete_result(target.name)
    assert response == {"ok": False, "error": "Không xóa được vì file đang mở hoặc bị khóa. Đóng file trong Excel rồi thử lại."}
    assert target.read_bytes() == b"locked"


def test_save_copy_refuses_same_path_and_preserves_source(output_dir, tmp_path):
    source = output_dir / "report.xlsx"
    source.write_bytes(b"content")
    assert not results.save_result_copy(source.name, str(source))["ok"]
    dest = tmp_path / "copy.xlsx"
    assert results.save_result_copy(source.name, str(dest))["ok"]
    assert source.read_bytes() == dest.read_bytes() == b"content"


def test_open_file_and_folder(monkeypatch, output_dir):
    target = output_dir / "report.xlsx"
    target.touch()
    opened = []
    monkeypatch.setattr(results.os, "startfile", opened.append, raising=False)
    assert results.open_result(target.name)["ok"]
    assert results.open_output_folder()["ok"]
    assert opened == [target.resolve(), output_dir]
    assert not results.open_result("missing.xlsx")["ok"]
    assert not results.open_result("../outside.xlsx")["ok"]


def test_list_results_newest_first_excludes_unsafe_files(monkeypatch, output_dir):
    first, second = output_dir / "a.xlsx", output_dir / "b.XLSX"
    first.write_bytes(b"a")
    second.write_bytes(b"bb")
    (output_dir / "ignore.csv").touch()
    (output_dir / "folder.xlsx").mkdir()
    import os
    os.utime(first, (10, 10))
    os.utime(second, (20, 20))
    response = results.list_results()
    assert [row["name"] for row in response["files"]] == ["b.XLSX", "a.xlsx"]
    assert response["folder"] == str(output_dir)
    assert all(row["modified"] and row["size_text"] for row in response["files"])
