"""Offline tests for db.py: upsert idempotence, transcript preservation, cache roundtrips."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import db
from models import Page, Video


@pytest.fixture
def path(tmp_path: Path) -> Path:
    db_file = tmp_path / "cache.db"
    db.init_db(db_file)
    return db_file


def _video(**overrides) -> Video:
    fields = dict(
        video_id="v1",
        url="https://www.facebook.com/reel/1",
        page_url="https://www.facebook.com/pagea",
        page_name="Page A",
        page_followers=150_000,
        posted_at=1_760_000_000,
        format="reel",
        duration_s=42.0,
        views=60_000,
        reactions=900,
        comments=40,
        shares=25,
        caption="Caption gốc",
    )
    fields.update(overrides)
    return Video(**fields)


def test_init_db_creates_tables_and_is_idempotent(path: Path) -> None:
    db.init_db(path)  # second call must not fail
    with db.conn(path) as c:
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"pages", "videos", "jev_answers", "llm_outputs", "runs"} <= names


def test_conn_creates_missing_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir" / "x.db"
    db.init_db(nested)
    assert nested.exists()


def test_upsert_video_is_idempotent(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.upsert_video(_video(), path=path)
    with db.conn(path) as c:
        count = c.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    assert count == 1
    stored = db.get_video("v1", path=path)
    assert stored is not None
    assert stored.caption == "Caption gốc"
    assert stored.views == 60_000


def test_upsert_video_updates_metrics(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.upsert_video(_video(views=75_000, reactions=1_200, comments=55, shares=31), path=path)
    stored = db.get_video("v1", path=path)
    assert stored is not None
    assert (stored.views, stored.reactions, stored.comments, stored.shares) == (75_000, 1_200, 55, 31)


def test_upsert_video_updates_caption_when_non_empty(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.upsert_video(_video(caption="Caption mới"), path=path)
    stored = db.get_video("v1", path=path)
    assert stored is not None and stored.caption == "Caption mới"


def test_upsert_video_keeps_stored_values_when_incoming_empty(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.upsert_video(_video(caption="", views=None, page_followers=None), path=path)
    stored = db.get_video("v1", path=path)
    assert stored is not None
    assert stored.caption == "Caption gốc"
    assert stored.views == 60_000
    assert stored.page_followers == 150_000


def test_upsert_video_never_erases_transcript_or_hook(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.save_transcript("v1", "Xin chào các dược sĩ", "ok", "Xin chào các dược sĩ", path=path)
    # A fresh scan carries no transcript or hook yet.
    db.upsert_video(_video(transcript="", transcript_status="", hook=""), path=path)
    assert db.get_transcript("v1", path=path) == ("Xin chào các dược sĩ", "ok")
    stored = db.get_video("v1", path=path)
    assert stored is not None
    assert stored.hook == "Xin chào các dược sĩ"


def test_save_transcript_with_empty_text_keeps_stored_transcript(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.save_transcript("v1", "Nội dung thoại", "ok", "Hook cũ", path=path)
    db.save_transcript("v1", "", "failed", "", path=path)
    assert db.get_transcript("v1", path=path) == ("Nội dung thoại", "ok")
    stored = db.get_video("v1", path=path)
    assert stored is not None and stored.hook == "Hook cũ"


def test_save_transcript_status_recorded_when_no_text_stored(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    db.save_transcript("v1", "", "no_speech", "", path=path)
    assert db.get_transcript("v1", path=path) == ("", "no_speech")


def test_get_transcript_none_until_transcribed(path: Path) -> None:
    db.upsert_video(_video(), path=path)
    assert db.get_transcript("v1", path=path) is None
    assert db.get_transcript("unknown", path=path) is None


def test_get_video_roundtrip_and_missing(path: Path) -> None:
    assert db.get_video("missing", path=path) is None
    db.upsert_video(_video(), path=path)
    stored = db.get_video("v1", path=path)
    assert stored == Video(
        video_id="v1",
        url="https://www.facebook.com/reel/1",
        page_url="https://www.facebook.com/pagea",
        page_name="Page A",
        page_followers=150_000,
        posted_at=1_760_000_000,
        format="reel",
        duration_s=42.0,
        views=60_000,
        reactions=900,
        comments=40,
        shares=25,
        caption="Caption gốc",
    )


def test_upsert_page_keeps_name_and_followers_when_incoming_empty(path: Path) -> None:
    db.upsert_page(Page(url="https://www.facebook.com/pagea", name="Page A", followers=1000), path=path)
    db.upsert_page(Page(url="https://www.facebook.com/pagea", name="", followers=None), path=path)
    with db.conn(path) as c:
        row = c.execute("SELECT name, followers FROM pages WHERE url = ?",
                        ("https://www.facebook.com/pagea",)).fetchone()
    assert (row["name"], row["followers"]) == ("Page A", 1000)


def test_jev_cache_roundtrip(path: Path) -> None:
    answers = {"topic": "kien_thuc_benh", "relevant": 0.91, "note": "Tiếng Việt có dấu"}
    usage = {"tokens": 321}
    db.save_jev("v1", "jev-1.13", "labels", answers, usage, path=path)

    assert db.get_jev("v1", "jev-1.13", "labels", path=path) == answers
    assert db.get_jev("v1", "jev-1.14", "labels", path=path) is None
    assert db.get_jev("v1", "jev-1.13", "suggestion_check", path=path) is None
    assert db.get_jev("v2", "jev-1.13", "labels", path=path) is None


def test_jev_save_again_replaces_answers(path: Path) -> None:
    db.save_jev("v1", "jev-1.13", "labels", {"relevant": 0.2}, {}, path=path)
    db.save_jev("v1", "jev-1.13", "labels", {"relevant": 0.8}, {"tokens": 5}, path=path)
    assert db.get_jev("v1", "jev-1.13", "labels", path=path) == {"relevant": 0.8}
    with db.conn(path) as c:
        count = c.execute("SELECT COUNT(*) FROM jev_answers").fetchone()[0]
    assert count == 1


def test_jev_kind_must_be_known(path: Path) -> None:
    with pytest.raises(ValueError):
        db.save_jev("v1", "jev-1.13", "bogus", {}, {}, path=path)
    with pytest.raises(ValueError):
        db.get_jev("v1", "jev-1.13", "bogus", path=path)


def test_llm_cache_roundtrip(path: Path) -> None:
    output = {
        "chu_de_bai": "Dấu hiệu nhận biết bệnh",
        "goi_y_nhan_ban": [{"hook_moi": "Chủ nhà thuốc nào cũng…", "y_tuong": "Kể tình huống"}],
        "_usage": 812,
    }
    db.save_llm("v1", "model-x", output, path=path)
    assert db.get_llm("v1", path=path) == output
    assert db.get_llm("v2", path=path) is None

    db.save_llm("v1", "model-y", {"chu_de_bai": "Mới"}, path=path)
    assert db.get_llm("v1", path=path) == {"chu_de_bai": "Mới"}


def test_run_log_roundtrip(path: Path) -> None:
    params = {"days": 14, "formats": {"video", "reel"}, "preset": "no_bat_thuong"}
    run_id = db.start_run(params, path=path)
    assert isinstance(run_id, int)

    db.finish_run(run_id, {"messages": ["Hoàn tất"], "usage": {"jev_tokens": 10}}, path=path)

    with db.conn(path) as c:
        row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["finished_at"] is not None
    assert json.loads(row["params_json"]) == {
        "days": 14,
        "formats": ["reel", "video"],  # sets are stored as sorted lists
        "preset": "no_bat_thuong",
    }
    assert json.loads(row["log_json"])["usage"] == {"jev_tokens": 10}


def test_finish_run_rejects_unknown_run_id(path: Path) -> None:
    with pytest.raises(ValueError):
        db.finish_run(9999, {}, path=path)
