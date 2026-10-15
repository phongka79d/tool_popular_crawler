"""Điều phối quét Facebook, phân tích và xuất Excel."""
from __future__ import annotations

import argparse
import io
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

from backend.core import applog
from backend.core import config
from backend.core import db
from backend.services import export_excel
from backend.services import filters
from backend.services import jev_client
from backend.core import keys
from backend.services import llm_client
from backend.collectors import transcript, ytdlp
from backend.collectors.facebook import FacebookScanner, page_url_problem
from backend.core.errors import AuthError, BrowserUnavailable, LoginRequired, NetworkError, QuotaError, ServiceError
from backend.core.models import VIDEO_KINDS, Video

logger = logging.getLogger(__name__)

# Mỗi luồng phân tích tải audio từ Facebook (yt-dlp); giữ 4 để không tăng tải lên Facebook.
# Đo thực tế: phân tích đã chạy xong trong lúc quét kênh, thêm luồng không rút ngắn lần quét.
ANALYZE_WORKERS = 4
MAX_POST_IMAGES = 4
_METRICS = ("views", "reactions", "comments", "shares", "posted_at", "duration_s")


@dataclass
class RunParams:
    days: int
    formats: set[str]
    min_views: int = 0
    min_interactions: int = 0
    min_ratio_follow: float = 0
    match_all: bool = True
    length_limits: filters.LengthLimits = field(default_factory=dict)


def is_post_run(params: RunParams) -> bool:
    return params.formats == {"post"}


def download_images(urls: list[str]) -> list[bytes]:
    """Tải ảnh bài đăng còn hiệu lực; bỏ qua ảnh không tải hoặc đọc được."""
    images = []
    for url in urls[:MAX_POST_IMAGES]:
        try:
            response = requests.get(url, timeout=(10, 30))
            response.raise_for_status()
            data = response.content
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            images.append(data)
        except (requests.RequestException, OSError, ValueError):
            logger.warning("Không tải/đọc được một ảnh bài đăng, bỏ qua ảnh này")
    logger.info("Đã tải %d/%d ảnh bài đăng", len(images), min(len(urls), MAX_POST_IMAGES))
    return images


@dataclass
class Progress:
    stage: str
    page_index: int
    page_total: int
    page_url: str
    message: str
    done: bool = False
    error: str | None = None
    step: int = 0  # số việc đã xong trong bước hiện tại (ví dụ số video đã phân tích)
    steps: int = 0  # tổng số việc của bước hiện tại; 0 khi không đếm trước được
    usage: dict | None = None  # ảnh chụp run_log["usage"]: token, số lần gọi, thời gian và tốc độ LLM
    transient: bool = False  # cập nhật tạm (đếm ngược hoặc mức dùng): không ghi vào diễn biến
    turn: dict | None = None  # mức dùng riêng của mục vừa hoàn tất


def _safe_message(exc: object, credentials: dict) -> str:
    message = str(exc)
    for value in credentials.values():
        if value:
            message = message.replace(value, keys.mask(value))
    return message


def _count_text(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") if value is not None else "?"


def llm_speed(output_tokens: float, seconds: float) -> int | None:
    """Token LLM trả về mỗi giây chờ; None khi chưa có thời gian đo."""
    return round(output_tokens / seconds) if seconds > 0 else None


def _seconds_text(seconds: float) -> str:
    return f"{seconds:.1f}".replace(".", ",")


def analyze_workers(settings: dict) -> int:
    """Giới hạn số video phân tích song song để không tạo quá nhiều request API."""
    try:
        value = int(settings["scan"].get("analyze_workers", ANALYZE_WORKERS))
    except (TypeError, ValueError, OverflowError):
        value = ANALYZE_WORKERS
    return max(1, min(8, value))


def _speed_text(meter: dict) -> str:
    """Đuôi tiến độ cho một bước: ' · LLM 2.083 token trong 9,8 giây (213 token/giây)'."""
    if not meter["calls"]:
        return ""
    speed = llm_speed(meter["output_tokens"], meter["seconds"])
    return (f" · LLM {_count_text(meter['output_tokens'])} token trong {_seconds_text(meter['seconds'])} giây"
            + (f" ({_count_text(speed)} token/giây)" if speed is not None else ""))


def usage_summary(usage: dict) -> str:
    """Một câu tổng kết LLM của lần chạy; rỗng khi chưa gọi LLM."""
    calls = usage.get("llm_calls", 0)
    if not calls:
        return ""
    speed = llm_speed(usage.get("llm_output_tokens", 0), usage.get("llm_seconds", 0.0))
    return (f"LLM {usage.get('llm_model', '')}: {_count_text(calls)} lần gọi, "
            f"{_count_text(usage.get('llm_output_tokens', 0))} token trả về, "
            f"{_seconds_text(usage.get('llm_seconds', 0.0))} giây chờ"
            + (f", trung bình {_count_text(speed)} token/giây." if speed is not None else "."))


def check_all_keys(settings: dict, *, require_deepgram: bool = True) -> dict[str, str | None]:
    """Kiểm tra song song các dịch vụ cần cho loại quét."""
    names = ("jev", "deepgram", "llm") if require_deepgram else ("jev", "llm")
    credentials = {name: keys.get_key(name) for name in names}
    labels = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM"}

    def check(name: str) -> str | None:
        key = credentials[name]
        if not key:
            return f"Chưa có API key {labels[name]}. Vào Cài đặt để nhập key."
        try:
            if name == "jev":
                jev_client.check_key(key, settings["jev"]["model"])
            elif name == "deepgram":
                transcript.check_key(key)
            else:
                llm = settings["llm"]
                if not llm.get("base_url") or not llm.get("model"):
                    return "Chưa có endpoint hoặc model LLM. Vào Cài đặt để nhập lại."
                llm_client.check_key(llm["base_url"], key, llm["model"])
        except Exception as exc:
            reason = _safe_message(exc, credentials)
            return reason if isinstance(exc, ServiceError) else f"Không kiểm tra được key {labels[name]}: {reason}"
        return None

    with ThreadPoolExecutor(max_workers=len(credentials)) as pool:
        return dict(zip(credentials, pool.map(check, credentials)))


def _tokens(usage: dict | int | None) -> int:
    if isinstance(usage, int):
        return usage
    if not usage:
        return 0
    if "total_tokens" in usage:
        return int(usage["total_tokens"] or 0)
    return int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0) + int(
        usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    )


class _Stopped(Exception):
    pass


class _Paused(Exception):
    pass


def run(
    params: RunParams,
    settings: dict,
    on_progress: Callable[[Progress], None],
    stop_event: threading.Event,
    ask_user: Callable[[str, str, list[tuple[str, str]]], str] | None = None,
) -> Path | None:
    """Chạy một lượt; lỗi dịch vụ hoặc Dừng vẫn xuất dữ liệu đã có.

    `ask_user` chờ lựa chọn khi LLM hết hạn mức; CLI mặc định tiếp tục không có gợi ý.
    Mỗi kênh được bổ sung số liệu và lọc riêng; video đạt ngưỡng bắt đầu phân tích ngay,
    song song với nghỉ lịch sự và quét kênh tiếp theo; số luồng lấy từ scan.analyze_workers.
    `on_progress` và `ask_user` có thể được gọi từ các luồng đó.
    """
    run_started = time.monotonic()
    run_times = {"quét kênh": 0.0, "nghỉ giữa kênh": 0.0,
                 "chờ phân tích sau khi quét xong": 0.0, "xuất Excel": 0.0}
    analyses_done_at = None
    scan_finished_at = None
    export_started = None
    config.ensure_dirs()
    db.init_db()
    params_log = asdict(params)
    params_log["formats"] = sorted(params.formats)
    run_id = db.start_run(params_log)
    run_log = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "params": params_log,
        "pages": [],
        "usage": {"jev_tokens": 0, "jev_calls": 0, "llm_tokens": 0, "deepgram_minutes": 0.0,
                  "deepgram_calls": 0, "llm_model": settings["llm"]["model"],
                  "llm_calls": 0, "llm_output_tokens": 0, "llm_seconds": 0.0, "llm_cached": 0},
        "messages": [],
    }
    credentials = {name: keys.get_key(name) for name in ("jev", "deepgram", "llm")}
    post_run = is_post_run(params)
    item_label = "bài đăng" if post_run else "video"
    collected: list[Video] = []
    passed: list[Video] = []
    page_logs: dict[str, dict] = {}
    channels: list[str] = []
    page_index = 0
    page_url = ""
    partial = False
    llm_unavailable = False
    quota_choice: str | None = None
    jev = None
    llm = None
    analyzed_count = 0
    submitted_count = 0
    fatal: list[BaseException] = []
    filtered_pages: set[str] = set()
    # Các luồng phân tích chỉ ghi run_log, page_logs và bộ đếm khi giữ `lock`.
    lock = threading.RLock()
    clients_lock = threading.Lock()
    quota_lock = threading.Lock()
    # Một video gặp lỗi phải dừng cả lượt (key sai, mất mạng, tạm dừng...): các video còn lại không bắt đầu.
    abort = threading.Event()

    class ScanStop:
        """Ghép Dừng của người dùng và lỗi phân tích mà không đổi stop_event."""
        def is_set(self) -> bool:
            return stop_event.is_set() or abort.is_set()

        def wait(self, timeout: float | None = None) -> bool:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self.is_set():
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return self.is_set()
                abort.wait(0.1 if remaining is None else min(0.1, remaining))
            return True

    scan_stop = ScanStop()

    def emit(stage: str, message: str, *, error: str | None = None, done: bool = False,
             video: Video | None = None, step: int = 0, steps: int = 0, transient: bool = False,
             turn: dict | None = None) -> None:
        url, index = page_url, page_index
        if video is not None:
            url, index = video.page_url, channels.index(video.page_url) + 1
        if message and error is None and not transient:
            logger.info("%s", message)
        with lock:
            usage = dict(run_log["usage"])
        on_progress(Progress(stage, index, len(channels), url, message, done, error, step, steps,
                             usage, transient, dict(turn) if turn is not None else None))

    def checkpoint() -> None:
        if abort.is_set():
            with lock:
                if fatal:
                    raise fatal[0]
        if stop_event.is_set():
            raise _Stopped()

    def add_error(exc: object, video: Video | None = None) -> str:
        message = _safe_message(exc, credentials)
        url = video.page_url if video is not None else page_url
        with lock:
            run_log["messages"].append(message)
            if url in page_logs:
                page_logs[url]["errors"].append(message)
        logger.warning("%s", message)
        emit("error", message, error=message, video=video)
        return message

    def new_turn(label: str) -> dict:
        return {"label": label, "llm_calls": 0, "llm_tokens": 0, "llm_output_tokens": 0,
                "llm_seconds": 0.0, "jev_calls": 0, "jev_tokens": 0, "deepgram_minutes": 0.0}

    def add_usage(amounts: dict, turn: dict, *, stage: str = "analyze",
                  video: Video | None = None) -> None:
        with lock:
            for name, amount in amounts.items():
                run_log["usage"][name] += amount
                if name in turn:
                    turn[name] += amount
            if any(amounts.values()):
                emit(stage, "", video=video, transient=True)

    def take_llm(turn: dict, tokens: int = 0, *, stage: str = "analyze",
                 video: Video | None = None) -> dict:
        meter = llm_client.meter_take()
        add_usage({"llm_tokens": tokens, "llm_calls": meter["calls"],
                   "llm_output_tokens": meter["output_tokens"], "llm_seconds": meter["seconds"]},
                  turn, stage=stage, video=video)
        return meter

    def call_llm(turn: dict, function, *args, tokens, stage: str = "analyze",
                 video: Video | None = None):
        """Cập nhật ngay từng request, kể cả request sửa JSON bên trong client."""
        before = dict(turn)
        reported_tokens = 0

        def completed(amount: int) -> None:
            nonlocal reported_tokens
            reported_tokens += amount
            take_llm(turn, amount, stage=stage, video=video)

        try:
            with llm_client.observe_usage(completed):
                result = function(*args)
            take_llm(turn, max(0, tokens(result) - reported_tokens), stage=stage, video=video)
        finally:
            take_llm(turn, stage=stage, video=video)
        meter = {"calls": turn["llm_calls"] - before["llm_calls"],
                 "output_tokens": turn["llm_output_tokens"] - before["llm_output_tokens"],
                 "seconds": turn["llm_seconds"] - before["llm_seconds"]}
        return result, meter

    def call_jev(turn: dict, function, *args, video: Video):
        result = None
        try:
            result = function(*args)
            return result
        finally:
            add_usage({"jev_tokens": _tokens(result[-1]) if result is not None else 0,
                       "jev_calls": 1}, turn, video=video)

    def jev_instance():
        nonlocal jev
        with clients_lock:
            if jev is None:
                checkpoint()
                jev = jev_client.make_client(credentials["jev"], settings["jev"]["model"])
            return jev

    def llm_instance():
        nonlocal llm
        with clients_lock:
            if llm is None:
                checkpoint()
                llm = llm_client.make_client(settings["llm"]["base_url"], credentials["llm"])
            return llm

    def handle_llm_quota(video: Video | None = None) -> bool:
        """Hỏi một lần khi LLM hết hạn mức; các video đang phân tích song song dùng lại lựa chọn đó."""
        nonlocal llm_unavailable, quota_choice
        with quota_lock:
            if quota_choice is None:
                message = "Tài khoản LLM đã hết credit/hạn mức."
                options = [("continue", "Chạy tiếp không có gợi ý"), ("pause", "Tạm dừng")]
                quota_choice = ask_user("llm_quota", message, options) if ask_user else "continue"
                llm_unavailable = True
                decision = "tạm dừng" if quota_choice == "pause" else "tiếp tục không có gợi ý"
                default = " (mặc định CLI)" if ask_user is None else ""
                add_error(f"{message} Lựa chọn: {decision}{default}.", video)
            return quota_choice == "pause"

    def analyze(number: int, video: Video, taxonomy: dict, ban_words: list[str],
                keyterms: list[str], turn: dict) -> str:
        """Phân tích một video trên luồng phân tích; trả kết quả ngắn để báo tiến độ."""
        started = time.monotonic()
        durations: dict[str, float] = {}

        def add_time(stage: str, seconds: float) -> None:
            with lock:
                durations[stage] = durations.get(stage, 0.0) + seconds

        def measured(stage: str, function, *args, **kwargs):
            before = time.monotonic()
            try:
                return function(*args, **kwargs)
            finally:
                add_time(stage, time.monotonic() - before)

        def say(text: str) -> None:
            with lock:  # giữ thứ tự sự kiện đúng với bộ đếm video đã xong
                emit("analyze", f"{item_label.capitalize()} {number}: {text}", video=video,
                     step=analyzed_count, steps=submitted_count)

        checkpoint()
        llm_client.meter_take()  # bỏ số đo còn sót của mục trước trên luồng này
        try:
            if post_run:
                video.transcript = ""
                video.transcript_status = ""
                video.hook = next((line.strip() for line in video.caption.splitlines() if line.strip()), "")[:transcript.CAPTION_HOOK_CHARS].strip()
                say("đọc caption bài đăng…")
                if settings["scan"].get("read_images", False) and video.image_urls:
                    cached_images = db.get_transcript(video.video_id)
                    if cached_images and cached_images[1] == "images" and cached_images[0]:
                        video.transcript, video.transcript_status = cached_images
                        say("dùng nội dung ảnh đã lưu…")
                    else:
                        images = download_images(video.image_urls)
                        say(f"AI đọc {len(images)} ảnh…")
                        if images:
                            (video.transcript, _), meter = measured("LLM", call_llm,
                                turn, llm_client.describe_images,
                                llm_instance(), settings["llm"]["model"], images, video.caption,
                                llm_client.reasoning_effort(settings), tokens=lambda result: result[1],
                                video=video,
                            )
                            say(f"đọc ảnh xong{_speed_text(meter)}")
                            if video.transcript:
                                video.transcript_status = "images"
                                db.save_transcript(video.video_id, video.transcript, "images", video.hook)
            else:
                views = f"{_count_text(video.views)} lượt xem" if video.views is not None else "chưa rõ lượt xem"
                say(f"tải audio và chép lời ({views})…")
                warnings: list[str] = []
                deepgram_calls = 0

                def deepgram_completed(minutes: float) -> None:
                    nonlocal deepgram_calls
                    deepgram_calls += 1
                    add_usage({"deepgram_minutes": minutes, "deepgram_calls": 1}, turn, video=video)

                with transcript.observe_usage(deepgram_completed), transcript.observe_timing(add_time):
                    minutes = transcript.get_transcript(
                        video, credentials["deepgram"], settings["stt"], keyterms, config.DATA_DIR / "tmp",
                        warnings,
                    )
                if not deepgram_calls and minutes and minutes > 0:
                    add_usage({"deepgram_minutes": float(minutes), "deepgram_calls": 1}, turn, video=video)
                if video.transcript_language:
                    language = {"vi": "tiếng Việt", "en": "tiếng Anh"}.get(
                        video.transcript_language, video.transcript_language)
                    say(f"chép lời xong: thoại {language}")
                for warning in warnings:
                    with lock:
                        run_log["messages"].append(warning)
                    say(warning)
            def translate() -> None:
                if (video.transcript_language.startswith("en") and video.transcript
                        and not video.transcript_vi):
                    llm_client.meter_take()
                    say("LLM dịch thoại sang tiếng Việt…")
                    try:
                        (video.transcript_vi, _), _ = measured(
                            "dịch", call_llm, turn, llm_client.translate_to_vi,
                            settings["llm"]["base_url"], credentials["llm"],
                            settings["llm"]["model"], video.transcript,
                            tokens=lambda result: _tokens(result[1]), video=video,
                        )
                        db.save_transcript(
                            video.video_id, video.transcript, video.transcript_status, video.hook,
                            transcript_language=video.transcript_language, transcript_vi=video.transcript_vi,
                        )
                    except AuthError:
                        raise
                    except ServiceError as exc:
                        note = "Chưa dịch được thoại sang tiếng Việt"
                        if note not in video.notes:
                            video.notes.append(note)
                        warning = f"{note}: {_safe_message(exc, credentials)}"
                        logger.warning("%s", warning)
                        with lock:
                            run_log["messages"].append(warning)
                        say(warning)

            checkpoint()
            if (video.transcript_language.startswith("en") and video.transcript
                    and not video.transcript_vi):
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dich") as translation_pool:
                    translation = translation_pool.submit(translate)
                    try:
                        say("Jev gắn nhãn chủ đề, kiểu hook, cấu trúc…")
                        raw, _ = measured("Jev", call_jev, turn, jev_client.ask_labels,
                                          jev_instance(), video, taxonomy, settings, video=video)
                    finally:
                        # Luôn chờ dịch, chuyển AuthError về luồng chính trước khi gọi LLM.
                        translation.result()
            else:
                say("Jev gắn nhãn chủ đề, kiểu hook, cấu trúc…")
                raw, _ = measured("Jev", call_jev, turn, jev_client.ask_labels,
                                  jev_instance(), video, taxonomy, settings, video=video)
            video.jev = jev_client.interpret_labels(raw, settings, taxonomy)
            video.score = filters.formula_score(
                video.ratio_median, video.jev.get("replicable_p"), video.jev.get("hook_strength"),
                video.jev.get("relevant_p"), settings["score_weights"], video.jev.get("jev_viral"),
            )
            with lock:
                page_logs[video.page_url]["analyzed"] += 1
            checkpoint()
            if video.jev.get("relevant_p", 0) < 0.5:
                return "không liên quan ngành, không cần LLM"
            cached = db.get_llm(db.analysis_cache_key(video))
            if cached is not None:
                video.llm = cached
                with lock:
                    run_log["usage"]["llm_cached"] += 1
                    emit("analyze", "", video=video, transient=True)
                return "dùng phân tích LLM đã lưu"
            if llm_unavailable:
                return "không có gợi ý (LLM hết hạn mức)"
            for attempt in range(2):
                checkpoint()
                say("LLM viết phân tích và gợi ý (thường dưới 1 phút)…" if attempt == 0
                    else "Jev loại hết gợi ý; LLM viết lại lần 2…")
                analysis, _ = measured("LLM", call_llm,
                    turn, llm_client.write_analysis, llm_instance(), settings["llm"]["model"],
                    video, video.jev, settings, tokens=lambda result: _tokens(result.get("_usage")),
                    video=video,
                )
                video.llm = dict(analysis)
                # Không xuất gợi ý chưa được kiểm tra, kể cả khi xuất kết quả một phần.
                video.llm["goi_y_nhan_ban"] = []
                if analysis.get("_raw"):
                    video.notes.append(str(analysis["_raw"]))
                checkpoint()
                suggestions = llm_client.filter_banned(analysis.get("goi_y_nhan_ban", []), ban_words)
                kept: list = []
                if suggestions:
                    say(f"Jev kiểm tra {len(suggestions)} gợi ý…")
                    kept, check_raw, usage = measured("Jev duyệt", call_jev,
                        turn, jev_client.check_suggestions, jev_instance(), video, suggestions,
                        settings, video=video,
                    )
                    db.save_jev(db.analysis_cache_key(video), settings["jev"]["model"], "suggestion_check", check_raw, usage)
                video.llm["goi_y_nhan_ban"] = kept
                checkpoint()
                if kept or attempt == 1:
                    break
            db.save_llm(db.analysis_cache_key(video), settings["llm"]["model"], video.llm)
            return f"giữ {len(kept)} gợi ý"
        except QuotaError as exc:
            if exc.service != "llm":
                raise
            video.llm["goi_y_nhan_ban"] = []
            if handle_llm_quota(video):
                raise _Paused() from exc
            return "không có gợi ý (LLM hết hạn mức)"
        except (AuthError, NetworkError, LoginRequired, _Stopped, _Paused):
            raise
        except Exception as exc:
            video.notes.append(add_error(exc, video))
            return "lỗi, xem Nhật ký"
        finally:
            order = ("tải audio", "ffmpeg", "Deepgram", "dịch", "Jev", "LLM", "Jev duyệt")
            with lock:
                parts = [f"{stage} {_seconds_text(durations[stage])}s" for stage in order if stage in durations]
            parts.append(f"tổng {_seconds_text(time.monotonic() - started)}s")
            logger.info("%s %s · thời gian: %s", item_label.capitalize(), number, " · ".join(parts))

    def analyze_all(pool: ThreadPoolExecutor, page_passed: list[Video]) -> None:
        """Đưa video đạt ngưỡng của từng kênh vào cùng một hàng đợi phân tích."""
        nonlocal submitted_count
        if not page_passed:
            return
        taxonomy = config.load_json("taxonomy.json")
        ban_words = config.load_lines("config/ban_words.txt")
        keyterms = [] if post_run else config.load_lines(settings["stt"].get("keyterms_file", "config/keyterms.txt"))
        def task(number: int, video: Video) -> None:
            nonlocal analyzed_count
            nonlocal analyses_done_at
            turn = new_turn(f"{item_label.capitalize()} {number}")
            try:
                result = analyze(number, video, taxonomy, ban_words, keyterms, turn)
            except BaseException as exc:  # noqa: BLE001 - chuyển lỗi về luồng chính
                with lock:
                    if not abort.is_set():
                        fatal.append(exc)  # chỉ lỗi đầu tiên; các luồng khác dừng vì abort
                    abort.set()
                return
            finally:
                take_llm(turn, video=video)  # tính cả lượt thành công trước khi xử lý kết quả gặp lỗi
                with lock:
                    analyses_done_at = time.monotonic()
            meter = {"calls": turn["llm_calls"], "output_tokens": turn["llm_output_tokens"],
                     "seconds": turn["llm_seconds"]}
            with lock:
                analyzed_count += 1
                emit("analyze", f"{item_label.capitalize()} {number}: xong, {result}{_speed_text(meter)}.",
                     video=video, step=analyzed_count, steps=submitted_count, turn=turn)

        for video in page_passed:
            checkpoint()
            with lock:
                submitted_count += 1
                number = submitted_count
            pool.submit(task, number, video)

    @contextmanager
    def analysis_pool():
        pool = ThreadPoolExecutor(max_workers=analyze_workers(settings), thread_name_prefix="phan-tich")
        try:
            yield pool
        finally:
            pool.shutdown(wait=True)
            # Luồng phân tích có thể gặp lỗi trong khi đang xử lý Dừng ở luồng quét.
            if fatal:
                raise fatal[0]

    try:
        try:
            checkpoint()
            emit("keys", "Đang kiểm tra API key (Jev, LLM)…" if post_run else "Đang kiểm tra 3 API key (Jev, Deepgram, LLM)…")
            failures = check_all_keys(settings, require_deepgram=not post_run)
            checkpoint()
            if any(failures.values()):
                for reason in failures.values():
                    if reason:
                        add_error(reason)
                return None
            if post_run and settings["scan"].get("read_images", False):
                llm_settings = settings["llm"]
                if llm_client.vision_cached(llm_settings) is not True:
                    emit("keys", "Đang kiểm tra model LLM đọc ảnh…")
                    ok = llm_client.check_vision(llm_settings["base_url"], credentials["llm"], llm_settings["model"])
                    llm_settings["vision"] = {"base_url": llm_settings["base_url"], "model": llm_settings["model"], "ok": ok}
                    config.save_settings(settings)
                    if not ok:
                        add_error(llm_client.vision_error(llm_settings["model"]))
                        return None
            channels = config.load_lines("config/channels.txt")
            checkpoint()
            emit("scan", f"API key dùng được. Mở trình duyệt quét (chạy ẩn) cho {len(channels)} kênh…")
            with analysis_pool() as pool, FacebookScanner(hidden=True, settings=settings) as scanner:
                checkpoint()
                scanner.check_login()
                checkpoint()
                seen: set[str] = set()
                for page_index, page_url in enumerate(channels, 1):
                    checkpoint()
                    where = f"Kênh {page_index}/{len(channels)}"
                    entry = {
                        "url": page_url, "name": "", "followers": None,
                        "scanned": 0, "passed": 0, "analyzed": 0,
                        "skipped_reason": None, "errors": [],
                    }
                    run_log["pages"].append(entry)
                    page_logs[page_url] = entry
                    problem = page_url_problem(page_url)
                    if problem:
                        # Không mở trình duyệt, không nghỉ giữa kênh: báo ngay và sang kênh tiếp.
                        entry["skipped_reason"] = problem
                        emit("scan", f"{where}: bỏ qua. {problem}")
                        continue
                    emit("scan", f"{where}: mở trang, đọc tên và số người theo dõi…")
                    page_items: list[Video] = []
                    header_seconds = 0.0
                    scan_seconds = 0.0
                    tab_times = {}
                    try:
                        header_started = time.monotonic()
                        try:
                            page = scanner.get_page_info(page_url)
                        finally:
                            header_seconds = time.monotonic() - header_started
                            scan_finished_at = time.monotonic()
                        checkpoint()
                        entry.update(name=page.name, followers=page.followers)
                        db.upsert_page(page)
                        followers = (f"{_count_text(page.followers)} người theo dõi" if page.followers is not None
                                     else "chưa đọc được số người theo dõi")
                        emit("scan", f"{where}: {page.name or page_url} · {followers}")
                        if page.followers is None:
                            entry["errors"].append("Chưa xác định được follower của kênh")
                        scan_failure = None
                        try:
                            scan_started = time.monotonic()
                            rows = scanner.scan_page(
                                page_url, days=params.days, formats=params.formats,
                                max_videos=settings["scan"]["max_videos_per_page"], stop_event=scan_stop,
                                on_progress=lambda text, transient=False: emit(
                                    "scan", f"{where} · {text}", transient=transient),
                            )
                        except ServiceError as exc:
                            rows = getattr(exc, "partial_rows", [])
                            scan_failure = exc
                        finally:
                            scan_finished_at = time.monotonic()
                            scan_seconds = scan_finished_at - scan_started
                            tab_times = dict(getattr(scanner, "scan_timings", {}))
                        entry["errors"].extend(getattr(scanner, "scan_errors", []))
                        for row in rows:
                            # Giữ các mục đã thu được khi Dừng trong lúc cuộn.
                            values = dict(row)
                            values.update(page_url=page_url, page_name=page.name, page_followers=page.followers)
                            video = Video(**values)
                            if video.video_id in seen:
                                continue
                            if post_run and not video.caption and not settings["scan"].get("read_images", False):
                                continue  # bài chỉ có ảnh: cần bật đọc ảnh mới phân tích được
                            seen.add(video.video_id)
                            db.upsert_video(video)
                            collected.append(video)
                            page_items.append(video)
                            entry["scanned"] += 1
                        emit("scan", f"{where}: thu được {entry['scanned']} {item_label} trong {params.days} ngày.")
                        if scan_failure is not None:
                            raise scan_failure
                        if not entry["scanned"] and not page.name and page.followers is None:
                            add_error("Không đọc được page: kiểm tra link đúng và page công khai")
                        checkpoint()
                    except (_Stopped, _Paused, ServiceError):
                        raise
                    except Exception as exc:
                        add_error(exc)
                    finally:
                        run_times["quét kênh"] += header_seconds + scan_seconds
                        parts = [f"đầu trang {_seconds_text(header_seconds)}s"]
                        parts.extend(f"tab {label} {_seconds_text(seconds)}s"
                                     for label, seconds in tab_times.items())
                        logger.info("%s · thời gian quét: %s", where, " · ".join(parts))
                    checkpoint()
                    missing = [] if post_run else [video for video in page_items
                               if not video.caption or any(getattr(video, metric) is None for metric in _METRICS)]

                    def finish_page(page_items=page_items, missing=missing, entry=entry,
                                    page_url=page_url, report=None) -> None:
                        """Bổ sung số liệu (yt-dlp), lọc theo ngưỡng rồi đưa vào hàng đợi phân tích."""
                        for number, video in enumerate(missing, 1):
                            checkpoint()
                            if report is None:
                                emit("filter", f"Bổ sung số liệu còn thiếu (yt-dlp): video {number}/{len(missing)}…",
                                     step=number - 1, steps=len(missing))
                            else:
                                report(number - 1)
                            try:
                                ytdlp.fill_missing(video)
                            except Exception as exc:
                                video.notes.append(add_error(exc))
                            db.upsert_video(video)
                            checkpoint()
                        if report is not None:
                            report(len(missing))
                        emit("filter", f"Tính chỉ số và lọc {len(page_items)} {item_label} theo ngưỡng…")
                        filters.compute_metrics(page_items)
                        page_passed = filters.apply_filter(page_items, params.min_views, params.min_interactions,
                                                           params.min_ratio_follow, params.match_all,
                                                           params.length_limits, entry["errors"])
                        with lock:
                            passed.extend(page_passed)
                            filtered_pages.add(page_url)
                        entry["passed"] = len(page_passed)
                        for video in page_items:
                            for note in video.notes:
                                if note not in entry["errors"]:
                                    entry["errors"].append(note)
                        emit("filter", f"Đạt ngưỡng: {len(passed)}/{len(collected)} {item_label}.")
                        analyze_all(pool, page_passed)

                    if page_index == len(channels):
                        finish_page()
                        continue
                    # Bổ sung số liệu chạy trong lúc nghỉ giữa kênh thay vì trước đó: cùng số request,
                    # không chồng lên lúc cuộn kênh sau vì luôn chờ xong trước khi mở kênh tiếp.
                    rest = "Nghỉ giữa hai kênh như người dùng thật, tránh bị Facebook chặn"
                    side = {"left": None, "done": 0, "total": len(missing)}

                    def side_text() -> str:
                        parts = [rest if side["left"] is not None else "Hết giờ nghỉ, chờ bổ sung số liệu xong"]
                        if side["left"] is not None:
                            parts.append(f"còn {side['left']} giây")
                        if side["done"] < side["total"]:
                            parts.append(f"bổ sung số liệu (yt-dlp) {side['done']}/{side['total']} video")
                        return " · ".join(parts)

                    def report(done: int) -> None:
                        side["done"] = done
                        emit("scan", side_text(), transient=True)

                    def tick(left: int) -> None:
                        side["left"] = left
                        emit("scan", side_text(), transient=True)

                    if missing:
                        emit("scan", f"{rest}; đồng thời bổ sung số liệu còn thiếu cho {len(missing)} video…")
                    else:
                        emit("scan", f"{rest}…")
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="bo-sung") as side_pool:
                        finishing = side_pool.submit(finish_page, report=report)
                        pause_started = time.monotonic()
                        try:
                            scanner.polite_page_pause(stop_event=scan_stop, on_tick=tick)
                        finally:
                            run_times["nghỉ giữa kênh"] += time.monotonic() - pause_started
                            side["left"] = None
                        if not finishing.done():
                            emit("scan", side_text(), transient=True)
                        finishing.result()
                    checkpoint()
            checkpoint()
        except (LoginRequired, BrowserUnavailable) as exc:
            add_error(exc)
            if not collected:
                return None
            partial = True
        except _Paused:
            partial = True
        except _Stopped:
            partial = True
            run_log["messages"].append("Đã dừng theo yêu cầu; xuất dữ liệu đã có.")
        except AuthError as exc:
            message = ("API key [Deepgram] không hợp lệ. Vào Cài đặt để nhập lại."
                       if exc.service == "deepgram" else exc)
            add_error(message)
            partial = True
        except ServiceError as exc:
            add_error(exc)
            partial = True

        # Mục ở kênh bị ngắt trước bước lọc vẫn được xét cho kết quả một phần.
        if partial:
            remaining = [video for video in collected if video.page_url not in filtered_pages]
            filters.compute_metrics(remaining)
            extra = []
            for entry in run_log["pages"]:
                page_remaining = [video for video in remaining if video.page_url == entry["url"]]
                extra.extend(filters.apply_filter(
                    page_remaining, params.min_views, params.min_interactions,
                    params.min_ratio_follow, params.match_all, params.length_limits, entry["errors"]))
            passed_ids = {video.video_id for video in passed + extra}
            passed = [video for video in collected if video.video_id in passed_ids]
            for entry in run_log["pages"]:
                entry["passed"] = sum(video.page_url == entry["url"] for video in passed)
                for video in remaining:
                    if video.page_url == entry["url"]:
                        for note in video.notes:
                            if note not in entry["errors"]:
                                entry["errors"].append(note)
        if stop_event.is_set() and not collected:
            emit("done", "Đã dừng theo yêu cầu.", done=True)
            return None
        export_started = time.monotonic()
        summary = export_excel.build_summary_tables(passed)
        if not partial and not llm_unavailable and not stop_event.is_set():
            try:
                checkpoint()
                llm_client.meter_take()  # bỏ lượt kiểm tra key/ảnh trước khi quét
                turn = new_turn("Nhận xét tổng hợp")
                emit("export", "LLM viết nhận xét tổng hợp cho file Excel…")
                (summary["commentary"], _), meter = call_llm(
                    turn, llm_client.write_commentary, llm_instance(), settings["llm"]["model"],
                    summary, llm_client.reasoning_effort(settings), tokens=lambda result: _tokens(result[1]),
                    stage="export",
                )
                emit("export", f"Nhận xét tổng hợp xong{_speed_text(meter)}.", turn=turn)
            except QuotaError as exc:
                if exc.service != "llm":
                    add_error(exc)
                    partial = True
                else:
                    partial = handle_llm_quota()
            except ServiceError as exc:
                add_error(exc)
                partial = True
            except _Stopped:
                run_log["messages"].append("Đã dừng theo yêu cầu; xuất dữ liệu đã có.")
            except Exception as exc:
                add_error(exc)
        run_log["finished_at"] = datetime.now(timezone.utc).isoformat()
        emit("export", f"Đang ghi file Excel ({len(passed)} {item_label})…")
        result = export_excel.export(passed, summary, run_log)
        done_text = "Đã xuất kết quả một phần." if partial or stop_event.is_set() else "Đã xuất kết quả."
        emit("done", f"{done_text} {usage_summary(run_log['usage'])}".strip(), done=True)
        return result
    finally:
        if scan_finished_at is not None and analyses_done_at is not None:
            run_times["chờ phân tích sau khi quét xong"] = max(0.0, analyses_done_at - scan_finished_at)
        if export_started is not None:
            run_times["xuất Excel"] = time.monotonic() - export_started
        logger.info("Tổng thời gian: %s · tổng %ss",
                    " · ".join(f"{stage} {_seconds_text(seconds)}s" for stage, seconds in run_times.items()),
                    _seconds_text(time.monotonic() - run_started))
        if run_log["finished_at"] is None:
            run_log["finished_at"] = datetime.now(timezone.utc).isoformat()
        db.finish_run(run_id, run_log)
        for client in (jev, llm):
            close = getattr(client, "close", None)
            if close is not None:
                close()


def main(argv: list[str] | None = None) -> int:
    applog.use_utf8_console()  # tiếng Việt không làm hỏng CLI trên console mã cũ (cp1252)
    parser = argparse.ArgumentParser(description="Quét video hoặc bài đăng Facebook và xuất công thức nội dung ra Excel.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--formats", default="video,reel",
                        help="video,reel hoặc riêng post")
    parser.add_argument("--min-views", type=int, default=None)
    parser.add_argument("--min-interactions", type=int, default=None)
    parser.add_argument("--min-ratio", type=float, default=None,
                        help="Lượt xem tối thiểu so với follower (×); 0 tắt")
    for kind in ("video", "reel"):
        for bound in ("min", "max"):
            parser.add_argument(f"--{kind}-{bound}-seconds", type=float, default=None,
                                help="Thời lượng tính bằng giây; 0 = không giới hạn")
    parser.add_argument("--any", action="store_true",
                        help="Giữ video đạt một trong các điều kiện (mặc định: đạt tất cả)")
    args = parser.parse_args(argv)
    formats = {item.strip() for item in args.formats.split(",") if item.strip()}
    if args.days <= 0 or not formats or (formats != {"post"} and not formats <= VIDEO_KINDS):
        parser.error("Số ngày phải lớn hơn 0; định dạng gồm video,reel hoặc riêng post.")
    settings = config.load_settings()
    min_views = args.min_views if args.min_views is not None else settings["scan"].get("min_views", 10000)
    min_interactions = args.min_interactions if args.min_interactions is not None else settings["scan"].get("min_interactions", 200)
    min_ratio = args.min_ratio if args.min_ratio is not None else settings["scan"].get("min_ratio_follow", 0)
    if min_views < 0 or min_interactions < 0 or min_ratio < 0:
        parser.error("Ngưỡng tối thiểu không được âm.")
    match_all = False if args.any else settings["scan"].get("match_all", True)
    length_limits = {}
    for kind in ("video", "reel"):
        saved = settings["scan"].get("length_limits", {}).get(kind, (None, None))
        length_limits[kind] = tuple(
            (getattr(args, f"{kind}_{bound}_seconds") if getattr(args, f"{kind}_{bound}_seconds") is not None
             else saved[index]) or None
            for index, bound in enumerate(("min", "max"))
        )
    problem = filters.validate_length_limits(length_limits)
    if problem:
        parser.error(problem)
    params = RunParams(args.days, formats, min_views, min_interactions, min_ratio, match_all,
                       length_limits if formats != {"post"} else {})
    stop = threading.Event()
    import signal
    previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        result = run(params, settings, lambda progress: print(progress.message, flush=True), stop)
    finally:
        signal.signal(signal.SIGINT, previous)
    if result is not None:
        print(f"Kết quả: {result}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
