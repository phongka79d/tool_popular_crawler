"""Jev (TypeSafe System One) integration: labels, score extras, suggestion check, key check.

Spec: PLAN-JEV.md §6, §7, §11.6. Raw answers are cached per model in SQLite so score
weights and thresholds can change without calling Jev again.
"""
from __future__ import annotations

import logging
from typing import Any

import db
from errors import AuthError, ServiceError
from models import Video
from retry import with_retry
from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient, TypeSafeError

logger = logging.getLogger(__name__)

CAPTION_MAX = 1500
TRANSCRIPT_MAX = 3000
HOOK_FALLBACK_MAX = 200
UNSURE_SUFFIX = " (chưa chắc)"
YES_TEXT = "Có"
NO_TEXT = "Không"
LABELS_KIND = "labels"
AUTH_MESSAGE = "API key [Jev] không hợp lệ. Vào Cài đặt để nhập lại."
ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

# PLAN §7: reject a suggestion if giu_cong_thuc < 1, chep_nguyen > 0.5 or rui_ro > 0.5.
MIN_FORMULA_KEEP = 1.0
MAX_COPY = 0.5
MAX_RISK = 0.5

CHOICE_KEYS = ("topic", "hook_type", "structure", "cta")
RISK_KEYS = ("risk_absolute", "risk_compare")

HOOK_LEVELS = [
    "Nhạt, không gợi tò mò",
    "Có gợi tò mò",
    "Rất cuốn, khó lướt qua",
]

# PLAN §11.6: clip-forge's viral rubric split into atomic Scores, each with three levels.
EXTRA_SCORES: dict[str, tuple[str, list[str]]] = {
    "cam_xuc_manh": (
        "Nội dung trong `caption` và `transcript` gây cảm xúc mạnh đến mức nào?",
        [
            "Trung tính, không có cảm xúc rõ",
            "Có chút ngạc nhiên, lo lắng hoặc thích thú",
            "Cảm xúc mạnh rõ rệt: sốc, lo sợ, giận dữ hoặc phấn khích",
        ],
    ),
    "gia_tri_thuc_tien": (
        "Người xem làm theo được ngay những gì có trong `transcript` hoặc `caption` đến mức nào?",
        [
            "Chủ yếu kể lể hoặc quảng cáo, không có cách làm cụ thể",
            "Có một ý hữu ích nhưng còn chung chung",
            "Có cách làm hoặc mẹo cụ thể, làm theo được ngay",
        ],
    ),
    "ket_thuc_tron_y": (
        "`transcript` có mở đầu, phát triển và kết thúc trọn ý đến mức nào?",
        [
            "Dừng giữa chừng hoặc không có kết luận",
            "Có phần kết nhưng còn ngắn hoặc chưa chốt ý",
            "Có đủ mở đầu, phát triển và kết luận rõ ràng",
        ],
    ),
    "kha_nang_chia_se": (
        "Người xem có lý do để gửi video này cho người khác đến mức nào, dựa trên `caption` và `transcript`?",
        [
            "Ít có lý do để chia sẻ",
            "Có thể chia sẻ với một nhóm nhỏ",
            "Có lý do rõ để chia sẻ cho người thân, đồng nghiệp hoặc khách hàng",
        ],
    ),
}

FORMULA_LEVELS = [
    "Khác cả kiểu hook lẫn cấu trúc",
    "Giống một trong hai: kiểu hook hoặc cấu trúc",
    "Giống cả kiểu hook lẫn cấu trúc",
]


def build_state(video: Video, my_page_desc: str) -> dict:
    """State sent to Jev (PLAN §6): hook, caption and transcript are truncated."""
    caption = video.caption or ""
    transcript = video.transcript or ""
    return {
        "hook": video.hook or caption[:HOOK_FALLBACK_MAX],
        "caption": caption[:CAPTION_MAX],
        "transcript": transcript[:TRANSCRIPT_MAX],
        "my_page": my_page_desc,
    }


def build_questions(taxonomy: dict) -> dict[str, Choice | Noul | Score]:
    """All labelling questions for one Jev call: 4 Choices, 1 hook Score, 4 Noul, 4 Score extras."""
    questions: dict[str, Choice | Noul | Score] = {
        "topic": Choice(
            instructions="Chủ đề chính của `caption` và `transcript` thuộc nhóm nào?",
            criteria=dict(taxonomy["topic"]),
        ),
        "hook_type": Choice(
            instructions="Câu `hook` thuộc kiểu mở đầu nào?",
            criteria=dict(taxonomy["hook_type"]),
        ),
        "structure": Choice(
            instructions="`transcript` được sắp xếp theo cấu trúc nào?",
            criteria=dict(taxonomy["structure"]),
        ),
        "cta": Choice(
            instructions="Lời kêu gọi hành động trong `transcript` hoặc `caption` là gì? Chọn `khong_co` nếu không có CTA, hoặc `khac` nếu có CTA nhưng không thuộc các nhóm liệt kê.",
            criteria=dict(taxonomy["cta"]),
        ),
        "hook_strength": Score(
            instructions="Câu `hook` giữ người xem lại mạnh đến đâu?",
            criteria=list(HOOK_LEVELS),
        ),
        "relevant": Noul(
            instructions="`caption` hoặc `transcript` có liên quan trực tiếp tới nghề dược hoặc kinh doanh nhà thuốc không?",
        ),
        "replicable": Noul(
            instructions="Page mô tả trong `my_page` có làm lại được ý tưởng này với nội dung của mình không?",
        ),
        "risk_absolute": Noul(
            instructions="`caption` hoặc `transcript` có câu khẳng định tuyệt đối hoặc cam kết chữa khỏi bệnh không?",
        ),
        "risk_compare": Noul(
            instructions="`caption` hoặc `transcript` có so sánh, chê bai đối thủ hoặc thương hiệu cụ thể không?",
        ),
    }
    for key, (instructions, levels) in EXTRA_SCORES.items():
        questions[key] = Score(instructions=instructions, criteria=list(levels))
    return questions


def ask_labels(
    client: TypeSafeClient, video: Video, taxonomy: dict, settings: dict
) -> tuple[dict, dict]:
    """One Jev call with every label question. Cached per model: a cache hit makes no call."""
    model = settings["jev"]["model"]
    cached = db.get_jev(video.video_id, model, LABELS_KIND)
    if cached is not None:
        logger.info("Dùng lại nhãn Jev đã lưu của video %s", video.video_id)
        return cached, dict(ZERO_USAGE)

    questions = build_questions(taxonomy)
    state = build_state(video, _my_page_desc(settings))
    response = with_retry(
        lambda: client.system_one(state=state, questions=questions, model=model),
        service="jev",
    )
    raw = _answers_to_raw(response)
    _check_complete(raw, questions)
    usage = _usage_of(response)
    db.save_jev(video.video_id, model, LABELS_KIND, raw, usage)
    return raw, usage


def interpret_labels(answers_raw: dict, settings: dict, taxonomy: dict) -> dict:
    """Raw Jev answers → Excel-ready values (PLAN §6 "Đọc kết quả bằng code")."""
    jev = settings["jev"]
    yes_threshold = jev["yes_threshold"]
    min_confidence = jev["min_confidence"]
    labels = taxonomy["labels"]

    out: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    uncertain: list[str] = []

    for key in CHOICE_KEYS:
        code = answers_raw[key]["choice"]
        conf = float(answers_raw[key]["confidence"])
        text = labels[code]
        if conf < min_confidence:
            text += UNSURE_SUFFIX
            uncertain.append(key)
        out[key] = text
        out[f"{key}_code"] = code
        confidence[key] = conf

    out["hook_strength"] = _to_level(float(answers_raw["hook_strength"]["score"]))
    for key in EXTRA_SCORES:
        out[key] = float(answers_raw[key]["score"])
    for key in ("hook_strength", *EXTRA_SCORES):
        conf = float(answers_raw[key]["confidence"])
        confidence[key] = conf
        if conf < min_confidence:
            uncertain.append(key)

    for key in ("relevant", "replicable"):
        p = float(answers_raw[key]["noul"])
        out[f"{key}_p"] = p
        out[key] = YES_TEXT if p >= yes_threshold else NO_TEXT
    for key in RISK_KEYS:
        out[f"{key}_p"] = float(answers_raw[key]["noul"])
    out["risk_flags"] = [labels[key] for key in RISK_KEYS if out[f"{key}_p"] >= yes_threshold]

    out["uncertain"] = uncertain
    out["confidence"] = confidence
    return out


def check_suggestions(
    client: TypeSafeClient, video: Video, suggestions: list[dict], settings: dict
) -> tuple[list[dict], dict, dict]:
    """Jev checks every LLM suggestion (PLAN §7) in one call. Returns (kept, raw answers, usage).

    Not cached: the suggestions can be rewritten, so a stored check would go stale.
    """
    if not suggestions:
        return [], {}, dict(ZERO_USAGE)

    model = settings["jev"]["model"]
    questions: dict[str, Choice | Noul | Score] = {}
    for i in range(len(suggestions)):
        questions[f"giu_cong_thuc_{i}"] = Score(
            instructions=(
                f"`goi_y[{i}].hook_moi` có cùng kiểu hook (`kieu_hook_goc`) "
                "và cùng cấu trúc (`cau_truc_goc`) với video gốc không?"
            ),
            criteria=list(FORMULA_LEVELS),
        )
        questions[f"chep_nguyen_{i}"] = Noul(
            instructions=f"`goi_y[{i}].y_tuong` có lặp lại gần nguyên văn câu chữ trong `transcript` không?",
        )
        questions[f"rui_ro_{i}"] = Noul(
            instructions=(
                f"`goi_y[{i}].hook_moi` hoặc `goi_y[{i}].y_tuong` "
                "có khẳng định tuyệt đối hoặc cam kết chữa bệnh không?"
            ),
        )

    state = {
        "kieu_hook_goc": _plain_label(video.jev["hook_type"]),
        "cau_truc_goc": _plain_label(video.jev["structure"]),
        "transcript": (video.transcript or "")[:TRANSCRIPT_MAX],
        "goi_y": [
            {"hook_moi": s.get("hook_moi", ""), "y_tuong": s.get("y_tuong", "")}
            for s in suggestions
        ],
    }
    response = with_retry(
        lambda: client.system_one(state=state, questions=questions, model=model),
        service="jev",
    )
    raw = _answers_to_raw(response)
    _check_complete(raw, questions)

    kept: list[dict] = []
    for i, suggestion in enumerate(suggestions):
        giu = float(raw[f"giu_cong_thuc_{i}"]["score"])
        chep = float(raw[f"chep_nguyen_{i}"]["noul"])
        rui = float(raw[f"rui_ro_{i}"]["noul"])
        if giu >= MIN_FORMULA_KEEP and chep <= MAX_COPY and rui <= MAX_RISK:
            kept.append(suggestion)
        else:
            logger.info(
                "Loại gợi ý %d: giữ công thức %.2f, chép nguyên văn %.2f, rủi ro %.2f",
                i, giu, chep, rui,
            )
    return kept, raw, _usage_of(response)


def make_client(api_key: str | None, model: str) -> TypeSafeClient:
    """Jev client. SDK retries are off because with_retry owns backoff and error mapping."""
    if not api_key:
        raise AuthError("jev", AUTH_MESSAGE)
    try:
        return TypeSafeClient(api_key=api_key, model=model, retry=RetryPolicy(max_retries=0))
    except TypeSafeError as exc:
        raise AuthError("jev", AUTH_MESSAGE) from exc


def check_key(api_key: str | None, model: str) -> None:
    """Verify key and model with one tiny Noul. Raises ServiceError (AuthError, QuotaError, ...) on failure."""
    client = make_client(api_key, model)
    questions = {"loi_chao": Noul(instructions="Nội dung `state` có phải là một lời chào không?")}
    try:
        with_retry(
            lambda: client.system_one(state="Xin chào", questions=questions, model=model),
            service="jev",
        )
    finally:
        client.close()


def list_models(api_key: str | None) -> list[dict]:
    """Models the key can use, from GET /v1/models: [{"name", "description", "release_date"}].

    Also verifies the key. Raises ServiceError (AuthError, ...) on failure.
    """
    client = make_client(api_key, "")
    try:
        resp = with_retry(client.models.list, service="jev")
    finally:
        client.close()
    return [
        {"name": m.name, "description": m.description or "", "release_date": str(m.release_date or "")}
        for m in resp.models
    ]


def _my_page_desc(settings: dict) -> str:
    page = settings["my_page"]
    return f"Page {page['name']}. Khách hàng của page: {page['audience']}."


def _answers_to_raw(response: Any) -> dict:
    """SDK answers → plain JSON dict, safe to cache in SQLite."""
    raw: dict[str, dict] = {}
    for qid, answer in response.choices.items():
        raw[qid] = {
            "type": "choice",
            "choice": answer.choice,
            "confidence": answer.confidence,
            "probabilities": dict(answer.probabilities),
        }
    for qid, answer in response.scores.items():
        raw[qid] = {
            "type": "score",
            "score": answer.score,
            "confidence": answer.confidence,
            "probabilities": dict(answer.probabilities),
        }
    for qid, answer in response.nouls.items():
        raw[qid] = {"type": "noul", "noul": answer.noul}
    return raw


def _check_complete(raw: dict, questions: dict) -> None:
    missing = [qid for qid in questions if qid not in raw]
    if missing:
        raise ServiceError("jev", f"Jev không trả lời đủ câu hỏi: {', '.join(missing)}.")


def _usage_of(response: Any) -> dict:
    input_tokens = response.usage.input_tokens or 0
    output_tokens = response.usage.output_tokens or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _to_level(score: float) -> int:
    """Expected Score (0–2) → integer level; halves round up."""
    return min(2, max(0, int(score + 0.5)))


def _plain_label(text: str) -> str:
    return text.removesuffix(UNSURE_SUFFIX)
