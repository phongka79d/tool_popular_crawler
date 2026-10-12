"""Offline tests for export_excel.py: sheets, header order, sort, risk fill, formats, filename."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

import export_excel as xl
from models import Video

NOW = datetime(2026, 10, 12, 9, 5)

HEADERS = [
    "STT", "Kênh", "Follower kênh", "Ngày đăng", "Định dạng", "Thời lượng (giây)", "Link bài",
    "View", "Cảm xúc", "Bình luận", "Chia sẻ", "View/Follower", "Hệ số so trung vị kênh",
    "Tỷ lệ tương tác", "Tỷ lệ share",
    "Chủ đề bài", "Tóm tắt", "Caption", "Nội dung thoại", "Hook gốc",
    "Nhóm chủ đề", "Kiểu hook", "Độ mạnh hook", "Cấu trúc", "CTA",
    "Liên quan ngành (%)", "Làm lại được (%)", "Điểm công thức (0–100)", "Cờ rủi ro",
    "Lý do viral", "Gợi ý 1", "Gợi ý 2", "Gợi ý 3",
    "Ghi chú",
]

CAPTION_B = '=HYPERLINK("http://x","bấm") Khỏi hẳn bệnh'

SUMMARY = {
    "by_topic": [
        {"label": "Kiến thức bệnh", "count": 2, "avg_views": 70_000, "avg_score": 62.5},
        {"label": "Pháp lý GPP", "count": 1, "avg_views": None, "avg_score": 90.0},
    ],
    "by_hook": [
        {"label": "Câu hỏi", "count": 2, "avg_views": 70_000, "avg_score": 62.5},
    ],
    "commentary": "Công thức câu hỏi đang thắng.",
}

RUN_LOG = {
    "started_at": 1_760_000_000,
    "finished_at": "2026-10-12 09:04:00",
    "params": {
        "days": 14,
        "formats": {"video", "reel"},
        "min_page_followers": 100_000,
        "rules": {"ratio_median": 3},
        "preset": "no_bat_thuong",
    },
    "pages": [
        {"url": "https://fb/p1", "name": "Kênh A", "followers": 200_000, "scanned": 40,
         "passed": 3, "analyzed": 3, "skipped_reason": None, "errors": []},
        {"url": "https://fb/p2", "name": "Kênh C", "followers": 5_000, "scanned": 0,
         "passed": 0, "analyzed": 0, "skipped_reason": "Follower 5.000 dưới ngưỡng 100.000",
         "errors": []},
        {"url": "https://fb/p3", "name": "", "followers": None, "scanned": 2,
         "passed": 0, "analyzed": 0, "skipped_reason": None,
         "errors": ["Không kết nối được tới Facebook"]},
    ],
    "usage": {"jev_tokens": 12_345, "llm_tokens": 6_789, "deepgram_minutes": 3.5},
    "messages": ["Đã dùng cache cho 2 video"],
}


def _videos() -> list[Video]:
    # Input order is deliberately not the score order, and one video has no score.
    return [
        Video(
            video_id="c", url="https://www.facebook.com/reel/c",
            page_url="https://www.facebook.com/kenhc", page_name="Kênh C",
            page_followers=90_000, posted_at=None, format="video", views=1_000,
            caption="Nội dung không có điểm", score=None,
            jev={},
            llm={"_raw": "Không phải JSON: {oops"},
        ),
        Video(
            video_id="b", url="https://www.facebook.com/reel/b",
            page_url="https://www.facebook.com/kenhb", page_name="Kênh B",
            page_followers=300_000, posted_at=1_760_000_000, format="video",
            duration_s=55.0, views=120_000, reactions=2_500, comments=300, shares=900,
            ratio_follow=0.4, ratio_median=5.0, engagement=0.03, share_rate=0.0075,
            caption=CAPTION_B, transcript="", transcript_status="failed", hook="Khỏi hẳn bệnh",
            score=90.0,
            jev={
                "topic": "Pháp lý GPP (chưa chắc)", "hook_type": "Cảnh báo sai lầm",
                "hook_strength": 1, "structure": "Liệt kê mẹo", "cta": "Bình luận",
                "relevant_p": 0.95, "replicable_p": 0.7,
                "risk_flags": ["Khẳng định tuyệt đối", "So sánh đối thủ"],
                "uncertain": ["topic"],
            },
            notes=["Chưa đủ 5 video để tính trung vị"],
            llm={"chu_de_bai": "Cảnh báo sai lầm", "tom_tat": "Tóm tắt B"},
        ),
        Video(
            video_id="a", url="https://www.facebook.com/reel/a",
            page_url="https://www.facebook.com/kenha", page_name="Kênh A",
            page_followers=200_000, posted_at=1_760_000_000, format="reel",
            duration_s=30.0, views=80_000, reactions=1_000, comments=50, shares=40,
            ratio_follow=0.4, ratio_median=3.2, engagement=0.03, share_rate=0.0005,
            caption="Bạn có biết dấu hiệu này không?", transcript="Thoại A",
            transcript_status="ok", hook="Bạn có biết", score=55.0,
            jev={
                "topic": "Kiến thức bệnh", "hook_type": "Câu hỏi", "hook_strength": 2,
                "structure": "Vấn đề - giải pháp", "cta": "Inbox", "relevant_p": 0.9,
                "replicable_p": 0.8, "risk_flags": [], "uncertain": [],
            },
            llm={
                "chu_de_bai": "Dấu hiệu nhận biết bệnh",
                "tom_tat": "Tóm tắt A",
                "hook_goc": "Bạn có biết…",
                "ly_do_viral": "Giả thuyết A",
                "goi_y_nhan_ban": [
                    {"hook_moi": "Chủ nhà thuốc nào cũng…", "y_tuong": "Kể tình huống"},
                    {"hook_moi": "H2", "y_tuong": "Y2"},
                    {"hook_moi": "H3", "y_tuong": "Y3"},
                ],
            },
        ),
        Video(
            video_id="d", url="https://www.facebook.com/reel/d",
            page_url="https://www.facebook.com/kenhd", page_name="Kênh D",
            page_followers=120_000, posted_at=1_760_000_000, format="reel",
            views=70_000, score=70.0, caption="Chia sẻ mẹo nhỏ",
            jev={
                "topic": "Kiến thức bệnh", "hook_type": "Câu hỏi", "hook_strength": 1,
                "structure": "Liệt kê mẹo", "cta": "Lưu", "relevant_p": 0.7,
                "replicable_p": 0.6, "risk_flags": [], "uncertain": [],
            },
        ),
    ]


@pytest.fixture
def exported(tmp_path: Path) -> Path:
    return xl.export(_videos(), SUMMARY, RUN_LOG, out_dir=tmp_path, now=NOW)


@pytest.fixture
def wb(exported: Path):
    return load_workbook(exported)


@pytest.fixture
def detail(wb):
    return wb["Chi tiết video"]


def _col(header: str) -> int:
    return HEADERS.index(header) + 1


def _find_row(ws, text: str, column: int = 1) -> int:
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, column).value == text:
            return r
    raise AssertionError(f"không thấy {text!r} trong cột {column}")


def _width(ws, column: int) -> float | None:
    # openpyxl groups adjacent equal-width columns on save, so look up by range.
    for dim in ws.column_dimensions.values():
        if dim.min is not None and dim.max is not None and dim.min <= column <= dim.max:
            return dim.width
    return None


def test_filename_matches_pattern(exported: Path, tmp_path: Path) -> None:
    assert exported.name == "cong-thuc_2026-10-12_0905.xlsx"
    assert re.fullmatch(r"cong-thuc_\d{4}-\d{2}-\d{2}_\d{4}\.xlsx", exported.name)
    assert exported.parent == tmp_path


def test_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    first = xl.export([], {}, {}, out_dir=tmp_path, now=NOW)
    second = xl.export([], {}, {}, out_dir=tmp_path, now=NOW)
    assert first.name == "cong-thuc_2026-10-12_0905.xlsx"
    assert second.name == "cong-thuc_2026-10-12_0905_2.xlsx"
    assert first.exists() and second.exists()


def test_sheet_names_in_order(wb) -> None:
    assert wb.sheetnames == ["Chi tiết video", "Tổng hợp công thức", "Nhật ký"]


def test_detail_header_order_matches_plan(detail) -> None:
    assert detail.max_column == len(HEADERS) == 34
    assert [detail.cell(1, c).value for c in range(1, len(HEADERS) + 1)] == HEADERS


def test_rows_sorted_by_score_desc_with_missing_score_last(detail) -> None:
    assert detail.max_row == 5
    assert [detail.cell(r, _col("STT")).value for r in range(2, 6)] == [1, 2, 3, 4]
    assert [detail.cell(r, _col("Kênh")).value for r in range(2, 6)] == [
        "Kênh B", "Kênh D", "Kênh A", "Kênh C",
    ]
    assert [detail.cell(r, _col("Điểm công thức (0–100)")).value for r in range(2, 6)] == [
        90.0, 70.0, 55.0, None,
    ]


def test_freeze_panes_and_autofilter(detail) -> None:
    assert detail.freeze_panes == "C2"
    assert detail.auto_filter.ref == "A1:AH5"


def test_risky_row_has_light_yellow_fill(detail) -> None:
    risky_row = 2  # Kênh B: has risk flags, score 90
    for c in range(1, len(HEADERS) + 1):
        cell = detail.cell(risky_row, c)
        assert cell.fill.fill_type == "solid", cell.coordinate
        assert cell.fill.fgColor.rgb[-6:] == "FFF2CC", cell.coordinate


def test_clean_row_has_no_fill(detail) -> None:
    clean_row = 3  # Kênh D: no risk flags
    assert detail.cell(clean_row, _col("Kênh")).fill.fill_type is None


def test_number_and_percent_formats(detail) -> None:
    row = 2  # Kênh B: has every metric filled in
    assert detail.cell(row, _col("View")).number_format == "#,##0"
    assert detail.cell(row, _col("Follower kênh")).number_format == "#,##0"
    assert detail.cell(row, _col("Thời lượng (giây)")).number_format == "#,##0"
    assert detail.cell(row, _col("View/Follower")).number_format == "0.0%"
    assert detail.cell(row, _col("View/Follower")).value == pytest.approx(0.4)
    assert detail.cell(row, _col("Hệ số so trung vị kênh")).number_format == "0.0%"
    assert detail.cell(row, _col("Tỷ lệ tương tác")).number_format == "0.0%"
    assert detail.cell(row, _col("Tỷ lệ share")).number_format == "0.00%"
    assert detail.cell(row, _col("Tỷ lệ share")).value == pytest.approx(0.0075)
    assert detail.cell(row, _col("Liên quan ngành (%)")).number_format == "0%"
    assert detail.cell(row, _col("Liên quan ngành (%)")).value == pytest.approx(0.95)
    assert detail.cell(row, _col("Làm lại được (%)")).number_format == "0%"
    assert detail.cell(row, _col("Điểm công thức (0–100)")).number_format == "#,##0.0"


def test_long_text_columns_wrap_at_width_60(detail) -> None:
    for header in ("Tóm tắt", "Caption", "Nội dung thoại", "Hook gốc", "Gợi ý 1", "Ghi chú"):
        col = _col(header)
        assert _width(detail, col) == 60, header
        assert detail.cell(2, col).alignment.wrap_text is True, header


def test_short_columns_keep_default_width_without_wrap(detail) -> None:
    col = _col("Kênh")
    assert _width(detail, col) == 24
    assert not detail.cell(2, col).alignment.wrap_text


def test_formula_like_caption_stays_literal_text(detail) -> None:
    assert detail.cell(2, _col("Caption")).value == CAPTION_B


def test_detail_values_map_from_jev_llm_and_metrics(detail) -> None:
    row = 4  # Kênh A
    assert detail.cell(row, _col("Ngày đăng")).value == datetime(2025, 10, 9, 15, 53, 20)
    assert detail.cell(row, _col("Định dạng")).value == "Reel"
    assert detail.cell(row, _col("Chủ đề bài")).value == "Dấu hiệu nhận biết bệnh"
    assert detail.cell(row, _col("Hook gốc")).value == "Bạn có biết…"
    assert detail.cell(row, _col("Độ mạnh hook")).value == 2
    assert detail.cell(row, _col("Nhóm chủ đề")).value == "Kiến thức bệnh"
    assert detail.cell(row, _col("CTA")).value == "Inbox"
    assert detail.cell(row, _col("Lý do viral")).value == "Giả thuyết A"
    assert detail.cell(row, _col("Gợi ý 1")).value == (
        "Hook: Chủ nhà thuốc nào cũng…\nÝ tưởng: Kể tình huống"
    )
    assert detail.cell(row, _col("Gợi ý 3")).value == "Hook: H3\nÝ tưởng: Y3"
    assert detail.cell(row, _col("Ghi chú")).value is None


def test_risk_flags_uncertain_labels_and_failed_transcript_in_notes(detail) -> None:
    row = 2  # Kênh B
    assert detail.cell(row, _col("Cờ rủi ro")).value == "Khẳng định tuyệt đối, So sánh đối thủ"
    assert detail.cell(row, _col("Nhóm chủ đề")).value == "Pháp lý GPP (chưa chắc)"
    notes = detail.cell(row, _col("Ghi chú")).value
    assert notes.splitlines() == [
        "Chưa đủ 5 video để tính trung vị",
        "Nhãn chưa chắc: Nhóm chủ đề",
        "Chưa lấy được thoại",
    ]


def test_missing_jev_llm_fields_are_blank_and_raw_goes_to_notes(detail) -> None:
    row = 5  # Kênh C: no score, empty jev, raw LLM text only
    assert detail.cell(row, _col("Điểm công thức (0–100)")).value is None
    assert detail.cell(row, _col("Chủ đề bài")).value is None
    assert detail.cell(row, _col("Gợi ý 1")).value is None
    assert detail.cell(row, _col("Ngày đăng")).value is None
    notes = detail.cell(row, _col("Ghi chú")).value
    assert "Không phải JSON: {oops" in notes


def test_empty_export_still_writes_three_sheets(tmp_path: Path) -> None:
    path = xl.export([], {}, {}, out_dir=tmp_path, now=NOW)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Chi tiết video", "Tổng hợp công thức", "Nhật ký"]
    assert wb["Chi tiết video"].max_row == 1


def test_summary_sheet_tables_and_commentary(wb) -> None:
    ws = wb["Tổng hợp công thức"]
    topic_title = _find_row(ws, "Bảng 1 – Theo nhóm chủ đề")
    assert [ws.cell(topic_title + 1, c).value for c in range(1, 5)] == [
        "Nhóm chủ đề", "Số video", "View trung bình", "Điểm công thức trung bình",
    ]
    assert [ws.cell(topic_title + 2, c).value for c in range(1, 5)] == [
        "Kiến thức bệnh", 2, 70_000, 62.5,
    ]
    assert ws.cell(topic_title + 2, 3).number_format == "#,##0"
    assert ws.cell(topic_title + 2, 4).number_format == "#,##0.0"
    assert [ws.cell(topic_title + 3, c).value for c in range(1, 5)] == [
        "Pháp lý GPP", 1, None, 90.0,
    ]

    hook_title = _find_row(ws, "Bảng 2 – Theo kiểu hook")
    assert ws.cell(hook_title + 2, 1).value == "Câu hỏi"

    note = _find_row(ws, "Nhận xét")
    assert ws.cell(note + 1, 1).value == "Công thức câu hỏi đang thắng."


def test_run_log_sheet_contents(wb) -> None:
    ws = wb["Nhật ký"]
    assert ws.cell(_find_row(ws, "Kết thúc"), 2).value == "2026-10-12 09:04:00"
    assert isinstance(ws.cell(_find_row(ws, "Bắt đầu"), 2).value, str)

    assert ws.cell(_find_row(ws, "Follower tối thiểu của page"), 2).value == 100_000
    assert ws.cell(_find_row(ws, "Preset"), 2).value == "no_bat_thuong"

    skipped = _find_row(ws, "Kênh C")
    assert ws.cell(skipped, 7).value == "Follower 5.000 dưới ngưỡng 100.000"
    failed = _find_row(ws, "https://fb/p3")
    assert ws.cell(failed, 8).value == "Không kết nối được tới Facebook"

    usage_title = _find_row(ws, "Sử dụng")
    assert [ws.cell(usage_title + 1, c).value for c in range(1, 4)] == [
        "Token Jev", "Token LLM", "Phút Deepgram",
    ]
    assert [ws.cell(usage_title + 2, c).value for c in range(1, 4)] == [12_345, 6_789, 3.5]
    assert ws.cell(usage_title + 2, 1).number_format == "#,##0"
    assert ws.cell(usage_title + 2, 3).number_format == "#,##0.00"

    message_row = _find_row(ws, "Đã dùng cache cho 2 video", column=2)
    assert ws.cell(message_row, 2).value == "Đã dùng cache cho 2 video"


def test_build_summary_tables_groups_and_averages() -> None:
    videos = [
        Video(video_id="1", url="", page_url="", views=100, score=60.0,
              jev={"topic": "Kiến thức bệnh (chưa chắc)", "hook_type": "Câu hỏi"}),
        Video(video_id="2", url="", page_url="", views=None, score=80.0,
              jev={"topic": "Kiến thức bệnh", "hook_type": "Câu hỏi"}),
        Video(video_id="3", url="", page_url="", views=50, score=None, jev={}),
    ]
    tables = xl.build_summary_tables(videos)
    assert tables == {
        "by_topic": [
            {"label": "Kiến thức bệnh", "count": 2, "avg_views": 100.0, "avg_score": 70.0},
            {"label": "Chưa gắn nhãn", "count": 1, "avg_views": 50.0, "avg_score": None},
        ],
        "by_hook": [
            {"label": "Câu hỏi", "count": 2, "avg_views": 100.0, "avg_score": 70.0},
            {"label": "Chưa gắn nhãn", "count": 1, "avg_views": 50.0, "avg_score": None},
        ],
        "commentary": "",
    }


def test_build_summary_tables_empty() -> None:
    assert xl.build_summary_tables([]) == {"by_topic": [], "by_hook": [], "commentary": ""}
