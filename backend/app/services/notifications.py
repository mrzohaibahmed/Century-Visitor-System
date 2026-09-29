"""
Notifications (Phase 6A): "your visitor has arrived", for the visit's host and the visited department.

Flow
    check-in transaction ── visit + audit + notification (all or nothing)
                                           │
                                           ├── in-app: for the host's "Linked app account" (an existing
                                           │           Admin/Guard user); hosts themselves never log in
                                           └── e-mail: to the host's address, sent AFTER the check-in by
                                                       the background sender (EmailWorker)
    check-in transaction ── department notification (e-mail only): to the visited department's
                            "Notification email", for listed and unlisted hosts alike; skipped when it is
                            the host's own address

- The notification is written in the check-in transaction, so it exists exactly when the visit does:
  never for a check-in that failed, never lost if the API stops right after the check-in.
- One notification per visit and kind: event_key "HOST_VISITOR_ARRIVAL:<visit id>" (and
  "DEPARTMENT_VISITOR_ARRIVAL:<visit id>") is unique in the database.
- The check-in never waits for e-mail. The `notifications` collection is the e-mail queue:
  PENDING -> SENDING (claimed atomically, so several API processes never send the same e-mail)
  -> SENT, or back to PENDING for a retry (after 1, 5, 15 and 60 minutes), or FAILED after
  MAX_ATTEMPTS or a permanent refusal. NONE: no address, or e-mail switched off.
- A send interrupted by a crash (still SENDING when its lease expires) is marked FAILED, not sent
  again: the message may already have gone out, and a duplicate is worse than a gap.
- Retention: notifications are kept like visits; nothing is deleted automatically (to be decided
  with the other retention rules).
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import decode_cursor, encode_cursor
from app.services import email as email_svc
from app.services import email_settings
from app.services.auth import AuthContext

log = logging.getLogger(__name__)

HOST_ARRIVAL = "HOST_VISITOR_ARRIVAL"
DEPARTMENT_ARRIVAL = "DEPARTMENT_VISITOR_ARRIVAL"       # e-mail only, to the department's address
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1            # 5 attempts over about 81 minutes, then FAILED
LEASE = timedelta(minutes=2)                     # longer than one SMTP attempt can take
POLL_SECONDS = 30
PAGE_SIZE = 20
NOT_FOUND = AppError(404, "not_found", "Notification not found.")


def event_key(visit_id: ObjectId) -> str:
    return f"{HOST_ARRIVAL}:{visit_id}"


# ------------------------------------------------------------------------------------------ creation
async def create_host_arrival(db: AsyncDatabase, settings: Settings, visit: dict, host: dict,
                              session: AsyncClientSession) -> dict | None:
    """Called inside the check-in transaction for a visit with a registered host.
    Returns the notification, or None when there is nobody to tell (no linked account, no e-mail)."""
    recipient = None
    if host.get("linked_user_id"):
        user = await db.users.find_one({"_id": host["linked_user_id"], "is_active": True}, {"_id": 1},
                                       session=session)
        recipient = user["_id"] if user else None
    address = host.get("email")
    if recipient is None and not address:
        return None

    now = visit["check_in_at"]
    if address and await email_settings.active(db, settings, session=session):
        email = {"status": "PENDING", "to": address, "attempts": 0, "next_attempt_at": now}
    else:
        email = {"status": "NONE", "to": None, "attempts": 0,
                 "reason": "email_disabled" if address else "no_address"}
    snap = visit["snapshot"]
    doc = {
        "event_key": event_key(visit["_id"]), "type": HOST_ARRIVAL, "recipient_user_id": recipient,
        "visit_id": visit["_id"], "visitor_id": visit["visitor_id"], "host_id": host["_id"],
        "data": {"visitor_name": snap["visitor_name"], "host_name": snap.get("host_name"),
                 "gate_name": snap.get("gate_name"), "department_name": snap.get("department_name"),
                 "reason_code": visit.get("reason_code"), "check_in_at": visit["check_in_at"]},
        "created_at": now, "read_at": None, "email": email,
    }
    doc["_id"] = (await db.notifications.insert_one(doc, session=session)).inserted_id
    return doc


async def create_department_arrival(db: AsyncDatabase, settings: Settings, visit: dict, department: dict,
                                    host: dict | None, session: AsyncClientSession) -> dict | None:
    """Called inside the check-in transaction for every visit, listed host or not. E-mail only, to the
    visited department's notification address. Returns None when there is nothing to send: no address,
    e-mail switched off, or the same address as the host's (who is e-mailed already)."""
    address = department.get("notification_email")
    if not address:
        return None
    if host and (host.get("email") or "").strip().lower() == address.strip().lower():
        return None
    if not await email_settings.active(db, settings, session=session):
        return None

    now = visit["check_in_at"]
    snap = visit["snapshot"]
    doc = {
        "event_key": f"{DEPARTMENT_ARRIVAL}:{visit['_id']}", "type": DEPARTMENT_ARRIVAL, "recipient_user_id": None,
        "visit_id": visit["_id"], "visitor_id": visit["visitor_id"], "host_id": visit.get("host_id"),
        "data": {"visitor_name": snap["visitor_name"], "host_name": snap.get("host_name"),
                 "gate_name": snap.get("gate_name"), "department_name": snap.get("department_name"),
                 "reason_code": visit.get("reason_code"), "check_in_at": visit["check_in_at"]},
        "created_at": now, "read_at": None,
        "email": {"status": "PENDING", "to": address, "attempts": 0, "next_attempt_at": now},
    }
    doc["_id"] = (await db.notifications.insert_one(doc, session=session)).inserted_id
    return doc


# ------------------------------------------------------------------------------------------ in-app
def _own(ctx: AuthContext) -> dict:
    # The recipient always comes from the server-side session, never from the request.
    return {"recipient_user_id": ctx.user["_id"]}


async def list_for_user(db: AsyncDatabase, ctx: AuthContext, *, unread_only: bool,
                        cursor: str | None) -> tuple[list[dict], str | None, int]:
    query: dict = _own(ctx) | ({"read_at": None} if unread_only else {})
    if cursor:
        last_at, last_id = decode_cursor(cursor)
        query = {"$and": [query, {"$or": [{"created_at": {"$lt": last_at}},
                                          {"created_at": last_at, "_id": {"$lt": last_id}}]}]}
    docs = await db.notifications.find(query).sort([("created_at", -1), ("_id", -1)]).limit(PAGE_SIZE + 1) \
        .to_list(length=PAGE_SIZE + 1)
    next_cursor = None
    if len(docs) > PAGE_SIZE:
        docs = docs[:PAGE_SIZE]
        next_cursor = encode_cursor(docs[-1]["created_at"], docs[-1]["_id"])
    unread = await db.notifications.count_documents(_own(ctx) | {"read_at": None})
    return docs, next_cursor, unread


async def mark_read(db: AsyncDatabase, ctx: AuthContext, notification_id: str) -> dict:
    """Idempotent. Someone else's notification is simply "not found"."""
    if not ObjectId.is_valid(notification_id):
        raise NOT_FOUND
    oid = ObjectId(notification_id)
    await db.notifications.update_one(_own(ctx) | {"_id": oid, "read_at": None},
                                      {"$set": {"read_at": datetime.now(UTC)}})
    doc = await db.notifications.find_one(_own(ctx) | {"_id": oid})
    if doc is None:
        raise NOT_FOUND
    return doc


async def mark_all_read(db: AsyncDatabase, ctx: AuthContext) -> int:
    result = await db.notifications.update_many(_own(ctx) | {"read_at": None},
                                                {"$set": {"read_at": datetime.now(UTC)}})
    return result.modified_count


# ------------------------------------------------------------------------------------------ e-mail
async def _finish(db: AsyncDatabase, doc: dict, fields: dict) -> None:
    # Only the attempt that holds the claim may record its result.
    await db.notifications.update_one(
        {"_id": doc["_id"], "email.status": "SENDING", "email.attempts": doc["email"]["attempts"]},
        {"$set": {f"email.{k}": v for k, v in fields.items()} | {"email.lease_until": None}})


async def dispatch_due(db: AsyncDatabase, settings: Settings, *, send=email_svc.send, limit: int = 20) -> int:
    """Sends the e-mails that are due, one at a time, with the SMTP settings in use now (saved by an
    administrator, else the server environment). Returns how many were attempted."""
    attempted = 0
    config: email_svc.SmtpConfig | None = None
    unusable: str | None = None
    loaded = False
    while attempted < limit:
        now = datetime.now(UTC)
        await db.notifications.update_many(
            {"email.status": "SENDING", "email.lease_until": {"$lt": now}},
            {"$set": {"email.status": "FAILED", "email.error": "interrupted", "email.lease_until": None,
                      "email.next_attempt_at": None}})
        doc = await db.notifications.find_one_and_update(
            {"email.status": "PENDING", "email.next_attempt_at": {"$lte": now}},
            {"$set": {"email.status": "SENDING", "email.lease_until": now + LEASE, "email.last_attempt_at": now},
             "$inc": {"email.attempts": 1}},
            sort=[("email.next_attempt_at", 1)], return_document=ReturnDocument.AFTER)
        if doc is None:
            return attempted
        attempted += 1
        attempt = doc["email"]["attempts"]
        if not loaded:                                # once per pass, only when something is due
            loaded = True
            try:
                config = await email_settings.effective(db, settings)
            except email_settings.SmtpUnusable as e:
                unusable = e.reason
        try:
            if unusable:                              # e.g. the server key changed: may be fixed; retried
                raise email_svc.EmailError(unusable.lower(), permanent=False, reason=unusable)
            if config is None:                        # switched off since the e-mail was queued
                raise email_svc.EmailError("email_disabled", permanent=True, reason="EMAIL_NOT_CONFIGURED")
            build = (email_svc.department_arrival_message if doc["type"] == DEPARTMENT_ARRIVAL
                     else email_svc.host_arrival_message)
            message = build(settings, config, doc["email"]["to"], doc["data"])
            await asyncio.wait_for(asyncio.to_thread(send, config, message),
                                   timeout=config.timeout_seconds + 10)
        except Exception as error:                   # noqa: BLE001 - one bad message never stops the queue
            code = error.code if isinstance(error, email_svc.EmailError) else type(error).__name__
            permanent = isinstance(error, email_svc.EmailError) and error.permanent
            if permanent or attempt >= MAX_ATTEMPTS:
                await _finish(db, doc, {"status": "FAILED", "error": code, "next_attempt_at": None})
                log.warning("Notification e-mail FAILED (notification %s, attempt %d, %s)", doc["_id"], attempt, code)
            else:
                retry_at = datetime.now(UTC) + RETRY_DELAYS[attempt - 1]
                await _finish(db, doc, {"status": "PENDING", "error": code, "next_attempt_at": retry_at})
                log.info("Notification e-mail will be retried (notification %s, attempt %d, %s)",
                         doc["_id"], attempt, code)
        else:
            await _finish(db, doc, {"status": "SENT", "sent_at": datetime.now(UTC), "error": None,
                                    "next_attempt_at": None})
            log.info("Notification e-mail sent (notification %s, attempt %d)", doc["_id"], attempt)
    return attempted


class EmailWorker:
    """The background sender inside the API process: runs every POLL_SECONDS, and at once after a
    check-in (wake()). No queue server needed; the database holds the queue."""

    def __init__(self, db: AsyncDatabase, settings: Settings):
        self._db = db
        self._settings = settings
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        # The SMTP settings are read at every pass (they can be changed by an administrator).
        log.info("E-mail sender started")
        while True:
            try:
                await dispatch_due(self._db, self._settings)
            except asyncio.CancelledError:
                raise
            except Exception:                    # noqa: BLE001 - e.g. database briefly unreachable
                log.exception("E-mail sender pass failed; retrying in %d seconds", POLL_SECONDS)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
            except TimeoutError:
                pass
            self._wake.clear()
