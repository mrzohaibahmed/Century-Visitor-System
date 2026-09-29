"""E-mail (SMTP) settings saved by administrators: generic SMTP for any provider, encrypted password,
database-over-environment precedence, runtime use without restart, and the test e-mail.

No real mail provider is ever contacted: SMTP is either a recording stand-in for smtplib (to prove
exactly which host / port / security / login is used) or a local fake server on 127.0.0.1.
"""
import ast
import logging
import smtplib
import socket
import ssl
import threading
from pathlib import Path

import bson
import pytest

from app.core.secrets import generate_key
from app.services import email_settings as svc
from app.services import notifications as notifications_svc
from tests.conftest import make_settings
from tests.fake_smtp import FakeSMTP
from tests.test_notifications import HOST_EMAIL, check_in, directory, only_notification  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio

URL = "/api/v1/settings/email"
SECRET = "Smtp-App-Pass-9 xyz"                     # with a space, like a Gmail app password


@pytest.fixture
def settings():
    # No CG_SMTP_* (no environment fallback) unless a test sets it; the background sender is off so
    # the tests drive delivery themselves.
    return make_settings(secrets_key=generate_key(), email_worker=False)


def body(**change) -> dict:
    return {"enabled": True, "smtp_host": "smtp.gmail.com", "smtp_port": 587, "security": "starttls",
            "username": "gate.vms@gmail.com", "password": SECRET, "from_email": "gate.vms@gmail.com",
            "from_name": "Century Gate VMS", "reply_to": "reception@century.test"} | change


async def stored(harness) -> bytes:
    """Raw BSON of every settings document and audit entry."""
    docs = await harness.db.settings.find({}).to_list(None) + await harness.db.audit_logs.find({}).to_list(None)
    return b"".join(bson.encode(d) for d in docs)


# ---------------------------------------------------------------- recording stand-in for smtplib
class RecordingSMTP:
    """Records what the e-mail service asks of the SMTP server; sends nothing anywhere."""

    instances: list["RecordingSMTP"] = []
    implicit_tls = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list = []
        self.tls_context = None
        self.message = None
        RecordingSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.tls_context = context

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append("send")
        self.message = message


class RecordingSMTPSSL(RecordingSMTP):
    implicit_tls = True


@pytest.fixture
def recording(monkeypatch):
    RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSMTPSSL)
    return RecordingSMTP.instances


# ---------------------------------------------------------------- access
async def test_only_administrators_can_see_change_or_test_the_settings(harness, admin, guard):
    anonymous = harness.client()
    assert (await anonymous.get(URL)).status_code == 401
    for method, path, payload in [("GET", URL, None), ("PUT", URL, body()), ("DELETE", URL, None),
                                  ("POST", f"{URL}/test", {"to": "a@century.test"})]:
        r = await guard.request(method, path, json=payload)
        assert r.status_code == 403, (method, path)
        assert (await anonymous.request(method, path, json=payload)).status_code in (401, 403)
    assert (await admin.get(URL)).status_code == 200
    assert await harness.db.settings.find_one({"_id": svc.DOC_ID}) is None


async def test_changes_need_the_csrf_token(admin):
    r = await admin.post_without_csrf(f"{URL}/test", json={"to": "a@century.test"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


async def test_nothing_saved_and_no_environment_means_email_is_off(admin):
    got = (await admin.get(URL)).json()
    assert (got["source"], got["saved"], got["environment_configured"], got["password_status"]) == \
        ("none", False, False, "NOT_SET")


# ---------------------------------------------------------------- saving; the password stays on the server
async def test_saved_settings_encrypt_the_password_and_never_return_it(harness, admin):
    r = await admin.put(URL, json=body())
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["source"] == "database" and got["saved"] and got["password_status"] == "SAVED"
    assert (got["smtp_host"], got["smtp_port"], got["security"], got["username"]) == \
        ("smtp.gmail.com", 587, "starttls", "gate.vms@gmail.com")
    assert (got["from_name"], got["reply_to"]) == ("Century Gate VMS", "reception@century.test")
    for leaked in ("password", "ciphertext", "nonce", "ct", "kid"):
        assert leaked not in got
    assert SECRET not in r.text and SECRET not in (await admin.get(URL)).text

    doc = await harness.db.settings.find_one({"_id": svc.DOC_ID})
    assert set(doc["password"]) == {"v", "kid", "nonce", "ct"}
    assert SECRET.encode() not in await stored(harness)               # nowhere in plain text, audit included
    entry = await harness.db.audit_logs.find_one({"action": "EMAIL_SETTINGS_UPDATED"})
    assert entry["changes"]["password"] == "changed" and entry["changes"]["smtp_host"]["to"] == "smtp.gmail.com"
    assert entry["metadata"] == {"created": True}


async def test_the_password_is_kept_unless_it_would_go_somewhere_else(harness, admin):
    await admin.put(URL, json=body())
    sealed = (await harness.db.settings.find_one({"_id": svc.DOC_ID}))["password"]
    r = await admin.put(URL, json=body(password=None, from_name="Main Gate", reply_to=None, enabled=False))
    assert r.status_code == 200 and r.json()["password_status"] == "SAVED" and r.json()["enabled"] is False
    assert (await harness.db.settings.find_one({"_id": svc.DOC_ID}))["password"] == sealed
    for change in ({"smtp_host": "smtp.office365.com"}, {"smtp_port": 465}, {"security": "ssl"},
                   {"username": "other@gmail.com"}):
        r = await admin.put(URL, json=body(password=None, **change))
        assert r.status_code == 422 and r.json()["error"]["code"] == "email_password_required", change
    r = await admin.put(URL, json=body(smtp_host="smtp.office365.com", password="New-Pass-2"))
    assert r.status_code == 200 and r.json()["smtp_host"] == "smtp.office365.com"
    assert (await harness.db.settings.find_one({"_id": svc.DOC_ID}))["password"] != sealed


async def test_the_first_save_with_a_user_name_needs_a_password(admin):
    r = await admin.put(URL, json=body(password=None))
    assert r.status_code == 422 and r.json()["error"]["code"] == "email_password_required"


async def test_no_user_name_means_no_login_and_no_password(harness, admin):
    await admin.put(URL, json=body())
    r = await admin.put(URL, json=body(smtp_host="smtp.company.local", smtp_port=25, security="none",
                                       username=None, password=None))
    assert r.status_code == 200 and r.json()["password_status"] == "NOT_SET" and r.json()["username"] is None
    assert "password" not in await harness.db.settings.find_one({"_id": svc.DOC_ID})
    entry = await harness.db.audit_logs.find({"action": "EMAIL_SETTINGS_UPDATED"}).sort("timestamp", -1).to_list(1)
    assert entry[0]["changes"]["password"] == "removed"
    r = await admin.put(URL, json=body(username=None, password=SECRET))
    assert r.status_code == 422 and SECRET not in r.text


@pytest.mark.parametrize("change", [
    {"smtp_host": "http://smtp.example.com"}, {"smtp_host": "smtp.example.com:587"},
    {"smtp_host": "user@smtp.example.com"}, {"smtp_host": ""}, {"smtp_host": "smtp example com"},
    {"smtp_port": 0}, {"smtp_port": 70000},
    {"security": "tls"}, {"security": "SSL_TLS"}, {"from_email": "not-an-email"}, {"reply_to": "nope"},
    {"password": ""}, {"password": "x" * 257}, {"from_name": "Evil\r\nBcc: victim@example.com"},
    {"username": "bad\nuser"}, {"enabled": "maybe"}, {"provider": "GMAIL"},
])
async def test_invalid_settings_are_refused_without_echoing_them(harness, admin, change):
    r = await admin.put(URL, json=body(**change))
    assert r.status_code == 422, change
    assert SECRET not in r.text and "x" * 257 not in r.text
    assert await harness.db.settings.find_one({"_id": svc.DOC_ID}) is None


@pytest.mark.parametrize("host, port", [("smtp.gmail.com", 587), ("smtp.office365.com", 587), ("mail.example.com", 465),
                                        ("smtp.company.local", 25), ("10.10.20.15", 2525), ("fd00::25", 587)])
async def test_any_smtp_host_and_port_is_accepted(admin, host, port):
    r = await admin.put(URL, json=body(smtp_host=host, smtp_port=port))
    assert r.status_code == 200 and (r.json()["smtp_host"], r.json()["smtp_port"]) == (host, port)


async def test_production_refuses_a_login_over_an_unencrypted_connection(harness, admin):
    harness.app.state.settings = make_settings(environment="production", secrets_key=generate_key())
    r = await admin.put(URL, json=body(security="none", smtp_port=25))
    assert r.status_code == 422 and "unencrypted" in r.json()["error"]["message"]


async def test_without_a_server_key_passwords_cannot_be_saved(harness, admin):
    harness.app.state.settings = make_settings(secrets_key=None)
    r = await admin.put(URL, json=body())
    assert r.status_code == 503 and r.json()["error"]["code"] == "secrets_key_missing"


async def test_a_changed_server_key_makes_the_password_unreadable_not_wrong(harness, admin, recording):
    await admin.put(URL, json=body())
    harness.app.state.settings = make_settings(secrets_key=generate_key())
    assert (await admin.get(URL)).json()["password_status"] == "UNREADABLE"
    r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    assert (r.json()["status"], r.json()["code"]) == ("FAILED", "EMAIL_CREDENTIALS_UNREADABLE")
    assert recording == []                                           # nothing sent without a usable password


async def test_deleting_returns_to_the_environment_settings(harness, admin):
    await admin.put(URL, json=body())
    harness.app.state.settings = make_settings(secrets_key=generate_key(), smtp_host="mail.century.test",
                                               smtp_from="vms@century.test")
    assert (await admin.get(URL)).json()["source"] == "database"      # saved settings win
    assert (await admin.delete(URL)).status_code == 204
    got = (await admin.get(URL)).json()
    assert (got["source"], got["saved"], got["environment_configured"]) == ("environment", False, True)
    assert await harness.db.settings.find_one({"_id": svc.DOC_ID}) is None
    assert await harness.db.audit_logs.count_documents({"action": "EMAIL_SETTINGS_REMOVED"}) == 1
    assert (await admin.delete(URL)).status_code == 404


# ---------------------------------------------------------------- generic SMTP: any provider, same code
@pytest.mark.parametrize("name, config, implicit_tls, starttls, login", [
    ("Gmail-style", {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "security": "starttls"}, False, True, True),
    ("Microsoft 365-style", {"smtp_host": "smtp.office365.com", "smtp_port": 587, "security": "starttls",
                             "username": "vms@company.com", "from_email": "vms@company.com"}, False, True, True),
    ("Webmail/cPanel-style", {"smtp_host": "mail.example.com", "smtp_port": 465, "security": "ssl",
                              "username": "user@example.com", "from_email": "user@example.com"}, True, False, True),
    ("Custom relay", {"smtp_host": "smtp.company.local", "smtp_port": 25, "security": "none", "username": None,
                      "password": None, "from_email": "vms@company.local"}, False, False, False),
])
async def test_the_configured_values_alone_decide_how_mail_is_sent(admin, recording, name, config, implicit_tls,
                                                                  starttls, login):
    await admin.put(URL, json=body(**config))
    r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    assert r.json() == {"status": "SENT", "code": None, "message": None, "source": "database"}, name
    [server] = recording
    assert (server.host, server.port, server.implicit_tls) == (config["smtp_host"], config["smtp_port"], implicit_tls)
    assert ("starttls" in server.calls) is starttls
    for context in (server.context, server.tls_context):
        if context is not None:                                       # certificates always checked
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert implicit_tls is (server.context is not None) and starttls is (server.tls_context is not None)
    logins = [c for c in server.calls if isinstance(c, tuple)]
    assert logins == ([("login", config.get("username", "gate.vms@gmail.com"), SECRET)] if login else [])
    assert server.message["From"] == f"Century Gate VMS <{config.get('from_email', 'gate.vms@gmail.com')}>"
    assert server.message["Reply-To"] == "reception@century.test" and server.message["To"] == "admin@century.test"


def test_no_provider_specific_code():
    """No provider name in any code: names, strings or comparisons (docstrings may mention examples)."""
    docstrings, words = set(), []
    for path in ("app/services/email.py", "app/services/email_settings.py", "app/api/v1/email_settings.py",
                 "app/schemas/email_settings.py"):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            documented = isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            if documented and (doc := ast.get_docstring(node, clean=False)) is not None:
                docstrings.add(doc)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings:
                words.append(node.value.lower())
            elif isinstance(node, ast.Name):
                words.append(node.id.lower())
            elif isinstance(node, ast.Attribute):
                words.append(node.attr.lower())
    code = " ".join(words)
    for provider in ("gmail", "google", "office365", "outlook", "microsoft", "yahoo", "zoho", "cpanel"):
        assert provider not in code, provider


# ---------------------------------------------------------------- real sockets: success and safe failures
def _silent_server(banner: bytes | None):
    """Accepts connections; sends `banner` (None: never answers)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)

    held = []                                        # keep connections open: silence, not a hang-up

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            held.append(conn)
            if banner is not None:
                conn.sendall(banner)

    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1]


async def test_a_test_email_is_delivered(admin):
    with FakeSMTP() as smtp:
        await admin.put(URL, json=body(smtp_host="127.0.0.1", smtp_port=smtp.port, security="none",
                                       username=None, password=None))
        r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
        assert r.json()["status"] == "SENT"
        [message] = smtp.messages
        assert message["To"] == "admin@century.test" and message["Reply-To"] == "reception@century.test"
        assert "test e-mail" in message["Subject"]


async def test_the_test_email_is_audited_without_the_recipient_or_password(harness, admin):
    with FakeSMTP() as smtp:
        await admin.put(URL, json=body(smtp_host="127.0.0.1", smtp_port=smtp.port, security="none",
                                       username=None, password=None))
        await admin.post(f"{URL}/test", json={"to": "someone.private@century.test"})
    entry = await harness.db.audit_logs.find_one({"action": "EMAIL_TEST_SENT"})
    assert entry["result"] == "SUCCESS"
    assert entry["metadata"] == {"reason": None, "source": "database", "recipient_domain": "century.test"}
    assert b"someone.private" not in await stored(harness)


async def test_the_recipient_must_be_an_email_address(admin):
    await admin.put(URL, json=body())
    for bad in ("not-an-email", "", "a@b", "x@y.com\r\nBcc: z@y.com"):
        assert (await admin.post(f"{URL}/test", json={"to": bad})).status_code == 422, bad


async def test_not_configured(admin):
    r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    assert r.json() == {"status": "FAILED", "code": "EMAIL_NOT_CONFIGURED",
                        "message": "E-mail is not set up, or it is switched off.", "source": "none"}


def _plain(port: int, **change) -> dict:
    return body(smtp_host="127.0.0.1", smtp_port=port, security="none", username=None, password=None) | change


@pytest.mark.parametrize("scenario, expected", [
    ("refused", "EMAIL_CONNECTION_FAILED"),
    ("no banner", "EMAIL_CONNECTION_TIMEOUT"),
    ("garbage banner", "EMAIL_INVALID_RESPONSE"),
    ("ssl to a plain server", "EMAIL_TLS_FAILED"),
    ("starttls not offered", "EMAIL_TLS_FAILED"),
    ("recipient refused", "EMAIL_RECIPIENT_REFUSED"),
    ("login not offered", "EMAIL_AUTHENTICATION_FAILED"),
])
async def test_failures_are_safe_reasons(harness, admin, caplog, scenario, expected):
    harness.app.state.settings = make_settings(secrets_key=harness.app.state.settings.secrets_key.get_secret_value(),
                                               smtp_timeout_seconds=1, email_worker=False)
    caplog.set_level(logging.DEBUG)
    cleanup = None
    if scenario == "refused":
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        config = _plain(port)
    elif scenario in ("no banner", "garbage banner"):
        cleanup, port = _silent_server(None if scenario == "no banner" else b"hello, not smtp\r\n")
        config = _plain(port)
    else:
        smtp = FakeSMTP(mode="reject" if scenario == "recipient refused" else "ok").__enter__()
        cleanup = smtp
        config = {"ssl to a plain server": _plain(smtp.port, security="ssl"),
                  "starttls not offered": _plain(smtp.port, security="starttls"),
                  "recipient refused": _plain(smtp.port),
                  "login not offered": _plain(smtp.port, username="vms", password=SECRET)}[scenario]
    try:
        await admin.put(URL, json=config)
        r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    finally:
        if isinstance(cleanup, FakeSMTP):
            cleanup.__exit__(None, None, None)
        elif cleanup is not None:
            cleanup.close()
    # Windows retries a refused connection for about 2 s, so the 1 s timeout may come first: both are right.
    allowed = {expected, "EMAIL_CONNECTION_TIMEOUT"} if scenario == "refused" else {expected}
    result = r.json()
    assert r.status_code == 200 and result["status"] == "FAILED" and result["code"] in allowed, result
    assert result["message"] and "Traceback" not in r.text and "not smtp" not in r.text
    assert SECRET not in r.text and SECRET not in caplog.text


async def test_an_authentication_failure_hides_the_servers_reply(admin, monkeypatch):
    class Refusing(RecordingSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted (server detail)")

    monkeypatch.setattr(smtplib, "SMTP", Refusing)
    await admin.put(URL, json=body())
    r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    assert (r.json()["status"], r.json()["code"]) == ("FAILED", "EMAIL_AUTHENTICATION_FAILED")
    assert r.json()["message"] == "The mail server refused the user name or password."
    assert "server detail" not in r.text and "535" not in r.text and SECRET not in r.text


async def test_one_test_email_at_a_time(harness, admin):
    import asyncio
    harness.app.state.settings = make_settings(secrets_key=harness.app.state.settings.secrets_key.get_secret_value(),
                                               smtp_timeout_seconds=1, email_worker=False)
    srv, port = _silent_server(None)
    try:
        await admin.put(URL, json=_plain(port))
        first, second = await asyncio.gather(admin.post(f"{URL}/test", json={"to": "a@century.test"}),
                                             admin.post(f"{URL}/test", json={"to": "a@century.test"}))
    finally:
        srv.close()
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    assert "email_test_running" in first.text + second.text


# ---------------------------------------------------------------- runtime: host e-mails use the settings in use
async def test_host_emails_use_the_saved_settings_without_a_restart(harness, admin, guard, directory):  # noqa: F811 - fixture
    with FakeSMTP() as first, FakeSMTP() as second:
        await admin.put(URL, json=_plain(first.port))
        await check_in(guard, directory)
        assert (await only_notification(harness.db))["email"]["status"] == "PENDING"
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        [message] = first.messages
        assert message["To"] == HOST_EMAIL and message["Reply-To"] == "reception@century.test"
        assert message["From"] == "Century Gate VMS <gate.vms@gmail.com>"

        # Changed settings apply to the next e-mail, same running server.
        await admin.put(URL, json=_plain(second.port, from_name="Main Gate"))
        visitor = (await guard.post("/api/v1/visitors", json={
            "full_name": "Bilal Ahmed", "identity": {"type": "CNIC", "number": "35202-9999999-9"}})).json()
        await check_in(guard, directory, visitor=visitor)
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        assert len(first.messages) == 1 and second.messages[0]["From"] == "Main Gate <gate.vms@gmail.com>"


async def test_saved_settings_win_over_the_environment(harness, admin, guard, directory):  # noqa: F811 - fixture
    with FakeSMTP() as environment, FakeSMTP() as saved:
        harness.app.state.settings = make_settings(secrets_key=generate_key(), email_worker=False,
                                                   smtp_host="127.0.0.1", smtp_port=environment.port,
                                                   smtp_security="none", smtp_from="env@century.test")
        await admin.put(URL, json=_plain(saved.port))
        await check_in(guard, directory)
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        assert len(saved.messages) == 1 and environment.messages == []


async def test_the_environment_applies_when_nothing_is_saved(harness, guard, directory):  # noqa: F811 - fixture
    with FakeSMTP() as environment:
        harness.app.state.settings = make_settings(email_worker=False, smtp_host="127.0.0.1",
                                                   smtp_port=environment.port, smtp_security="none",
                                                   smtp_from="env@century.test")
        await check_in(guard, directory)
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        assert environment.messages[0]["From"] == "env@century.test"


async def test_switched_off_settings_send_nothing_even_with_an_environment(harness, admin, guard, directory):  # noqa: F811 - fixture
    with FakeSMTP() as environment:
        harness.app.state.settings = make_settings(secrets_key=generate_key(), email_worker=False,
                                                   smtp_host="127.0.0.1", smtp_port=environment.port,
                                                   smtp_security="none", smtp_from="env@century.test")
        await admin.put(URL, json=_plain(environment.port, enabled=False))
        await check_in(guard, directory)
        n = await only_notification(harness.db)
        assert (n["email"]["status"], n["email"]["reason"]) == ("NONE", "email_disabled")
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        assert environment.messages == []


async def test_switching_off_after_queueing_stops_the_email(harness, admin, guard, directory):  # noqa: F811 - fixture
    with FakeSMTP() as smtp:
        await admin.put(URL, json=_plain(smtp.port))
        await check_in(guard, directory)
        await admin.put(URL, json=_plain(smtp.port, enabled=False))
        await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
        n = await only_notification(harness.db)
        assert (n["email"]["status"], n["email"]["error"]) == ("FAILED", "email_disabled") and smtp.messages == []


async def test_nothing_configured_queues_no_email(harness, guard, directory):  # noqa: F811 - fixture
    await check_in(guard, directory)
    n = await only_notification(harness.db)
    assert (n["email"]["status"], n["email"]["reason"]) == ("NONE", "email_disabled")


async def test_unreadable_credentials_are_retried_not_leaked(harness, admin, guard, directory, caplog):  # noqa: F811 - fixture
    caplog.set_level(logging.DEBUG)
    await admin.put(URL, json=body())
    await check_in(guard, directory)
    harness.app.state.settings = make_settings(secrets_key=generate_key(), email_worker=False)    # key changed
    await notifications_svc.dispatch_due(harness.db, harness.app.state.settings)
    n = await only_notification(harness.db)
    assert (n["email"]["status"], n["email"]["error"]) == ("PENDING", "email_credentials_unreadable")
    assert SECRET not in caplog.text and SECRET not in str(n)


async def test_a_non_ascii_password_fails_safely(admin, monkeypatch, caplog):
    # smtplib logs in with ASCII only: a password like "Pässwort-1" must give a safe answer, not a 500.
    class AsciiOnly(RecordingSMTP):
        def login(self, user, password):
            password.encode("ascii")                  # what smtplib's AUTH does

    monkeypatch.setattr(smtplib, "SMTP", AsciiOnly)
    caplog.set_level(logging.DEBUG)
    await admin.put(URL, json=body(password="Pässwort-1"))
    r = await admin.post(f"{URL}/test", json={"to": "admin@century.test"})
    assert r.status_code == 200 and (r.json()["status"], r.json()["code"]) == ("FAILED", "EMAIL_AUTHENTICATION_FAILED")
    assert "Pässwort" not in r.text and "Pässwort" not in caplog.text and "\xe4" not in caplog.text
