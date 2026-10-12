"""Client LLM (endpoint tương thích OpenAI): viết phần chữ của phân tích, gợi ý nhân bản, nhận xét tổng hợp.

LLM chỉ viết chữ. Nhãn Jev đã gắn được đưa vào prompt làm khung (PLAN-JEV.md mục 7).
"""
from __future__ import annotations

import base64
import io
import secrets
import json
import logging
import re
import unicodedata
from typing import Any

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageOps

from errors import AuthError, NetworkError, QuotaError, ServiceError
from models import Video
from retry import with_retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 120.0
JSON_RESPONSE_FORMAT = {"type": "json_object"}
# Đo trên gpt-6-luna: phân tích 1 bài 64,5 s mặc định → 14,6 s với "low", chất lượng tương đương.
# Đổi qua settings llm.reasoning_effort; "" để không gửi tham số này.
DEFAULT_REASONING_EFFORT = "low"


def reasoning_effort(settings: dict) -> str:
    return settings.get("llm", {}).get("reasoning_effort", DEFAULT_REASONING_EFFORT)


# Khung góc nhìn, mẫu hook điền chỗ trống và vị trí CTA lấy từ videoanalyzer SKILL.md Step 4 (MIT).
SYSTEM_PROMPT = """Bạn là biên tập viên content cho page B2B ngành dược (khách: chủ nhà thuốc, dược sĩ).
Đầu vào: caption, transcript và các nhãn đã gắn (chủ đề, kiểu hook, cấu trúc, CTA).
Giữ đúng các nhãn đó, không đặt nhãn mới. Viết tiếng Việt tự nhiên, không khẳng định tuyệt đối,
không so sánh đối thủ, không chép nguyên câu của video gốc.
Chỉ dùng nội dung có trong caption hoặc transcript. Không bịa nội dung, số liệu hay lời chứng thực
không có trong đầu vào. Nếu đầu vào không đủ để trả lời một khóa, ghi "không có dữ liệu" cho khóa đó.

Trả về JSON đúng các khóa:
{"chu_de_bai": "<= 12 chữ",
 "tom_tat": "2-3 câu",
 "hook_goc": "câu mở đầu của video",
 "ly_do_viral": "1-2 câu, nêu là giả thuyết",
 "goc_nhin": "1-2 câu theo khung 'Nhiều người nghĩ..., nhưng thực tế...'",
 "mau_hook_dien_cho_trong": "một mẫu câu mở đầu có chỗ trống [ ] để người khác điền và làm lại",
 "vi_tri_cta": "đầu, giữa hoặc cuối video, kèm cơ chế (mồi bình luận, inbox nhận tài liệu, lưu, chia sẻ); ghi 'không có CTA' nếu không kêu gọi",
 "goi_y_nhan_ban": [{"hook_moi": "", "y_tuong": ""}, ... đúng 3 mục]}"""

POST_SYSTEM_PROMPT = """Bạn là biên tập viên content cho page B2B ngành dược (khách: chủ nhà thuốc, dược sĩ).
Đầu vào là bài đăng chữ/ảnh: dùng caption, nội dung ảnh đã đọc (nếu có) và các nhãn Jev (chủ đề, kiểu hook, cấu trúc, CTA).
Giữ nguyên nhãn. Viết tiếng Việt tự nhiên; không khẳng định tuyệt đối, so sánh đối thủ hoặc chép nguyên câu bài gốc.
Không bịa nội dung, số liệu, lời chứng thực hay chi tiết trong ảnh không có trong đầu vào.
Thiếu dữ liệu cho khóa nào thì ghi "không có dữ liệu". Hook gốc là dòng đầu tiên của caption.
Lý do viral chỉ là giả thuyết dựa trên cách viết, không phải kết luận nhân quả.
Trả về JSON đúng các khóa:
{"chu_de_bai": "<= 12 chữ",
 "tom_tat": "2-3 câu",
 "hook_goc": "dòng đầu tiên của caption",
 "ly_do_viral": "1-2 câu, nêu là giả thuyết",
 "goc_nhin": "1-2 câu theo khung 'Nhiều người nghĩ..., nhưng thực tế...'",
 "mau_hook_dien_cho_trong": "mẫu mở bài có chỗ trống [ ]",
 "vi_tri_cta": "đầu, giữa hoặc cuối bài đăng, kèm cơ chế (bình luận, inbox, lưu, chia sẻ); ghi 'không có CTA' nếu không kêu gọi",
 "goi_y_nhan_ban": [{"hook_moi": "", "y_tuong": ""}, ... đúng 3 mục]}
Gợi ý là 3 ý tưởng bài đăng mới cho khách hàng của page, giữ kiểu hook hoặc cấu trúc bài gốc,
khác câu chữ và tình huống; y_tuong nêu rõ bố cục bài viết, không yêu cầu quay hay thu âm."""

RETRY_PROMPT = "Chỉ trả JSON đúng các khóa đã yêu cầu. Không thêm lời dẫn, không bọc trong khối mã."

COMMENTARY_SYSTEM_PROMPT = """Bạn viết nhận xét cho báo cáo "công thức đang thắng" của page B2B ngành dược (khách: chủ nhà thuốc, dược sĩ).
Đầu vào là hai bảng đếm đã tính sẵn dạng JSON: by_topic (theo nhóm chủ đề) và by_hook (theo kiểu hook).
Mỗi dòng có label, count (số nội dung), avg_views (lượt xem trung bình nếu có), avg_score (điểm công thức trung bình).
Viết 5-7 dòng tiếng Việt về công thức đang thắng: nhóm nào có chỉ số và điểm cao, kiểu hook nào nên thử,
và nêu rõ khi số nội dung còn ít thì kết luận còn yếu. Chỉ dựa trên số trong bảng, không bịa thêm.
Chỉ số thiếu/null không có nghĩa là 0; không suy ra lượt xem cho bài đăng khi bảng không có dữ liệu.
Mỗi dòng là một câu hoàn chỉnh, không đánh số, không gạch đầu dòng, không dùng emoji."""

_TABLE_FIELDS = ("label", "count", "avg_views", "avg_score")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_SUGGESTION_FIELDS = ("hook_moi", "y_tuong")


def make_client(base_url: str, api_key: str) -> OpenAI:
    """Client OpenAI trỏ tới endpoint của người dùng. Tắt retry của SDK để retry.with_retry quản lý."""
    return OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT_S)

def vision_cached(llm: dict) -> bool | None:
    cache = llm.get("vision", {})
    if cache.get("base_url") == llm.get("base_url") and cache.get("model") == llm.get("model"):
        return cache.get("ok") if isinstance(cache.get("ok"), bool) else None
    return None


def vision_error(model: str) -> str:
    return (f"Model LLM hiện tại ({model}) không nhận ảnh nên không dùng được tuỳ chọn này. "
            "Đổi sang model hỗ trợ ảnh ở Cài đặt.")


def _image_part(data: bytes, mime: str) -> dict:
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def check_vision(base_url: str, api_key: str, model: str) -> bool:
    """Probe actual image reading without exposing the random answer in the prompt."""
    number = str(secrets.randbelow(9000) + 1000)
    image = Image.new("RGB", (420, 140), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    draw.text((20, 15), "Đọc số trong ảnh", fill="black", font=font)
    draw.text((20, 70), number, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Đọc và trả lại đúng số có bốn chữ số trong ảnh."},
        _image_part(buffer.getvalue(), "image/png"),
    ]}]
    try:
        answer, _, _ = _chat(make_client(base_url, api_key), model, messages, None, False,
                             reasoning_effort({}))
    except (AuthError, QuotaError, NetworkError):
        raise
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        if status == 400 or any(word in str(exc).lower() for word in ("unsupported content", "image input", "vision not supported")):
            return False
        raise
    return re.search(rf"(?<!\d){number}(?!\d)", answer) is not None


def describe_images(client: OpenAI, model: str, images: list[bytes], caption: str,
                    reasoning_effort: str | None) -> str:
    """Read all post images in one request; never invent illegible image text."""
    content = [{"type": "text", "text": (
        "Đọc các ảnh theo thứ tự. Với từng ảnh, chép nguyên văn toàn bộ chữ nhìn thấy; "
        "chữ không đọc rõ thì ghi không đọc rõ, không đoán. Sau đó mô tả ngắn bố cục "
        "và điểm thu hút thị giác (visual hook). Trả văn bản thuần tiếng Việt.\n"
        f"Caption để tham khảo (không coi là chữ trong ảnh):\n{caption}"
    )}]
    for data in images:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
        content.append(_image_part(buffer.getvalue(), "image/jpeg"))
    text, _, _ = _chat(client, model, [{"role": "user", "content": content}], None, False, reasoning_effort)
    return text



def check_key(base_url: str, api_key: str, model: str) -> None:
    """Trả None nếu endpoint, key và model dùng được; ném ServiceError nếu không.

    Ưu tiên GET /models (dưới 1 giây, không tốn token; key sai vẫn ra AuthError). Chỉ gọi thử
    1 token khi endpoint không liệt kê được model: gọi thật trên model chậm có thể mất 20–40 giây.
    """
    try:
        if any(info["id"] == model for info in list_models(base_url, api_key)):
            return
    except (AuthError, QuotaError, NetworkError):
        raise
    except ServiceError:
        pass  # endpoint không hỗ trợ /models: thử gọi model
    client = make_client(base_url, api_key)
    with_retry(
        lambda: client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        ),
        service="llm",
    )


def list_models(base_url: str, api_key: str) -> list[dict]:
    """Model của endpoint qua GET {base_url}/models, sắp theo id.

    Mỗi mục: {"id", "owned_by", "context_length", "price_in", "price_out"}; giá là USD / 1 triệu token,
    None khi endpoint không trả giá (chỉ kiểu OpenRouter có trường pricing). Ném ServiceError nếu lỗi.
    """
    client = make_client(base_url, api_key)
    page = with_retry(client.models.list, service="llm")
    models = [_model_info(m) for m in page.data]
    return sorted(models, key=lambda m: m["id"])


def _model_info(model: Any) -> dict:
    extra = model.model_extra or {}
    pricing = extra.get("pricing") if isinstance(extra.get("pricing"), dict) else {}
    return {
        "id": model.id,
        "owned_by": getattr(model, "owned_by", None) or "",
        "context_length": extra.get("context_length"),
        "price_in": _per_million(pricing.get("prompt")),
        "price_out": _per_million(pricing.get("completion")),
    }


def _per_million(per_token: Any) -> float | None:
    """Giá USD/token (số hoặc chuỗi) → USD / 1 triệu token; None nếu không đọc được hoặc âm."""
    try:
        value = float(per_token)
    except (TypeError, ValueError):
        return None
    return round(value * 1_000_000, 4) if value >= 0 else None


def parse_json_loose(text: str) -> dict | None:
    """Đọc object JSON từ chữ của LLM: bỏ khối ```json, rồi cắt từ '{' đầu tới '}' cuối.

    Trả None nếu không đọc được hoặc kết quả không phải object.
    """
    if not text:
        return None
    cleaned = _strip_fences(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _strip_fences(text: str) -> str:
    """Bỏ hàng rào ``` quanh JSON. Ý tưởng từ vyralforge planner/llm_brain.py (MIT)."""
    return _FENCE_RE.sub("", text.strip()).strip()


def _reply_text(resp: Any) -> str:
    if not resp.choices:
        return ""
    return (resp.choices[0].message.content or "").strip()


def _total_tokens(resp: Any) -> int:
    usage = resp.usage
    return int(usage.total_tokens or 0) if usage is not None else 0


def _is_rejection(exc: BaseException, param: str) -> bool:
    """Endpoint từ chối một tham số nó không hỗ trợ: lỗi 400 có nhắc tới tên tham số."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 400 and param in str(exc).lower()


def _chat(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    temperature: float | None,
    json_mode: bool,
    reasoning_effort: str | None = None,
) -> tuple[str, int, bool]:
    """Gọi chat completion, trả (chữ, tổng token, còn bật json_mode không).

    Endpoint từ chối response_format hoặc reasoning_effort (400) thì gọi lại không kèm tham số đó.
    """
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    def create(**extra: Any) -> Any:
        try:
            return with_retry(lambda: client.chat.completions.create(**kwargs, **extra), service="llm")
        except Exception as exc:
            if "reasoning_effort" not in kwargs or not _is_rejection(exc, "reasoning_effort"):
                raise
            logger.info("Endpoint LLM không nhận reasoning_effort, gọi lại không kèm tham số này")
            del kwargs["reasoning_effort"]
            return with_retry(lambda: client.chat.completions.create(**kwargs, **extra), service="llm")

    if json_mode:
        try:
            resp = create(response_format=JSON_RESPONSE_FORMAT)
        except Exception as exc:
            if not _is_rejection(exc, "response_format"):
                raise
            logger.info("Endpoint LLM không nhận response_format, gọi lại không kèm response_format")
        else:
            return _reply_text(resp), _total_tokens(resp), True
    resp = create()
    return _reply_text(resp), _total_tokens(resp), False


def write_analysis(client: OpenAI, model: str, video: Video, labels: dict, settings: dict) -> dict:
    """Viết phân tích và gợi ý nhân bản cho 1 video (PLAN mục 7).

    Trả dict gồm các khóa chu_de_bai, tom_tat, hook_goc, ly_do_viral, goc_nhin,
    mau_hook_dien_cho_trong, vi_tri_cta, goi_y_nhan_ban và `_usage` (tổng token).
    JSON không đọc được thì hỏi lại 1 lần; vẫn lỗi thì trả {"_raw": chữ thô, "_usage": ...}.
    Lỗi xác thực, hết hạn mức, mạng do with_retry ném ra ngoài.
    """
    temperature = settings["llm"]["temperature"]
    effort = reasoning_effort(settings)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": POST_SYSTEM_PROMPT if video.format == "post" else SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(video, labels)},
    ]
    text, usage, json_mode = _chat(client, model, messages, temperature, json_mode=True, reasoning_effort=effort)
    data = parse_json_loose(text)
    if data is None:
        logger.warning("LLM trả JSON không đọc được (video %s), hỏi lại 1 lần", video.video_id)
        retry_messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": RETRY_PROMPT},
        ]
        text, extra, _ = _chat(client, model, retry_messages, temperature, json_mode=json_mode, reasoning_effort=effort)
        usage += extra
        data = parse_json_loose(text)
        if data is None:
            logger.warning("Vẫn không đọc được JSON từ LLM (video %s), lưu chữ thô", video.video_id)
            return {"_raw": text, "_usage": usage}
    data["_usage"] = usage
    return data


def _user_prompt(video: Video, labels: dict) -> str:
    if video.format == "post":
        caption = video.caption or ""
        hook = caption.splitlines()[0] if caption else "(không có)"
        content = (
            f"Bài đăng chữ/ảnh, caption:\n{caption or '(không có)'}\n\n"
            f"Hook (dòng đầu caption):\n{hook}\n\n"
            "Xác định vị trí CTA trong bài đăng; gợi ý là ý tưởng bài đăng mới.\n\n"
        )
        if video.transcript_status == "images" and video.transcript:
            content += f"Nội dung ảnh đã đọc:\n{video.transcript}\n\n"
    else:
        content = (
            f"Caption:\n{video.caption or '(không có)'}\n\n"
            f"Transcript:\n{video.transcript or '(không có thoại, chỉ dựa vào caption)'}\n\n"
            f"Hook (vài giây đầu):\n{video.hook or '(không có)'}\n\n"
        )
    return (
        content +
        "Nhãn Jev đã gắn (giữ nguyên, không đặt nhãn mới):\n"
        f"- Chủ đề: {_label(labels, 'topic')}\n"
        f"- Kiểu hook: {_label(labels, 'hook_type')}\n"
        f"- Cấu trúc: {_label(labels, 'structure')}\n"
        f"- CTA: {_label(labels, 'cta')}\n"
    )


def _label(labels: dict, key: str) -> str:
    return str(labels.get(key) or "(không rõ)")


def write_commentary(
    client: OpenAI, model: str, summary_tables: dict, reasoning_effort: str | None = DEFAULT_REASONING_EFFORT
) -> tuple[str, int]:
    """Viết 5-7 dòng nhận xét "công thức đang thắng" từ bảng by_topic và by_hook.

    Trả (chữ nhận xét, tổng token). Chỉ gửi các cột của bảng đếm (không gửi caption, transcript hay nhận xét cũ).
    Không có dòng nào trong bảng thì trả ("", 0) và không gọi LLM.
    """
    tables = {
        "by_topic": _table_rows(summary_tables.get("by_topic")),
        "by_hook": _table_rows(summary_tables.get("by_hook")),
    }
    if not tables["by_topic"] and not tables["by_hook"]:
        return "", 0
    messages = [
        {"role": "system", "content": COMMENTARY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(tables, ensure_ascii=False, indent=2)},
    ]
    text, tokens, _ = _chat(client, model, messages, temperature=None, json_mode=False, reasoning_effort=reasoning_effort)
    return text, tokens


def _table_rows(rows: list[dict] | None) -> list[dict]:
    return [{field: row.get(field) for field in _TABLE_FIELDS} for row in rows or []]


def filter_banned(suggestions: list[dict], ban_words: list[str]) -> list[dict]:
    """Bỏ gợi ý có từ cấm trong hook_moi hoặc y_tuong (không phân biệt hoa thường).

    Trả danh sách gợi ý còn lại. Mỗi trường được kiểm riêng để không ghép chữ giữa hai trường.
    """
    banned = [w for w in (_normalize(b) for b in ban_words) if w]
    kept: list[dict] = []
    for suggestion in suggestions or []:
        if not isinstance(suggestion, dict):
            logger.warning("Bỏ gợi ý không đúng dạng object: %r", suggestion)
            continue
        hit = _find_banned(suggestion, banned)
        if hit is not None:
            logger.info("Loại gợi ý có từ cấm '%s'", hit)
            continue
        kept.append(suggestion)
    return kept


def _find_banned(suggestion: dict, banned: list[str]) -> str | None:
    for field in _SUGGESTION_FIELDS:
        text = _normalize(str(suggestion.get(field) or ""))
        for word in banned:
            if word in text:
                return word
    return None


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())
