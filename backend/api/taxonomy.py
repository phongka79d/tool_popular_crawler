"""Editable Jev classification labels."""
from backend.core import config
from backend.api.common import fail

_TAXONOMY_NOTES = {
    "topic": "Jev trả lời: video/bài này nói về chuyện gì? Kết quả nằm ở cột Nhóm chủ đề trong Excel và dùng để gom nhóm ở trang Tổng hợp công thức.",
    "hook_type": "Jev trả lời: câu mở đầu (hook) thuộc kiểu nào? Kết quả nằm ở cột Kiểu hook. Gợi ý của LLM phải giữ kiểu hook hoặc cấu trúc của video gốc; Jev dùng nhãn này để duyệt gợi ý.",
    "structure": "Jev trả lời: nội dung được sắp xếp theo trình tự nào? (mở – thân – kết). Kết quả nằm ở cột Cấu trúc và cũng dùng để duyệt gợi ý như kiểu hook.",
    "cta": "Jev trả lời: cuối video/bài kêu gọi người xem làm gì? Kết quả nằm ở cột CTA.",
}
_INTRO = [
    "Tên hiển thị: chữ bạn thấy trong Excel. Đổi tên không làm Jev chấm lại.",
    "Mô tả cho Jev: Jev dựa vào ô này để quyết định chọn nhãn. Viết cụ thể, có ví dụ thật, và nói rõ ranh giới với nhãn gần giống; mô tả mơ hồ khiến Jev hay ghi (chưa chắc).",
    'Thêm dòng: thêm lựa chọn mới (ví dụ chủ đề "Mỹ phẩm"). Xóa dòng: nội dung kiểu đó sẽ rơi vào nhãn gần nhất hoặc Khác.',
    "Thêm, xóa hoặc sửa mô tả rồi bấm Lưu nhãn thì ở lần quét sau Jev chấm lại mọi nội dung (kể cả nội dung đã chấm), tốn thêm một ít phí Jev.",
    "Nhãn không ảnh hưởng tới lượt xem, việc lọc ngưỡng hay các câu chấm điểm khác (độ mạnh hook, liên quan ngành, rủi ro…).",
]


def get_taxonomy() -> dict:
    taxonomy = config.load_taxonomy()
    return {"ok": True, "groups": [
        {"id": group, "title": title, "note": _TAXONOMY_NOTES[group],
         "rows": config.taxonomy_rows(taxonomy, group),
         "fixed": [taxonomy["labels"][code] for code in ("khong_co", "khac") if code in taxonomy[group]]}
        for group, title in config.TAXONOMY_GROUPS.items()], "intro": list(_INTRO)}


def save_taxonomy(groups: dict) -> dict:
    try:
        config.save_taxonomy(groups)
    except (ValueError, OSError) as exc:
        return fail(str(exc))
    return {"ok": True, "message": "Đã lưu nhãn phân loại Jev."}


def reset_taxonomy() -> dict:
    try:
        config.reset_taxonomy()
    except OSError as exc:
        return fail(str(exc))
    return {"ok": True, "message": "Đã khôi phục nhãn mặc định."}
