"""Điều phối quét Facebook, phân tích và xuất Excel (PLAN §2, §5–9)."""
from __future__ import annotations

import argparse
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import config
import db
import export_excel
import filters
import jev_client
import keys
import llm_client
from collectors import transcript, ytdlp
from collectors.facebook import FacebookScanner
from errors import AuthError, LoginRequired, NetworkError, QuotaError, ServiceError
from models import Video

logger = logging.getLogger(__name__)


@dataclass
class RunParams:
    days: int
    formats: set[str]
    min_page_followers: int
    rules: dict
    preset: str


@dataclass
class Progress:
    stage: str
    page_index: int
    page_total: int
    page_url: str
    message: str
    done: bool = False
    error: str | None = None


def _safe_message(exc: object, credentials: dict) -> str:
    message = str(exc)
    for value in credentials.values():
        if value:
            message = message.replace(value, keys.mask(value))
    return message


def check_all_keys(settings: dict) -> dict[str, str | None]:
    """Kiểm tra lại cả ba dịch vụ trước khi mở Facebook; không lưu key."""
    credentials = {name: keys.get_key(name) for name in ("jev", "deepgram", "llm")}
    labels = {"jev": "Jev", "deepgram": "Deepgram", "llm": "LLM"}
    results: dict[str, str | None] = {}
    for name, key in credentials.items():
        if not key:
            results[name] = f"Chưa có API key {labels[name]}. Vào Cài đặt để nhập key."
            continue
        try:
            if name == "jev":
                jev_client.check_key(key, settings["jev"]["model"])
            elif name == "deepgram":
                transcript.check_key(key)
            else:
                llm = settings["llm"]
                if not llm.get("base_url") or not llm.get("model"):
                    results[name] = "Chưa có endpoint hoặc model LLM. Vào Cài đặt để nhập lại."
                    continue
                llm_client.check_key(llm["base_url"], key, llm["model"])
            results[name] = None
        except Exception as exc:
            reason = _safe_message(exc, credentials)
            results[name] = reason if isinstance(exc, ServiceError) else f"Không kiểm tra được key {labels[name]}: {reason}"
    return results


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


def run(
    params: RunParams,
    settings: dict,
    on_progress: Callable[[Progress], None],
    stop_event: threading.Event,
) -> Path | None:
    """Chạy một lượt; lỗi dịch vụ hoặc Dừng vẫn xuất phần dữ liệu đã thu được."""
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
        "usage": {"jev_tokens": 0, "llm_tokens": 0, "deepgram_minutes": 0.0},
        "messages": [],
    }
    credentials = {name: keys.get_key(name) for name in ("jev", "deepgram", "llm")}
    collected: list[Video] = []
    passed: list[Video] = []
    page_logs: dict[str, dict] = {}
    channels: list[str] = []
    page_index = 0
    page_url = ""
    partial = False
    llm_unavailable = False
    jev = None
    llm = None

    def emit(stage: str, message: str, *, error: str | None = None, done: bool = False) -> None:
        on_progress(Progress(stage, page_index, len(channels), page_url, message, done, error))

    def checkpoint() -> None:
        if stop_event.is_set():
            raise _Stopped()

    def add_error(exc: object) -> str:
        message = _safe_message(exc, credentials)
        run_log["messages"].append(message)
        if page_url in page_logs:
            page_logs[page_url]["errors"].append(message)
        logger.warning("%s", message)
        emit("error", message, error=message)
        return message

    def jev_instance():
        nonlocal jev
        if jev is None:
            checkpoint()
            jev = jev_client.make_client(credentials["jev"], settings["jev"]["model"])
        return jev

    def llm_instance():
        nonlocal llm
        if llm is None:
            checkpoint()
            llm = llm_client.make_client(settings["llm"]["base_url"], credentials["llm"])
        return llm

    try:
        try:
            checkpoint()
            emit("keys", "Đang kiểm tra API key…")
            failures = check_all_keys(settings)
            checkpoint()
            if any(failures.values()):
                for reason in failures.values():
                    if reason:
                        add_error(reason)
                return None
            channels = config.load_lines("config/channels.txt")
            checkpoint()
            with FacebookScanner(headless=True, settings=settings) as scanner:
                checkpoint()
                scanner.check_login()
                checkpoint()
                seen: set[str] = set()
                for page_index, page_url in enumerate(channels, 1):
                    checkpoint()
                    entry = {
                        "url": page_url, "name": "", "followers": None,
                        "scanned": 0, "passed": 0, "analyzed": 0,
                        "skipped_reason": None, "errors": [],
                    }
                    run_log["pages"].append(entry)
                    page_logs[page_url] = entry
                    emit("scan", "Đang quét kênh…")
                    try:
                        page = scanner.get_page_info(page_url)
                        checkpoint()
                        entry.update(name=page.name, followers=page.followers)
                        db.upsert_page(page)
                        if not filters.page_allowed(page.followers, params.min_page_followers):
                            entry["skipped_reason"] = "Dưới ngưỡng follower"
                            emit("scan", "Dưới ngưỡng follower")
                        else:
                            if page.followers is None:
                                entry["errors"].append("Chưa xác định được follower của kênh")
                            rows = scanner.scan_page(
                                page_url, days=params.days, formats=params.formats,
                                max_videos=settings["scan"]["max_videos_per_page"], stop_event=stop_event,
                            )
                            for row in rows:
                                # Preserve already collected rows even if Dừng was pressed during scrolling.
                                values = dict(row)
                                values.update(page_url=page_url, page_name=page.name, page_followers=page.followers)
                                video = Video(**values)
                                if video.video_id in seen:
                                    continue
                                seen.add(video.video_id)
                                db.upsert_video(video)
                                collected.append(video)
                                entry["scanned"] += 1
                            checkpoint()
                    except (_Stopped, NetworkError, LoginRequired):
                        raise
                    except Exception as exc:
                        add_error(exc)
                    checkpoint()
                    if page_index < len(channels):
                        scanner.polite_page_pause(stop_event=stop_event)
                        checkpoint()
            checkpoint()
            emit("filter", "Đang tính chỉ số và lọc video…")
            filters.compute_metrics(collected)
            passed = filters.apply_filter(collected, params.rules)
            for video in collected:
                for note in video.notes:
                    if note not in page_logs[video.page_url]["errors"]:
                        page_logs[video.page_url]["errors"].append(note)
            for video in passed:
                page_logs[video.page_url]["passed"] += 1
            taxonomy = config.load_json("taxonomy.json")
            ban_words = config.load_lines("config/ban_words.txt")
            keyterms = config.load_lines(settings["stt"].get("keyterms_file", "config/keyterms.txt"))
            for video in passed:
                checkpoint()
                page_url = video.page_url
                page_index = channels.index(page_url) + 1
                emit("analyze", "Đang phân tích video…")
                try:
                    if any(getattr(video, metric) is None for metric in ("views", "reactions", "comments", "shares")):
                        ytdlp.fill_missing(video)
                        checkpoint()
                        db.upsert_video(video)
                    minutes = transcript.get_transcript(
                        video, credentials["deepgram"], settings["stt"], keyterms, config.DATA_DIR / "tmp",
                    )
                    run_log["usage"]["deepgram_minutes"] += float(minutes or 0)
                    checkpoint()
                    raw, usage = jev_client.ask_labels(jev_instance(), video, taxonomy, settings)
                    run_log["usage"]["jev_tokens"] += _tokens(usage)
                    video.jev = jev_client.interpret_labels(raw, settings, taxonomy)
                    video.score = filters.formula_score(
                        video.ratio_median, video.jev.get("replicable_p"), video.jev.get("hook_strength"),
                        video.jev.get("relevant_p"), settings["score_weights"],
                    )
                    page_logs[page_url]["analyzed"] += 1
                    checkpoint()
                    if video.jev.get("relevant_p", 0) < 0.5:
                        continue
                    cached = db.get_llm(video.video_id)
                    if cached is not None:
                        video.llm = cached
                        continue
                    if llm_unavailable:
                        continue
                    for attempt in range(2):
                        checkpoint()
                        analysis = llm_client.write_analysis(llm_instance(), settings["llm"]["model"], video, video.jev, settings)
                        run_log["usage"]["llm_tokens"] += _tokens(analysis.get("_usage"))
                        video.llm = dict(analysis)
                        # Unchecked suggestions must never appear in a partial export.
                        video.llm["goi_y_nhan_ban"] = []
                        if analysis.get("_raw"):
                            video.notes.append(str(analysis["_raw"]))
                        checkpoint()
                        suggestions = llm_client.filter_banned(analysis.get("goi_y_nhan_ban", []), ban_words)
                        kept = []
                        if suggestions:
                            kept, check_raw, usage = jev_client.check_suggestions(jev_instance(), video, suggestions, settings)
                            run_log["usage"]["jev_tokens"] += _tokens(usage)
                            db.save_jev(video.video_id, settings["jev"]["model"], "suggestion_check", check_raw, usage)
                        video.llm["goi_y_nhan_ban"] = kept
                        checkpoint()
                        if kept or attempt == 1:
                            break
                    db.save_llm(video.video_id, settings["llm"]["model"], video.llm)
                except QuotaError as exc:
                    if exc.service != "llm":
                        raise
                    llm_unavailable = True
                    video.llm["goi_y_nhan_ban"] = []
                    add_error(f"{_safe_message(exc, credentials)} Lựa chọn: tiếp tục không có gợi ý.")
                except (AuthError, NetworkError, LoginRequired, _Stopped):
                    raise
                except Exception as exc:
                    video.notes.append(add_error(exc))
        except LoginRequired as exc:
            add_error(exc)
            if not collected:
                return None
            partial = True
        except _Stopped:
            partial = True
            run_log["messages"].append("Đã dừng theo yêu cầu; xuất dữ liệu đã có.")
        except ServiceError as exc:
            add_error(exc)
            partial = True

        # A stop or network failure can happen before the filtering stage.
        if partial and not passed and collected:
            filters.compute_metrics(collected)
            passed = filters.apply_filter(collected, params.rules)
            for entry in run_log["pages"]:
                entry["passed"] = sum(video.page_url == entry["url"] for video in passed)
        if stop_event.is_set() and not collected:
            emit("done", "Đã dừng theo yêu cầu.", done=True)
            return None
        summary = export_excel.build_summary_tables(passed)
        if not partial and not llm_unavailable and not stop_event.is_set():
            try:
                checkpoint()
                summary["commentary"], usage = llm_client.write_commentary(llm_instance(), settings["llm"]["model"], summary)
                run_log["usage"]["llm_tokens"] += _tokens(usage)
            except QuotaError as exc:
                add_error(f"{_safe_message(exc, credentials)} Lựa chọn: tiếp tục không có gợi ý.")
            except ServiceError as exc:
                add_error(exc)
                partial = True
            except _Stopped:
                run_log["messages"].append("Đã dừng theo yêu cầu; xuất dữ liệu đã có.")
            except Exception as exc:
                add_error(exc)
        run_log["finished_at"] = datetime.now(timezone.utc).isoformat()
        emit("export", "Đang xuất Excel…")
        result = export_excel.export(passed, summary, run_log)
        emit("done", "Đã xuất kết quả một phần." if partial or stop_event.is_set() else "Đã xuất kết quả.", done=True)
        return result
    finally:
        if run_log["finished_at"] is None:
            run_log["finished_at"] = datetime.now(timezone.utc).isoformat()
        db.finish_run(run_id, run_log)
        for client in (jev, llm):
            close = getattr(client, "close", None)
            if close is not None:
                close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quét video Facebook và xuất công thức nội dung ra Excel.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--preset", choices=list(filters.PRESETS), default="no_bat_thuong")
    parser.add_argument("--formats", default="reel,video")
    parser.add_argument("--min-page-followers", type=int, default=None)
    args = parser.parse_args(argv)
    formats = {item.strip() for item in args.formats.split(",") if item.strip()}
    if args.days <= 0 or not formats or not formats <= {"reel", "video"}:
        parser.error("Số ngày phải lớn hơn 0; định dạng chỉ gồm reel,video.")
    settings = config.load_settings()
    minimum = args.min_page_followers if args.min_page_followers is not None else settings["scan"]["min_page_followers"]
    if minimum < 0:
        parser.error("Follower tối thiểu không được âm.")
    params = RunParams(args.days, formats, minimum, dict(filters.PRESETS[args.preset]["rules"]), args.preset)
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
