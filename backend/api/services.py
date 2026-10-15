"""AI service discovery, validation and credential-backed configuration."""
from __future__ import annotations

import copy
import logging

from backend.core import config, keys
from backend.collectors import transcript
from backend.services import jev_client, llm_client, pipeline
from backend.api.common import SERVICE_LABELS, error_message, fail, format_number, is_http_url, redact

logger = logging.getLogger("app.api.services")
DEFAULT_SETTINGS = {
    "jev": {"model": "", "yes_threshold": 0.5, "min_confidence": 0.6},
    "llm": {"base_url": "", "model": "", "temperature": 0.4},
    "stt": {"provider": "deepgram", "model": "", "language": "vi", "auto_language": True,
            "keyterms_file": "config/keyterms.txt", "fallback": "local_whisper",
            "whisper_model": "small"},
    "scan": {"video_kinds": ["video", "reel"], "min_views": 10000, "min_ratio_follow": 0, "match_all": True,
             "min_interactions": 200, "delay_min_s": 3, "delay_max_s": 8,
             "page_delay_min_s": 30, "page_delay_max_s": 60,
             "max_videos_per_page": 200, "max_scroll_rounds": 60, "stall_rounds": 4},
    "score_weights": {"ratio_median": 40, "ratio_median_cap": 5, "replicable": 25,
                      "hook_strength": 20, "relevant": 15, "jev_viral": 20},
    "my_page": {"name": "Thế Thảo Pharma", "audience": "Chủ nhà thuốc, dược sĩ"},
}
SERVICE_ROLES = {
    "jev": "Gắn nhãn chủ đề, kiểu hook và cấu trúc cho từng video hoặc bài đăng.",
    "deepgram": "Chuyển lời nói trong video thành chữ.",
    "llm": "Viết phân tích và gợi ý nhân bản. Dùng endpoint tương thích OpenAI.",
}
KEY_HELP = {
    "jev": "Key lấy từ tài khoản Jev. Key chỉ được lưu sau khi kiểm tra thành công.",
    "deepgram": "Key lấy từ trang quản lý API key của Deepgram. Key chỉ được lưu sau khi kiểm tra thành công.",
    "llm": "API key của nhà cung cấp đã chọn. Key chỉ được lưu sau khi kiểm tra thành công.",
}
LLM_PROVIDERS = {
    "OpenRouter": "https://openrouter.ai/api/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "Anthropic (Claude)": "https://api.anthropic.com/v1/",
}
LLM_CUSTOM = "Khác (tự nhập)"


def _configured(name: str, settings: dict, saved: str | None) -> bool:
    if not saved:
        return False
    if name == "jev":
        return bool(settings["jev"]["model"])
    if name == "deepgram":
        return bool(settings["stt"]["model"] and settings["stt"]["language"])
    return bool(settings["llm"]["base_url"] and settings["llm"]["model"])


def _saved_model(name: str, settings: dict) -> str:
    return settings["stt" if name == "deepgram" else name]["model"]


def get_services() -> dict:
    settings = config.load_settings()
    rows = []
    for name, label in SERVICE_LABELS.items():
        saved = keys.get_key(name)
        configured = _configured(name, settings, saved)
        row = {"name": name, "label": label, "role": SERVICE_ROLES[name], "key_help": KEY_HELP[name],
               "configured": configured, "saved_mask": keys.mask(saved) if saved else None,
               "model": redact(_saved_model(name, settings)), "needs_model": bool(saved and not configured)}
        if name == "llm":
            url = settings["llm"]["base_url"].strip()
            provider = next((label for label, value in LLM_PROVIDERS.items()
                             if value.rstrip("/") == url.rstrip("/")), None)
            row["llm"] = {"base_url": redact(url), "provider_label": provider or (LLM_CUSTOM if url else next(iter(LLM_PROVIDERS)))}
        elif name == "deepgram":
            row["deepgram"] = {"language": settings["stt"]["language"],
                               "auto_language": settings["stt"].get("auto_language", True)}
        rows.append(row)
    return {"ok": True, "storage_secure": keys.storage_secure(),
            "llm_providers": [{"label": label, "url": url} for label, url in LLM_PROVIDERS.items()],
            "custom_label": LLM_CUSTOM, "services": rows}


def _fetch_models(name: str, candidate: str, base_url: str) -> list[dict]:
    if name == "jev":
        return jev_client.list_models(candidate)
    if name == "deepgram":
        return transcript.list_deepgram_models(candidate)
    return llm_client.list_models(base_url, candidate)


def _deepgram_index(items: list[dict], saved: str) -> int:
    names = [item["name"] for item in items]
    if saved in names:
        return names.index(saved)
    for index, item in enumerate(items):
        if saved and item["architecture"] == saved:
            return index
    return 0


def _llm_option_label(item: dict) -> str:
    price_in, price_out = item.get("price_in"), item.get("price_out")
    if price_in is None and price_out is None:
        price = "giá: nhà cung cấp không công bố qua API"
    else:
        incoming = "không rõ" if price_in is None else format_number(price_in)
        outgoing = "không rõ" if price_out is None else format_number(price_out)
        price = f"giá vào {incoming} · ra {outgoing} USD / 1 triệu token"
    parts = [item["id"], price]
    context = item.get("context_length")
    if isinstance(context, (int, float)) and context > 0:
        parts.append(f"ngữ cảnh {int(context):,} token".replace(",", "."))
    return " · ".join(parts)


def connect_service(name: str, key: str, base_url: str) -> dict:
    if name not in SERVICE_LABELS:
        return fail("Dịch vụ không hợp lệ.")
    candidate = key.strip() or keys.get_key(name) or ""
    base_url = base_url.strip()
    if not candidate:
        return fail("Vui lòng nhập API key trước khi kết nối.")
    if name == "llm" and not is_http_url(base_url):
        return fail("Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://.")
    try:
        items = _fetch_models(name, candidate, base_url)
        if not items:
            return fail("Dịch vụ không trả về model nào. Kiểm tra lại " + ("key và endpoint." if name == "llm" else "key."))
        settings = config.load_settings()
        saved = _saved_model(name, settings)
        if name == "deepgram":
            models = [{"id": item["name"], "label": item["name"], "architecture": item["architecture"],
                       "languages": item["languages"]} for item in items]
            chosen = models[_deepgram_index(items, saved)]
        elif name == "jev":
            models = [{"id": item["name"], "label": item["name"],
                       "detail": " · ".join(part for part in (item.get("description", ""),
                                  f"phát hành {item['release_date']}" if item.get("release_date") else "") if part)}
                      for item in items]
            chosen = next((item for item in models if item["id"] == saved), models[0])
        else:
            models = [{"id": item["id"], "label": _llm_option_label(item)} for item in items]
            chosen = next((item for item in models if item["id"] == saved), models[0])
        # Provider-supplied metadata must not echo the candidate credential to JS.
        for model in models:
            for field in ("id", "label", "detail", "architecture"):
                if field in model:
                    model[field] = redact(model[field], (candidate,))
            if "languages" in model:
                model["languages"] = [{"code": redact(lang["code"], (candidate,)),
                                       "label": redact(lang["label"], (candidate,))}
                                      for lang in model["languages"]]
        result = {"ok": True, "models": models, "count": len(models), "default_id": chosen["id"]}
        if name == "deepgram":
            codes = [lang["code"] for lang in chosen["languages"]]
            language = settings["stt"]["language"]
            result["default_language"] = "vi" if "vi" in codes else language if language in codes else codes[0] if codes else None
        return result
    except Exception as exc:
        return fail(error_message(exc, (candidate,)))


def _check_selection(name: str, candidate: str, settings: dict, selection: dict) -> None:
    if name == "jev":
        jev_client.check_key(candidate, selection["model"])
    elif name == "deepgram":
        transcript.check_key(candidate, {**settings["stt"], "model": selection["model"],
                                         "language": selection["language"],
                                         "auto_language": selection.get("auto_language", True)})
    else:
        llm_client.check_key(selection["base_url"], candidate, selection["model"])


def _apply_selection(settings: dict, name: str, selection: dict) -> None:
    if name == "jev":
        settings["jev"]["model"] = selection["model"]
    elif name == "deepgram":
        settings["stt"].update(model=selection["model"], language=selection["language"],
                               auto_language=selection.get("auto_language", True))
    else:
        settings["llm"].update(base_url=selection["base_url"], model=selection["model"])


def save_service(name: str, key: str, selection: dict) -> dict:
    if name not in SERVICE_LABELS:
        return fail("Dịch vụ không hợp lệ.")
    if not keys.storage_secure():
        return fail("Không thể lưu API key: kho bảo mật chưa khả dụng. Hãy bật Windows Credential Manager.")
    candidate = key.strip() or keys.get_key(name) or ""
    if not candidate:
        return fail("Vui lòng nhập API key trước khi kiểm tra.")
    if name == "llm" and not is_http_url(selection.get("base_url", "")):
        return fail("Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://.")
    if not selection.get("model"):
        return fail("Vui lòng chọn model trước khi kiểm tra.")
    if name == "deepgram" and not selection.get("language"):
        return fail("Model này không có ngôn ngữ nào. Hãy chọn model khác.")
    try:
        settings = config.load_settings()
        _check_selection(name, candidate, settings, selection)
        updated = copy.deepcopy(settings)
        _apply_selection(updated, name, selection)
        config.save_settings(updated)
        keys.set_key(name, candidate)
    except Exception as exc:
        return fail(error_message(exc, (candidate,)))
    return {"ok": True, "message": f"Đã kiểm tra và lưu cấu hình {SERVICE_LABELS[name]}."}


def check_keys(require_deepgram: bool = True) -> dict:
    try:
        result = pipeline.check_all_keys(config.load_settings(), require_deepgram=require_deepgram)
        result = {name: redact(str(reason)) if reason else None for name, reason in result.items()}
        for name, reason in result.items():
            if reason:
                logger.warning("Key %s: %s", SERVICE_LABELS[name], reason)
    except Exception as exc:
        message = error_message(exc)
        result = {name: message for name in (SERVICE_LABELS if require_deepgram else ("jev", "llm"))}
    return {"ok": True, "status": result}


def reset_configuration() -> dict:
    try:
        for name in SERVICE_LABELS:
            keys.delete_key(name)
        config.save_settings(copy.deepcopy(DEFAULT_SETTINGS))
        (config.CONFIG_DIR / "channels.txt").write_text("", encoding="utf-8")
    except Exception as exc:
        return fail(error_message(exc))
    return {"ok": True, "message": "Đã đặt lại API key, cài đặt và danh sách kênh. Dữ liệu và phiên Facebook được giữ nguyên."}
