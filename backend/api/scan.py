"""Một phiên quét dùng chung; mọi trạng thái được bảo vệ bằng lock."""
from __future__ import annotations

import copy
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.core import config, keys
from backend.services import pipeline, filters, llm_client
from backend.api import services, results
from backend.api.common import error_message, redact, fail

KINDS = (("video", "Video thường"), ("reel", "Reel"))
_lock = threading.Lock()


def _new_session():
    return dict(running=False, scan_queue=queue.Queue(), stop_event=threading.Event(),
                scan_started=None, scan_elapsed=0, scan_log=[], scan_errors=[], progress=None,
                scan_result=None, question=None, scan_usage=None, scan_usage_history=[],
                scan_turns=[], scan_channels=[], scan_passed_total=0, scan_overall=0.0,
                scan_item_label="video", scan_lanes={}, scan_analyzed=(0, 0))


_session = _new_session()


def _channel_rows(channels):
    rows = []
    for channel in channels:
        passed, analyzed = channel["passed"], channel["analyzed"]
        fraction = (0.6 + 0.4 * min(1, analyzed / passed) if passed else
                    1.0 if passed == 0 else 0.35 if channel["found"] is not None else
                    0.1 if channel["status"] != "Chờ quét" else 0.0)
        if channel["status"] == "Bỏ qua":
            fraction = 1.0
        rows.append({"name": channel.get("name") or channel["url"], "url": channel["url"],
                     "followers": channel.get("followers"), "status": channel["status"],
                     "progress": fraction, "found": channel["found"], "passed": passed, "analyzed": analyzed})
    return rows


def _filter_summary(params: pipeline.RunParams) -> str:
    parts = []
    if params.min_views > 0:
        parts.append(f"≥ {params.min_views:,} lượt xem".replace(",", "."))
    if params.min_ratio_follow > 0:
        parts.append(f"≥ {params.min_ratio_follow:g}× follower")
    summary = ("Giữ video có " + (" VÀ " if params.match_all else " HOẶC ").join(parts)
               if parts else "Không lọc: giữ mọi video.")
    lengths = [
        f"{label} {filters.length_limit_text(params.length_limits.get(kind, (None, None)))}"
        for kind, label in (("video", "Video"), ("reel", "Reel"))
        if kind in params.formats and any(params.length_limits.get(kind, (None, None)))
    ]
    if lengths:
        return (summary + " · " if parts else "") + " · ".join(lengths)
    return summary

def _page_header(message: str) -> tuple[str, int | None] | None:
    """Chỉ đọc thông báo tên/follower, không nhầm với diễn biến quét kênh."""
    match = re.fullmatch(
        r"Kênh \d+/\d+: (.+) · (?:(\d[\d.,\s]*) người theo dõi|chưa đọc được số người theo dõi)",
        message,
    )
    if not match:
        return None
    count = match.group(2)
    return match.group(1).strip(), int(re.sub(r"\D", "", count)) if count is not None else None

def _track_channels(state, event: pipeline.Progress) -> None:
    """Bộ đếm lấy từ sự kiện cuối bước, không đếm các thông báo trung gian."""
    channels = state.setdefault("scan_channels", [])
    channel = next((row for row in channels if row["url"] == event.page_url), None)
    if channel is None and event.page_url:
        channel = {"url": event.page_url, "status": "Chờ quét", "found": None,
                   "passed": None, "analyzed": 0}
        channels.append(channel)
    if channel is not None:
        if event.error:
            channel["status"] = "Có lỗi"
        elif event.stage == "scan":
            header = _page_header(event.message)
            if header:
                channel["name"], channel["followers"] = header
            if "bỏ qua." in event.message:
                channel["status"] = "Bỏ qua"
            elif channel["passed"] is None:
                channel["status"] = "Đang quét"
            found = re.search(r"thu được (\d+)", event.message)
            if found:
                channel["found"] = int(found.group(1))
                channel["status"] = "Đã quét"
        elif event.stage == "filter":
            channel["status"] = "Đang lọc"
            passed = re.search(r"Đạt ngưỡng: (\d+)/(\d+)", event.message)
            if passed:
                total = int(passed.group(1))
                channel["passed"] = max(0, total - state.get("scan_passed_total", 0))
                state["scan_passed_total"] = total
                channel["status"] = ("Đã phân tích" if channel["analyzed"] >= channel["passed"]
                                     else "Chờ phân tích")
        elif event.stage == "analyze":
            channel["status"] = "Đang phân tích"
            if event.turn:
                channel["analyzed"] += 1
                if channel["passed"] is not None and channel["analyzed"] >= channel["passed"]:
                    channel["status"] = "Đã phân tích"
    if event.done:
        overall = 1.0
    elif event.stage == "export":
        overall = 0.95
    elif channels:
        # Quét và phân tích chạy song song: tiến độ tổng không lùi khi đổi kênh.
        overall = 0.05 + 0.85 * sum(row["progress"] for row in _channel_rows(channels)) / len(channels)
    else:
        overall = 0.02
    state["scan_overall"] = max(state.get("scan_overall", 0.0), overall)

def _record_scan_progress(state, event: pipeline.Progress, now: datetime, redact) -> None:
    """Cập nhật dữ liệu thuần; sự kiện chỉ có usage không thay khung tiến độ."""
    if event.usage is not None:
        state["scan_usage"] = dict(event.usage)
        state.setdefault("scan_usage_history", []).append(
            {"Thời gian": now, "Token LLM": event.usage.get("llm_tokens", 0),
             "Token Jev": event.usage.get("jev_tokens", 0)})
    if event.turn is not None:
        turn = dict(event.turn)
        turn["label"] = redact(turn["label"])
        state.setdefault("scan_turns", []).append(turn)
    if not event.message and event.transient:
        return
    if event.message and not event.transient:
        marker = "⚠ " if event.error else ""
        state.setdefault("scan_log", []).append(f"{now:%H:%M:%S}  {marker}{redact(event.message)}")
    if event.error:
        state.setdefault("scan_errors", []).append(redact(event.error))
    else:
        state["progress"] = event
        # Quét Facebook và phân tích AI chạy song song: giữ thông báo cuối của từng luồng riêng.
        lane = "analyze" if event.stage == "analyze" else "scan" if event.stage in ("scan", "filter") else None
        if lane:
            state.setdefault("scan_lanes", {})[lane] = event
        if event.stage == "analyze" and event.steps:
            state["scan_analyzed"] = (event.step, event.steps)
    if not event.transient:
        _track_channels(state, event)

def _turn_speed(turn: dict) -> float | None:
    seconds, tokens = turn.get("llm_seconds", 0.0), turn.get("llm_output_tokens", 0)
    return round(tokens / seconds, 2) if seconds > 0 and tokens > 0 else None

def _saved_video_kinds(saved):
    return [kind for kind, _ in KINDS if kind in (saved.get("video_kinds") or [])] or ["video", "reel"]


def _params(options, settings=None):
    settings = settings if settings is not None else config.load_settings()
    saved = settings.get("scan", {})
    post = options.get("kind", "video") == "post"
    formats = {"post"} if post else set(options.get("formats", _saved_video_kinds(saved)))
    limits = options.get("length_limits", saved.get("length_limits", {}))
    limits = {kind: tuple(value or None for value in limits.get(kind, (None, None)))
              for kind in ("video", "reel") if not post and kind in formats}
    return pipeline.RunParams(int(options.get("days", 7)), formats,
        min_views=0 if post else int(options.get("min_views", saved.get("min_views", 10000))),
        min_interactions=int(options.get("min_interactions", saved.get("min_interactions", 200))) if post else 0,
        min_ratio_follow=0 if post else float(options.get("min_ratio_follow", saved.get("min_ratio_follow", 0))),
        match_all=bool(options.get("match_all", saved.get("match_all", True))), length_limits=limits)


def _problems(params):
    problems = []
    if not params.formats:
        problems.append("Chọn ít nhất một loại video để quét.")
    if not pipeline.is_post_run(params):
        problem = filters.validate_length_limits(params.length_limits)
        if problem:
            problems.append(problem)
    if params.days < 1:
        problems.append("Số ngày phải lớn hơn 0.")
    if params.formats != {"post"} and not params.formats <= {kind for kind, _ in KINDS}:
        problems.append("Loại video không hợp lệ.")
    if min(params.min_views, params.min_ratio_follow, params.min_interactions) < 0:
        problems.append("Ngưỡng tối thiểu không được âm.")
    return problems


def get_scan_options():
    settings = config.load_settings()
    saved = settings.get("scan", {})
    defaults = dict(days=7, kind="video", formats=_saved_video_kinds(saved),
                    length_limits={kind: list(saved.get("length_limits", {}).get(kind, (None, None)))
                                   for kind in ("video", "reel")},
                    min_views=saved.get("min_views", 10000), min_ratio_follow=saved.get("min_ratio_follow", 0),
                    match_all=saved.get("match_all", True), min_interactions=saved.get("min_interactions", 200),
                    read_images=saved.get("read_images", False))
    return {"ok": True, "defaults": defaults, "kinds": [{"id": kind, "label": label} for kind, label in KINDS],
            "presets": {"min_views": [50000, 100000], "min_ratio_follow": [5, 10], "length": {
                "video": [{"label": "≥ 1 phút", "min": 60, "max": None}, {"label": "≥ 3 phút", "min": 180, "max": None}],
                "reel": [{"label": "≤ 60 giây", "min": None, "max": 60}, {"label": "≤ 90 giây", "min": None, "max": 90}]}},
            "terms": {"accepted_at": settings.get("terms_accepted_at"), "paragraphs": [
                "Công cụ này đọc Facebook qua trình duyệt đã đăng nhập (thu thập tự động).",
                "Điều khoản Facebook hạn chế việc thu thập tự động khi chưa được phép."], "bullets": [
                "Tài khoản dùng để quét có thể bị Facebook yêu cầu xác minh (checkpoint) hoặc khóa. Nên dùng tài khoản phụ, không dùng tài khoản chính.",
                "Chỉ thu thập nội dung bạn được phép truy cập.", "Bạn tự chịu trách nhiệm về việc sử dụng công cụ."],
                "link": {"label": "Điều khoản Facebook", "url": "https://www.facebook.com/terms"}}}


def preview_scan(options):
    settings = config.load_settings()
    params = _params(options, settings)
    problems = _problems(params)
    summary = (f"Giữ bài đăng có ≥ {params.min_interactions:,} tương tác".replace(",", ".")
               if pipeline.is_post_run(params) and params.min_interactions else
               "Không lọc: giữ mọi bài đăng." if pipeline.is_post_run(params) else _filter_summary(params))
    return {"ok": True, "summary": summary, "problems": problems,
            "can_start": not problems and bool(settings.get("terms_accepted_at")) and not is_running()}


def set_read_images(enabled):
    with _lock:
        if _session["running"]:
            return fail("Không thể đổi tùy chọn khi đang quét.")
        settings = config.load_settings()
        saved = settings.setdefault("scan", {})
        saved["video_kinds"] = _saved_video_kinds(saved)
        message = None
        enabled = bool(enabled)
        if enabled:
            llm = settings["llm"]
            supported = llm_client.vision_cached(llm)
            if supported is None:
                try:
                    supported = llm_client.check_vision(llm["base_url"], keys.get_key("llm"), llm["model"])
                except Exception as exc:
                    settings.setdefault("scan", {})["read_images"] = False
                    config.save_settings(settings)
                    return {**fail(error_message(exc)), "enabled": False, "message": None}
                llm["vision"] = dict(base_url=llm["base_url"], model=llm["model"], ok=supported)
            enabled = supported is True
            message = "Model LLM hỗ trợ đọc ảnh." if enabled else llm_client.vision_error(llm["model"])
        settings.setdefault("scan", {})["read_images"] = enabled
        config.save_settings(settings)
        return {"ok": True, "enabled": enabled, "message": message}


def accept_terms():
    with _lock:
        settings = config.load_settings()
        accepted = settings.get("terms_accepted_at")
        if not accepted:
            accepted = datetime.now().astimezone().isoformat(timespec="seconds")
            settings["terms_accepted_at"] = accepted
            saved = settings.setdefault("scan", {})
            saved["video_kinds"] = _saved_video_kinds(saved)
            config.save_settings(settings)
        return {"ok": True, "accepted_at": accepted}


def _scan_worker(params, settings, events, stop):
    def ask_user(kind, message, options):
        question = dict(kind=kind, message=message, options=options, answer_event=threading.Event(), answer=None)
        events.put(("question", question))
        while not question["answer_event"].wait(0.1):
            if stop.is_set():
                return "pause"
        return question["answer"]
    try:
        result = pipeline.run(params, settings, events.put, stop, ask_user=ask_user)
        events.put(("result", result))
    except Exception as exc:
        events.put(("failure", error_message(exc)))
    finally:
        events.put(("finished", time.monotonic()))


def start_scan(options):
    from backend.api import channels
    with channels._lock, _lock:
        if channels.is_logging_in():
            return fail("Đang đăng nhập Facebook. Hãy hoàn tất đăng nhập trước khi quét.")
        _drain_scan_queue()
        if _session["running"]:
            return fail("Một lần quét đang chạy. Hãy dừng hoặc chờ hoàn tất.")
        settings = config.load_settings()
        if not settings.get("terms_accepted_at"):
            return fail("Vui lòng đọc và xác nhận lưu ý Facebook trước khi quét.")
        params = _params(options, settings)
        problems = _problems(params)
        if problems:
            return fail(problems[0])
        checked = services.check_keys(require_deepgram=not pipeline.is_post_run(params))
        status = checked.get("status", {})
        failed = [dict(jev="Jev", deepgram="Deepgram", llm="LLM").get(name, name)
                  for name, reason in status.items() if reason]
        if failed:
            return fail("Chưa thể chạy quét vì lỗi key ở: " + ", ".join(failed) +
                        ". Sửa trong mục Dịch vụ AI rồi kiểm tra lại.", key_status=_redacted(status))
        if not checked.get("ok"):
            return fail(checked.get("error", "Không kiểm tra được API key."), key_status=_redacted(status))
        channels = config.load_lines("config/channels.txt")
        if not channels:
            return fail("Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét.")
        scan = settings.setdefault("scan", {})
        scan["video_kinds"] = _saved_video_kinds(scan)
        if pipeline.is_post_run(params):
            scan["min_interactions"] = params.min_interactions
        else:
            scan.update(min_views=params.min_views, min_ratio_follow=params.min_ratio_follow,
                        match_all=params.match_all, video_kinds=sorted(params.formats),
                        length_limits={**scan.get("length_limits", {}), **params.length_limits})
        config.save_settings(settings)
        _session.clear()
        _session.update(_new_session())
        _session.update(running=True, scan_started=time.monotonic(),
                        scan_item_label="bài đăng" if pipeline.is_post_run(params) else "video",
                        scan_channels=[dict(url=url, status="Chờ quét", found=None, passed=None, analyzed=0)
                                       for url in channels])
        worker = threading.Thread(target=_scan_worker,
            args=(params, copy.deepcopy(settings), _session["scan_queue"], _session["stop_event"]),
            daemon=True, name="video-scan")
        try:
            worker.start()
        except Exception:
            _session["running"] = False
            _session["scan_elapsed"] = time.monotonic() - _session["scan_started"]
            raise
        return {"ok": True}


def _drain_scan_queue():
    finished = False
    while True:
        try:
            event = _session["scan_queue"].get_nowait()
        except queue.Empty:
            break
        if not isinstance(event, tuple):
            _record_scan_progress(_session, event, datetime.now(), redact)
            continue
        kind, value = event
        if kind == "result":
            _session["scan_result"] = str(value) if value else None
        elif kind == "failure":
            _session["scan_errors"].append(redact(value))
        elif kind == "question":
            if not _session["stop_event"].is_set():
                _session["question"] = value
        elif kind == "finished":
            _session["running"] = False
            _session["scan_elapsed"] = max(0, (value if value is not None else time.monotonic()) - _session["scan_started"])
            _session["question"] = None
            finished = True
    return finished


def stop_scan():
    with _lock:
        _drain_scan_queue()
        _session["stop_event"].set()
        _session["question"] = None
    return {"ok": True}


def answer_question(option_id):
    with _lock:
        _drain_scan_queue()
        question = _session["question"]
        if not question or option_id not in [option[0] for option in question["options"]]:
            return fail("Lựa chọn không hợp lệ hoặc câu hỏi đã kết thúc.")
        question["answer"] = option_id
        question["answer_event"].set()
        _session["question"] = None
    return {"ok": True}


def _redacted(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def _turn_rows(turns):
    return [dict(label=turn["label"], llm_tokens=turn.get("llm_tokens", 0),
                 llm_output_tokens=turn.get("llm_output_tokens", 0), llm_seconds=round(turn.get("llm_seconds", 0), 2),
                 speed=_turn_speed(turn), jev_tokens=turn.get("jev_tokens", 0),
                 deepgram_minutes=round(turn.get("deepgram_minutes", 0), 2)) for turn in reversed(turns)]


def _lanes(state, stage):
    """Hai luồng chạy song song: quét Facebook theo kênh và phân tích AI theo từng mục."""
    finished = stage in ("export", "done") or (state["scan_started"] is not None and not state["running"])
    events, item = state.get("scan_lanes", {}), state["scan_item_label"]
    channels = state.get("scan_channels", [])
    total = len(channels)
    scanned = sum(1 for row in channels if row["found"] is not None or row["status"] in ("Bỏ qua", "Có lỗi"))
    scan_event = events.get("scan")
    scan_done = finished or (total > 0 and scanned >= total)
    if scan_done:
        scan = dict(state="done", message=f"Đã quét xong {scanned}/{total} kênh." if total else "Đã quét xong.")
    elif scan_event is not None:
        scan = dict(state="current", message=scan_event.message, page_url=scan_event.page_url or None)
    else:
        scan = dict(state="pending", message="Bắt đầu sau khi kiểm tra API key.")
    scan.update(id="scan", title="Quét Facebook", fraction=scanned / total if total else (1.0 if scan_done else 0.0),
                label=f"{scanned}/{total} kênh")
    done, known = state.get("scan_analyzed", (0, 0))
    analyze_event = events.get("analyze")
    if finished:
        analyze = dict(state="done", message=f"Đã phân tích {done} {item}." if known else f"Không có {item} nào cần phân tích.")
    elif analyze_event is not None and done < known:
        analyze = dict(state="current", message=analyze_event.message)
    elif analyze_event is not None:
        analyze = dict(state="waiting", message=f"Đã phân tích hết {item} đạt ngưỡng; chờ kênh tiếp theo.")
    else:
        analyze = dict(state="pending", message=f"Bắt đầu khi có {item} đạt ngưỡng từ bước quét.")
    analyze.update(id="analyze", title="Phân tích AI", fraction=done / known if known else (1.0 if finished else 0.0),
                   label=f"{done}/{known} {item}")
    return [scan, analyze]


def get_scan_state(log_since=0):
    with _lock:
        _drain_scan_queue()
        s = _session
        progress = s["progress"]
        stage = progress.stage if progress else None
        lanes = _lanes(s, stage)
        elapsed = (time.monotonic() - s["scan_started"] if s["running"] else s["scan_elapsed"])
        usage = dict(s["scan_usage"]) if s["scan_usage"] is not None else None
        if usage is not None:
            for key, default in dict(llm_model="", llm_tokens=0, llm_calls=0, llm_output_tokens=0,
                llm_seconds=0, llm_cached=0, jev_tokens=0, jev_calls=0, deepgram_minutes=0, deepgram_calls=0).items():
                usage.setdefault(key, default)
            usage["llm_speed"] = pipeline.llm_speed(usage["llm_output_tokens"], usage["llm_seconds"])
        question = s["question"]
        question = dict(kind=question["kind"], message=question["message"], options=[
            dict(id=key, label=label) for key, label in question["options"]]) if question else None
        result = s["scan_result"]
        result = dict(name=Path(result).name, count=results.summary_count(Path(result)), elapsed_s=elapsed) if result else None
        return _redacted(dict(ok=True, running=s["running"], stopping=s["running"] and s["stop_event"].is_set(),
            elapsed_s=elapsed, item_label=s["scan_item_label"], overall=s["scan_overall"], stage=stage, lanes=lanes,
            # Thông báo chung chỉ cho bước không thuộc hai luồng (kiểm tra key, xuất Excel).
            message=progress.message if progress and stage not in ("scan", "filter", "analyze") else "",
            channels=_channel_rows(s["scan_channels"]), usage=usage, usage_history=[
                dict(t=row["Thời gian"].strftime("%H:%M:%S"), llm=row["Token LLM"], jev=row["Token Jev"])
                for row in s["scan_usage_history"]], turns=_turn_rows(s["scan_turns"]),
            log=s["scan_log"][max(0, int(log_since)):], log_total=len(s["scan_log"]),
            errors=list(dict.fromkeys(s["scan_errors"])), question=question, result=result,
            ended_without_result=s["scan_started"] is not None and not s["running"] and not result))


def is_running():
    with _lock:
        _drain_scan_queue()
        return _session["running"]


def has_question():
    with _lock:
        _drain_scan_queue()
        return _session["question"] is not None


def has_result():
    with _lock:
        _drain_scan_queue()
        return bool(_session["scan_result"])


def clear_result(path):
    with _lock:
        _drain_scan_queue()
        if _session["scan_result"] and Path(_session["scan_result"]).resolve() == Path(path).resolve():
            _session["scan_result"] = None
