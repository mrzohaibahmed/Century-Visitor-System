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


# ---------------------------------------------------------------- request IDs vs CNICs (Phase 7A fix)
@pytest.mark.parametrize("request_id", [
    "dfe1234567890123ad8ae5499dc647e1",        # 13+ digits inside a hex ID: once logged as "dfe[CNIC]ad8…"
    "6c6c5ee985cb4ff783d8ad904d3791d2",
    "a3520112345671b",
    "req-12345678",
])
def test_random_request_ids_are_not_mistaken_for_cnics(request_id):
    assert redact(f'"request_id": "{request_id}"') == f'"request_id": "{request_id}"'


def test_every_generated_request_id_survives_the_log_formatter():
    import uuid
    for _ in range(2000):
        request_id = uuid.uuid4().hex
        token = set_request_id(request_id)
        try:
            record = logging.LogRecord("t", logging.INFO, __file__, 1, "request", (), None)
            assert json.loads(JsonFormatter().format(record))["request_id"] == request_id
        finally:
            reset_request_id(token)


@pytest.mark.parametrize("raw", [
    "cnic=3520211111111", "CNIC:35202-1111111-1", '{"identity": "35202-1111111-1"}', "(3520211111111)",
    "id 35202 1111111 1".replace(" ", "-"), "35202-1111111-1", "lookup 3520211111111.",
])
def test_cnics_next_to_punctuation_are_still_redacted(raw):
    assert "1111111" not in redact(raw)
