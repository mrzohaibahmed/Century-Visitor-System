"""
Structured (JSON lines) logging to stderr, suitable for containers and log shippers.

Every line passes through redact() as a safety net: credentials inside URLs,
password/token fields and CNIC numbers are masked even if logged by mistake.
Callers should still log IDs rather than personal data.
"""
import json
import logging
import re
import sys
from datetime import UTC, datetime

from app.core.request_context import current_request_id

_REDACTIONS = [
    # user:password@ inside any URL (MongoDB URI, SMTP URL, ...)
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@]+@"), r"\1***@"),
    # password=..., "token": "...", secret: ...
    (re.compile(r"(?i)(\w*(?:password|passwd|pwd|secret|token))(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"), r"\1\2***"),
    # CNIC: 13 digits, optionally formatted 12345-1234567-1
    (re.compile(r"(?<!\d)\d{5}-?\d{7}-?\d(?!\d)"), "[CNIC]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id:
            entry["request_id"] = request_id
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, ensure_ascii=False, default=str))


class _AppHandler(logging.StreamHandler):
    """Marks the handler installed by configure_logging, so reconfiguring replaces only it
    (handlers added by the host process or test runner are left alone)."""


def configure_logging(level: str = "INFO") -> None:
    handler = _AppHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, _AppHandler):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    # pymongo DEBUG output can contain whole documents (personal data).
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    # Uvicorn's own access log is replaced by the request middleware (no query strings logged).
    logging.getLogger("uvicorn.access").disabled = True
