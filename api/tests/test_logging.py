import json
import logging

import pytest

from app.core.logging import JsonFormatter, redact
from app.core.request_context import reset_request_id, set_request_id


@pytest.mark.parametrize("raw,secret", [
    ("mongodb://app:Db-Secret-1@db.internal:27017/", "Db-Secret-1"),
    ("{'smtp_password': 'Smtp-Secret-1'}", "Smtp-Secret-1"),
    ("session_token=abc123def456", "abc123def456"),
    ("cnic 35202-1111111-1", "35202-1111111-1"),
    ("cnic 3520211111111", "3520211111111"),
])
def test_redaction(raw, secret):
    assert secret not in redact(raw)


def test_ordinary_text_is_untouched():
    text = "Visit V-2026-000123 checked in via mongodb://localhost:27017/"
    assert redact(text) == text


def test_json_log_line_includes_request_id_and_is_redacted():
    token = set_request_id("req-12345678")
    try:
        record = logging.LogRecord("t", logging.WARNING, __file__, 1, "uri %s", ("mongodb://u:P4ss-word@h/",), None)
        line = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)
    assert line["request_id"] == "req-12345678" and line["level"] == "WARNING"
    assert "P4ss-word" not in line["message"]
