"""Phase 6A: host-arrival notifications (in-app + e-mail), delivery tracking, retries, isolation."""
import asyncio
import logging
import socket
import time
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.services import email as email_svc
from app.services import notifications as svc
from tests.conftest import TEST_MONGO_URI, make_settings
from tests.fake_smtp import FakeSMTP
from tests.test_visitors import CNIC, new_visitor

pytestmark = pytest.mark.anyio
HOST_EMAIL = "sara.ahmed@century.test"
LIST = "/api/v1/notifications"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


SMTP_PORT = _free_port()          # the fake server listens here only in the tests that start it


@pytest.fixture
def settings():
    """E-mail switched on (plain SMTP to the local fake server); the background sender is off so each
    test drives delivery itself with dispatch_due()."""
    s = make_settings(smtp_host="127.0.0.1", smtp_port=SMTP_PORT, smtp_security="none",
                      smtp_from="Century Gate VMS <vms@century.test>", email_worker=False)
    yield s
    MongoClient(TEST_MONGO_URI).drop_database(s.mongo_db)


@pytest.fixture
async def directory(harness, admin):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()
    dep = (await admin.post("/api/v1/departments", json={"name": "HR"})).json()
    me = await harness.db.users.find_one({"username": "admin"})
    host = (await admin.post("/api/v1/hosts", json={"name": "Sara Ahmed", "department_id": dep["id"],
                                                    "email": HOST_EMAIL, "linked_user_id": str(me["_id"])})).json()
    return {"gate": gate, "dep": dep, "host": host, "admin_id": me["_id"]}


async def check_in(client, directory, visitor=None, **overrides):
    visitor = visitor or await new_visitor(client)
    body = {"visitor_id": visitor["id"], "host_id": directory["host"]["id"], "reason_code": "INTERVIEW", **overrides}
    r = await client.post("/api/v1/visits", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def only_notification(db):
    docs = await db.notifications.find().to_list(length=10)
    assert len(docs) == 1, docs
    return docs[0]


# ---------------------------------------------------------------------------------------------- creation
async def test_check_in_creates_one_notification_for_the_linked_account_and_the_host_email(harness, guard,
                                                                                            directory):
    visit = await check_in(guard, directory)
    n = await only_notification(harness.db)
    assert n["event_key"] == f"HOST_VISITOR_ARRIVAL:{visit['id']}" and n["type"] == "HOST_VISITOR_ARRIVAL"
    assert n["recipient_user_id"] == directory["admin_id"] and n["read_at"] is None
    assert n["visit_id"] == ObjectId(visit["id"]) and n["host_id"] == ObjectId(directory["host"]["id"])
    assert n["email"]["status"] == "PENDING" and n["email"]["to"] == HOST_EMAIL and n["email"]["attempts"] == 0
    assert n["data"]["visitor_name"] == "Ali Khan" and n["data"]["gate_name"] == "Main Gate"
    assert n["data"]["department_name"] == "HR" and CNIC not in str(n) and "0300" not in str(n)


@pytest.mark.parametrize("host_fields,recipient,email_status", [
    ({"email": HOST_EMAIL}, False, "PENDING"),                    # e-mail only (no linked account)
    ({"link": True}, True, "NONE"),                              # in-app only (host has no address)
])
async def test_partial_hosts(harness, admin, guard, directory, host_fields, recipient, email_status):
    body = {"name": "Imran Ali", "department_id": directory["dep"]["id"]}
    if "email" in host_fields:
        body["email"] = host_fields["email"]
    if host_fields.get("link"):
        body["linked_user_id"] = str(directory["admin_id"])
    host = (await admin.post("/api/v1/hosts", json=body)).json()
    await check_in(guard, {**directory, "host": host})
    n = await only_notification(harness.db)
    assert (n["recipient_user_id"] is not None) is recipient and n["email"]["status"] == email_status
    if email_status == "NONE":
        assert n["email"]["reason"] == "no_address" and n["email"]["to"] is None


async def test_nobody_to_tell_means_no_notification(harness, admin, guard, directory):
    body = {"name": "Imran Ali", "department_id": directory["dep"]["id"]}
    host = (await admin.post("/api/v1/hosts", json=body)).json()
    await check_in(guard, {**directory, "host": host})
    assert await harness.db.notifications.count_documents({}) == 0


async def test_unlisted_host_is_never_emailed_and_the_visit_stays_flagged(harness, guard, directory):
    visitor = await new_visitor(guard)
    r = await guard.post("/api/v1/visits", json={"visitor_id": visitor["id"], "unlisted_host_name": "Imran Ali",
                                                 "department_id": directory["dep"]["id"], "reason_code": "DELIVERY"})
    assert r.status_code == 201 and r.json()["host_unlisted"] is True
    assert await harness.db.notifications.count_documents({}) == 0


async def test_a_disabled_linked_account_gets_nothing_in_app(harness, admin, guard, directory):
    guard_user = await harness.db.users.find_one({"username": "guard1"})
    await admin.patch(f"/api/v1/hosts/{directory['host']['id']}", json={"linked_user_id": str(guard_user["_id"])})
    await harness.db.users.update_one({"_id": guard_user["_id"]}, {"$set": {"is_active": False}})
    await check_in(admin, directory)
    n = await only_notification(harness.db)
    assert n["recipient_user_id"] is None and n["email"]["status"] == "PENDING"


async def test_email_switched_off_records_why(harness, guard, directory):
    visit = {"_id": ObjectId(), "visitor_id": ObjectId(), "check_in_at": datetime.now(UTC), "reason_code": "INTERVIEW",
             "snapshot": {"visitor_name": "Ali Khan", "host_name": "Sara Ahmed"}}
    host = {"_id": ObjectId(), "email": HOST_EMAIL}
    doc = await svc.create_host_arrival(harness.db, make_settings(), visit, host, session=None)
    assert doc["email"] == {"status": "NONE", "to": None, "attempts": 0, "reason": "email_disabled"}


async def test_one_notification_per_visit_is_enforced_by_the_database(harness, guard, directory):
    visit = await check_in(guard, directory)
    n = await only_notification(harness.db)
    with pytest.raises(DuplicateKeyError):
        await harness.db.notifications.insert_one({**n, "_id": ObjectId()})
    # Repeating the check-in request does not create a second visit or notification.
    again = await guard.post("/api/v1/visits", json={"visitor_id": visit["visitor"]["id"],
                                                     "host_id": directory["host"]["id"], "reason_code": "INTERVIEW"})
    assert again.status_code == 409 and await harness.db.notifications.count_documents({}) == 1


async def test_notification_and_visit_are_all_or_nothing(harness, guard, directory, monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError("notification store unavailable")
    monkeypatch.setattr(svc, "create_host_arrival", broken)
    visitor = await new_visitor(guard)
    r = await guard.post("/api/v1/visits", json={"visitor_id": visitor["id"], "host_id": directory["host"]["id"],
                                                 "reason_code": "INTERVIEW"})
    assert r.status_code == 500
    assert await harness.db.visits.count_documents({}) == 0          # no visit without its notification


# ---------------------------------------------------------------------------------------------- e-mail
async def test_check_in_succeeds_while_the_mail_server_is_down(harness, settings, guard, directory):
    started = time.perf_counter()
    await check_in(guard, directory)                                     # nothing listens on SMTP_PORT
    assert time.perf_counter() - started < 5
    assert await svc.dispatch_due(harness.db, settings) == 1
    n = await only_notification(harness.db)
    assert n["email"]["status"] == "PENDING" and n["email"]["attempts"] == 1
    assert n["email"]["error"] == "ConnectionRefusedError"
    retry_in = n["email"]["next_attempt_at"] - datetime.now(UTC)
    assert timedelta(seconds=50) < retry_in <= timedelta(minutes=1)
    assert await svc.dispatch_due(harness.db, settings) == 0            # not due yet: nothing is sent again


async def test_email_is_sent_once_with_safe_content(harness, settings, guard, directory):
    visit = await check_in(guard, directory)
    with FakeSMTP(port=SMTP_PORT) as smtp:
        results = await asyncio.gather(*(svc.dispatch_due(harness.db, settings) for _ in range(3)))
        assert sum(results) == 1 and await svc.dispatch_due(harness.db, settings) == 0
    assert len(smtp.messages) == 1
    message = smtp.messages[0]
    assert message["To"] == HOST_EMAIL and message["Subject"] == "Visitor arrived: Ali Khan"
    text = message.get_payload(0).get_payload(decode=True).decode()
    assert "Ali Khan has arrived" in text and "Main Gate" in text and "Interview" in text
    raw = message.as_string()
    for secret in (CNIC, CNIC.replace("-", ""), visit["id"], visit["visitor"]["id"], "0300"):
        assert secret not in raw
    n = await only_notification(harness.db)
    assert n["email"]["status"] == "SENT" and n["email"]["sent_at"] and n["email"]["attempts"] == 1


async def test_a_refused_recipient_is_not_retried(harness, settings, guard, directory):
    await check_in(guard, directory)
    with FakeSMTP(mode="reject", port=SMTP_PORT):
        await svc.dispatch_due(harness.db, settings)
    n = await only_notification(harness.db)
    assert n["email"]["status"] == "FAILED" and n["email"]["error"] == "SMTPRecipientsRefused 550"
    assert n["email"]["next_attempt_at"] is None


async def test_a_temporary_refusal_is_retried(harness, settings, guard, directory):
    await check_in(guard, directory)
    with FakeSMTP(mode="tempfail", port=SMTP_PORT):
        await svc.dispatch_due(harness.db, settings)
    n = await only_notification(harness.db)
    assert n["email"]["status"] == "PENDING" and n["email"]["error"] == "SMTPRecipientsRefused 451"


async def test_retries_are_bounded_with_growing_delays(harness, settings, guard, directory):
    await check_in(guard, directory)
    calls = []

    def failing(_settings, _message):
        calls.append(1)
        raise email_svc.EmailError("SMTPServerDisconnected", permanent=False)

    delays = []
    for _ in range(10):
        await harness.db.notifications.update_many({"email.status": "PENDING"},
                                                   {"$set": {"email.next_attempt_at": datetime.now(UTC)}})
        await svc.dispatch_due(harness.db, settings, send=failing)
        n = await only_notification(harness.db)
        if n["email"]["status"] == "PENDING":
            delays.append(round((n["email"]["next_attempt_at"] - n["email"]["last_attempt_at"]).total_seconds() / 60))
    assert len(calls) == svc.MAX_ATTEMPTS == 5
    assert delays == [1, 5, 15, 60]
    assert n["email"]["status"] == "FAILED" and n["email"]["attempts"] == 5


async def test_an_interrupted_send_is_never_repeated(harness, settings, guard, directory):
    await check_in(guard, directory)
    past = datetime.now(UTC) - timedelta(minutes=5)
    await harness.db.notifications.update_one({}, {"$set": {"email.status": "SENDING", "email.lease_until": past,
                                                            "email.attempts": 1}})
    sent = []
    await svc.dispatch_due(harness.db, settings, send=lambda *a: sent.append(1))
    n = await only_notification(harness.db)
    assert sent == [] and n["email"]["status"] == "FAILED" and n["email"]["error"] == "interrupted"


async def test_the_smtp_password_never_reaches_logs_or_the_database(harness, guard, directory, caplog):
    secret = "Smtp-Password-Never-Logged-7"
    configured = make_settings(smtp_host="127.0.0.1", smtp_port=SMTP_PORT, smtp_security="none",
                               smtp_from="vms@century.test", smtp_username="vms", smtp_password=secret)
    assert secret not in repr(configured) and secret not in str(configured.model_dump())
    await check_in(guard, directory)
    caplog.set_level(logging.DEBUG)
    with FakeSMTP(port=SMTP_PORT):                       # offers no AUTH: the login attempt fails
        await svc.dispatch_due(harness.db, configured)
    n = await only_notification(harness.db)
    assert n["email"]["error"] == "SMTPNotSupportedError"
    assert secret not in caplog.text and secret not in str(n)
    assert HOST_EMAIL not in caplog.text                 # addresses are not logged either


async def test_the_background_sender_emails_right_after_check_in(harness):
    from app.main import create_app
    with FakeSMTP() as smtp:
        s = make_settings(smtp_host="127.0.0.1", smtp_port=smtp.port, smtp_security="none",
                          smtp_from="vms@century.test", email_worker=True)
        app = create_app(s)
        try:
            async with app.router.lifespan_context(app):
                from app.db.migrate import apply_schema
                from tests.conftest import ADMIN_PASSWORD, AuthHarness
                await apply_schema(app.state.database.db)
                h = AuthHarness(app, app.state.database.db)
                await h.create_user("admin", ADMIN_PASSWORD, "ADMIN")
                c = await h.logged_in("admin", ADMIN_PASSWORD)
                await c.post("/api/v1/gates", json={"name": "Main Gate"})
                dep = (await c.post("/api/v1/departments", json={"name": "HR"})).json()
                host = (await c.post("/api/v1/hosts", json={"name": "Sara Ahmed", "email": HOST_EMAIL,
                                                            "department_id": dep["id"]})).json()
                await check_in(c, {"host": host})
                for _ in range(50):
                    if smtp.messages:
                        break
                    await asyncio.sleep(0.1)
                assert len(smtp.messages) == 1                   # woken by the check-in, not the 30 s timer
                await h.close()
        finally:
            MongoClient(TEST_MONGO_URI).drop_database(s.mongo_db)


# ---------------------------------------------------------------------------------------------- in-app API
async def test_the_bell_shows_only_the_signed_in_users_notifications(harness, admin, guard, directory):
    for i in range(3):
        await check_in(guard, directory, visitor=await new_visitor(guard, name=f"Person {chr(65 + i)}",
                                                                    number=f"35201-00000{i:02d}-1", phone=None))
    mine = (await admin.get(LIST)).json()
    assert mine["unread_count"] == 3 and [n["arrival"]["visitor_name"] for n in mine["items"]] == \
        ["Person C", "Person B", "Person A"]
    first = mine["items"][0]
    assert first["title"] == "Visitor arrived" and first["message"] == "Person C has arrived to visit Sara Ahmed."
    assert first["read"] is False and first["email_status"] == "PENDING" and "recipient" not in str(first)
    theirs = (await guard.get(LIST)).json()
    assert theirs == {"items": [], "next_cursor": None, "unread_count": 0}
    spoofed = (await guard.get(LIST, params={"user_id": str(directory["admin_id"]),
                                             "recipient_user_id": str(directory["admin_id"])})).json()
    assert spoofed["items"] == [] and spoofed["unread_count"] == 0


async def test_mark_read_is_idempotent_and_private(harness, admin, guard, directory):
    await check_in(guard, directory)
    n = (await admin.get(LIST)).json()["items"][0]
    assert (await guard.post(f"{LIST}/{n['id']}/read")).status_code == 404        # not theirs
    first = await admin.post(f"{LIST}/{n['id']}/read")
    second = await admin.post(f"{LIST}/{n['id']}/read")
    assert first.json()["read"] is True and second.json()["read_at"] == first.json()["read_at"]
    assert (await admin.get(LIST)).json()["unread_count"] == 0
    assert (await admin.get(LIST, params={"unread_only": "true"})).json()["items"] == []
    for bad in ("nope", "0" * 24):
        assert (await admin.post(f"{LIST}/{bad}/read")).status_code == 404


async def test_mark_all_read(harness, admin, guard, directory):
    for i in range(2):
        await check_in(guard, directory, visitor=await new_visitor(guard, name=f"Person {chr(65 + i)}",
                                                                    number=f"35201-00000{i:02d}-1", phone=None))
    r = await admin.post(f"{LIST}/read-all")
    assert r.json() == {"marked": 2, "unread_count": 0}
    assert (await admin.post(f"{LIST}/read-all")).json()["marked"] == 0
    assert all(n["read"] for n in (await admin.get(LIST)).json()["items"])


async def test_pages_without_repeats(harness, admin, guard, directory, monkeypatch):
    monkeypatch.setattr(svc, "PAGE_SIZE", 2)
    for i in range(5):
        await check_in(guard, directory, visitor=await new_visitor(guard, name=f"Person {chr(65 + i)}",
                                                                    number=f"35201-00000{i:02d}-1", phone=None))
    seen, cursor = [], None
    while True:
        page = (await admin.get(LIST, params={"cursor": cursor} if cursor else {})).json()
        assert page["unread_count"] == 5
        seen += [n["id"] for n in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 == len(set(seen))


async def test_access_rules(harness, admin):
    anonymous = harness.client()
    assert (await anonymous.get(LIST)).status_code == 401
    assert (await anonymous.post(f"{LIST}/read-all")).status_code == 401
    assert (await admin.post_without_csrf(f"{LIST}/read-all")).status_code == 403
    await harness.create_user("newguard", "Guard-Test-Pass-9", "GUARD", must_change_password=True)
    fresh = await harness.logged_in("newguard", "Guard-Test-Pass-9")
    assert (await fresh.get(LIST)).json()["error"]["code"] == "password_change_required"


# ---------------------------------------------------------------------------------------------- linked app account
async def test_admin_links_and_unlinks_an_app_account(harness, admin, directory):
    host = directory["host"]
    assert host["linked_user"] == {"id": str(directory["admin_id"]), "name": "Admin"}
    guard_user_id = str((await harness.create_user("guard2", "Guard-Test-Pass-2", "GUARD"))["_id"])
    r = await admin.patch(f"/api/v1/hosts/{host['id']}", json={"linked_user_id": guard_user_id})
    assert r.status_code == 200 and r.json()["linked_user"] == {"id": guard_user_id, "name": "Guard2"}
    r = await admin.patch(f"/api/v1/hosts/{host['id']}", json={"clear_linked_user": True})
    assert r.json()["linked_user"] is None
    record = await harness.db.audit_logs.find({"action": "HOST_UPDATED"}).sort("timestamp", -1).to_list(length=1)
    assert record[0]["changes"]["linked_user_id"] == {"from": guard_user_id, "to": None}


@pytest.mark.parametrize("body", [{"linked_user_id": "0" * 24}, {"linked_user_id": "not-an-id"},
                                  {"linked_user_id": str(ObjectId()), "clear_linked_user": True},
                                  {"clear_linked_user": False}])
async def test_invalid_links_are_refused(admin, directory, body):
    r = await admin.patch(f"/api/v1/hosts/{directory['host']['id']}", json=body)
    assert r.status_code == 422


async def test_a_disabled_account_cannot_be_linked(harness, admin, directory):
    user = await harness.create_user("oldguard", "Guard-Test-Pass-3", "GUARD")
    await harness.db.users.update_one({"_id": user["_id"]}, {"$set": {"is_active": False}})
    r = await admin.patch(f"/api/v1/hosts/{directory['host']['id']}", json={"linked_user_id": str(user["_id"])})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_linked_user"


async def test_guards_cannot_link_accounts(guard, directory):
    r = await guard.patch(f"/api/v1/hosts/{directory['host']['id']}", json={"clear_linked_user": True})
    assert r.status_code == 403


# ---------------------------------------------------------------------------------------------- settings
@pytest.mark.parametrize("overrides,message", [
    ({"smtp_host": "mail.century.test"}, "CG_SMTP_FROM"),
    ({"smtp_host": "mail.century.test", "smtp_from": "vms@century.test", "smtp_username": "vms"}, "both"),
    ({"smtp_host": "mail.century.test", "smtp_from": "vms@century.test", "smtp_username": "vms",
      "smtp_password": "x-Secret-1", "smtp_security": "none", "environment": "production"}, "unencrypted"),
])
def test_smtp_settings_are_checked(overrides, message):
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match=message):
        make_settings(**overrides)


def test_email_is_off_unless_a_server_is_configured():
    assert Settings(_env_file=None).email_enabled is False
