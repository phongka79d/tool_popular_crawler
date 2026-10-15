"""Redacted application logs, including the previous launch when available."""
import logging
import os

from backend.core import applog
from backend.api.common import fail

logger = logging.getLogger("app.api.logs")
LOG_MAX_RECORDS = 500


def _sessions() -> dict:
    files = {"current": ("Lần mở này", applog.LOG_FILE)}
    if applog.PREVIOUS_LOG_FILE.exists():
        files["previous"] = ("Lần mở trước", applog.PREVIOUS_LOG_FILE)
    return files


def get_logs(session: str = "current", problems_only: bool = True) -> dict:
    files = _sessions()
    selected = session if session in files else "current"
    path = files[selected][1]
    records = applog.read_records(problems_only, path)
    return {"ok": True, "sessions": [{"id": key, "label": value[0]} for key, value in files.items()],
            "session": selected, "path": str(path),
            "records": [applog.redact(record) for record in reversed(records[-LOG_MAX_RECORDS:])]}


def open_log_file(session: str) -> dict:
    files = _sessions()
    path = files.get(session, files["current"])[1]
    try:
        os.startfile(path)
    except (OSError, AttributeError) as exc:
        message = "Không mở được file nhật ký trên máy này."
        logger.warning("%s", message, exc_info=exc)
        return fail(message)
    return {"ok": True}
