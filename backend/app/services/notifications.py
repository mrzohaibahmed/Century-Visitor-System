"""
Notifications (Phase 6A): arrival and overstay messages for the visit's host and department.

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

    OverstayWorker (background) ── visits still CHECKED_IN after pass.expires_at
                                   ├── HOST_VISITOR_OVERSTAY (in-app + e-mail, same as arrival)
                                   └── DEPARTMENT_VISITOR_OVERSTAY (e-mail only)

- The arrival notification is written in the check-in transaction, so it exists exactly when the visit
  does: never for a check-in that failed, never lost if the API stops right after the check-in.
- One notification per visit and kind: event_key "HOST_VISITOR_ARRIVAL:<visit id>" (and the department /
  overstay variants) is unique in the database.
- The check-in never waits for e-mail. The notifications table is the e-mail queue:
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

from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import decode_cursor, encode_cursor
from app.db.types import Db, DbSession, RecordId
from app.repositories import directory as directory_repo
from app.repositories import notifications as notifications_repo
from app.repositories import users as users_repo
from app.repositories import visits as visits_repo
from app.repositories.errors import DuplicateKey
from app.repositories.ids import parse_id
from app.services import email as email_svc
from app.services import email_settings
from app.services.auth import AuthContext

log = logging.getLogger(__name__)

HOST_ARRIVAL = "HOST_VISITOR_ARRIVAL"
DEPARTMENT_ARRIVAL = "DEPARTMENT_VISITOR_ARRIVAL"       # e-mail only, to the department's address
HOST_OVERSTAY = "HOST_VISITOR_OVERSTAY"
DEPARTMENT_OVERSTAY = "DEPARTMENT_VISITOR_OVERSTAY"     # e-mail only, to the department's address
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1            # 5 attempts over about 81 minutes, then FAILED
LEASE = timedelta(minutes=2)                     # longer than one SMTP attempt can take
POLL_SECONDS = 30
PAGE_SIZE = 20
OVERSTAY_BATCH = 50
NOT_FOUND = AppError(404, "not_found", "Notification not found.")

_MESSAGE_BUILDERS = {
    HOST_ARRIVAL: email_svc.host_arrival_message,
    DEPARTMENT_ARRIVAL: email_svc.department_arrival_message,
    HOST_OVERSTAY: email_svc.host_overstay_message,
    DEPARTMENT_OVERSTAY: email_svc.department_overstay_message,
}


def event_key(visit_id: RecordId) -> str:
    return f"{HOST_ARRIVAL}:{visit_id}"


# ------------------------------------------------------------------------------------------ creation
async def create_host_arrival(db: Db, settings: Settings, visit: dict, host: dict,
                              session: DbSession) -> dict | None:
    """Called inside the check-in transaction for a visit with a registered host.
    Returns the notification, or None when there is nobody to tell (no linked account, no e-mail)."""
    recipient = None
    if host.get("linked_user_id"):
        recipient = await users_repo.find_active_id(db, host["linked_user_id"], session=session)
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
    doc["_id"] = await notifications_repo.insert(db, doc, session=session)
    return doc


async def create_department_arrival(db: Db, settings: Settings, visit: dict, department: dict,
                                    host: dict | None, session: DbSession) -> dict | None:
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
    doc["_id"] = await notifications_repo.insert(db, doc, session=session)
    return doc


def _overstay_data(visit: dict) -> dict:
    snap = visit.get("snapshot") or {}
    expires = (visit.get("pass") or {}).get("expires_at")
    return {
        "visitor_name": snap.get("visitor_name"), "host_name": snap.get("host_name"),
        "gate_name": snap.get("gate_name"), "department_name": snap.get("department_name"),
        "reason_code": visit.get("reason_code"), "check_in_at": visit.get("check_in_at"),
        "expires_at": expires,
    }


async def create_host_overstay(db: Db, settings: Settings, visit: dict,
                               host: dict) -> dict | None:
    """Queue an overstay notice for a registered host (in-app and/or e-mail). Idempotent via event_key."""
    recipient = None
    if host.get("linked_user_id"):
        recipient = await users_repo.find_active_id(db, host["linked_user_id"])
    address = host.get("email")
    if recipient is None and not address:
        return None

    now = datetime.now(UTC)
    if address and await email_settings.active(db, settings):
        email = {"status": "PENDING", "to": address, "attempts": 0, "next_attempt_at": now}
    else:
        email = {"status": "NONE", "to": None, "attempts": 0,
                 "reason": "email_disabled" if address else "no_address"}
    doc = {
        "event_key": f"{HOST_OVERSTAY}:{visit['_id']}", "type": HOST_OVERSTAY, "recipient_user_id": recipient,
        "visit_id": visit["_id"], "visitor_id": visit["visitor_id"], "host_id": host["_id"],
        "data": _overstay_data(visit), "created_at": now, "read_at": None, "email": email,
    }
    try:
        doc["_id"] = await notifications_repo.insert(db, doc)
    except DuplicateKey:
        return None
    return doc


async def create_department_overstay(db: Db, settings: Settings, visit: dict,
                                     department: dict, host: dict | None) -> dict | None:
    """E-mail the department when a visitor is still inside after badge expiry. Idempotent via event_key."""
    address = department.get("notification_email")
    if not address:
        return None
    if host and (host.get("email") or "").strip().lower() == address.strip().lower():
        return None
    if not await email_settings.active(db, settings):
        return None

    now = datetime.now(UTC)
    doc = {
        "event_key": f"{DEPARTMENT_OVERSTAY}:{visit['_id']}", "type": DEPARTMENT_OVERSTAY,
        "recipient_user_id": None, "visit_id": visit["_id"], "visitor_id": visit["visitor_id"],
        "host_id": visit.get("host_id"), "data": _overstay_data(visit), "created_at": now, "read_at": None,
        "email": {"status": "PENDING", "to": address, "attempts": 0, "next_attempt_at": now},
    }
    try:
        doc["_id"] = await notifications_repo.insert(db, doc)
    except DuplicateKey:
        return None
    return doc


async def queue_overstays(db: Db, settings: Settings, *, limit: int = OVERSTAY_BATCH) -> int:
    """Find visitors still inside after their badge expired and queue host + department overstay notices.
    Returns how many notification documents were inserted (0 when nothing new)."""
    now = datetime.now(UTC)
    visits = await visits_repo.list_overstayed(db, now, limit)
    created = 0
    for visit in visits:
        host = await directory_repo.find_by_id(db, "hosts", visit["host_id"]) if visit.get("host_id") else None
        department = (await directory_repo.find_by_id(db, "departments", visit["department_id"])
                      if visit.get("department_id") else None)
        if host is not None:
            if await create_host_overstay(db, settings, visit, host):
                created += 1
        if department is not None:
            if await create_department_overstay(db, settings, visit, department, host):
                created += 1
    return created


# ------------------------------------------------------------------------------------------ in-app
def _own(ctx: AuthContext) -> RecordId:
    # The recipient always comes from the server-side session, never from the request.
    return ctx.user["_id"]


async def list_for_user(db: Db, ctx: AuthContext, *, unread_only: bool,
                        cursor: str | None) -> tuple[list[dict], str | None, int]:
    docs = await notifications_repo.list_for_recipient(
        db, _own(ctx), unread_only=unread_only, after=decode_cursor(cursor) if cursor else None,
        limit=PAGE_SIZE + 1)
    next_cursor = None
    if len(docs) > PAGE_SIZE:
        docs = docs[:PAGE_SIZE]
        next_cursor = encode_cursor(docs[-1]["created_at"], docs[-1]["_id"])
    unread = await notifications_repo.count_unread(db, _own(ctx))
    return docs, next_cursor, unread


async def mark_read(db: Db, ctx: AuthContext, notification_id: str) -> dict:
    """Idempotent. Someone else's notification is simply "not found"."""
    record_id = parse_id(notification_id)
    if record_id is None:
        raise NOT_FOUND
    await notifications_repo.mark_read(db, _own(ctx), record_id, datetime.now(UTC))
    doc = await notifications_repo.find_for_recipient(db, _own(ctx), record_id)
    if doc is None:
        raise NOT_FOUND
    return doc


async def mark_all_read(db: Db, ctx: AuthContext) -> int:
    return await notifications_repo.mark_all_read(db, _own(ctx), datetime.now(UTC))


# ------------------------------------------------------------------------------------------ e-mail
async def _finish(db: Db, doc: dict, fields: dict) -> None:
    # Only the attempt that holds the claim may record its result.
    await notifications_repo.finish_claim(db, doc["_id"], doc["email"]["attempts"], fields)


async def dispatch_due(db: Db, settings: Settings, *, send=email_svc.send, limit: int = 20) -> int:
    """Sends the e-mails that are due, one at a time, with the SMTP settings in use now (saved by an
    administrator, else the server environment). Returns how many were attempted."""
    attempted = 0
    config: email_svc.SmtpConfig | None = None
    unusable: str | None = None
    loaded = False
    while attempted < limit:
        now = datetime.now(UTC)
        await notifications_repo.fail_expired_claims(db, now)
        doc = await notifications_repo.claim_next_due(db, now, now + LEASE)
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
            build = _MESSAGE_BUILDERS.get(doc["type"], email_svc.host_arrival_message)
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

    def __init__(self, db: Db, settings: Settings):
        self._db = db
        self._settings = settings
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        """Ends the loop after the current pass (a pass is never cut off in the middle of a database call)."""
        self._stopping.set()
        self._wake.set()

    async def run(self) -> None:
        # The SMTP settings are read at every pass (they can be changed by an administrator).
        log.info("E-mail sender started")
        while not self._stopping.is_set():
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
        log.info("E-mail sender stopped")


class OverstayWorker:
    """Looks for visitors still inside after badge expiry and queues overstay e-mails (host + department)."""

    def __init__(self, db: Db, settings: Settings, *, on_queued=None):
        self._db = db
        self._settings = settings
        self._on_queued = on_queued          # typically EmailWorker.wake
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        """Ends the loop after the current pass (a pass is never cut off in the middle of a database call)."""
        self._stopping.set()

    async def run(self) -> None:
        log.info("Overstay checker started (every %d s)", self._settings.overstay_poll_seconds)
        while not self._stopping.is_set():
            try:
                created = await queue_overstays(self._db, self._settings)
                if created and self._on_queued is not None:
                    self._on_queued()
            except asyncio.CancelledError:
                raise
            except Exception:                    # noqa: BLE001 - e.g. database briefly unreachable
                log.exception("Overstay check failed; retrying in %d seconds",
                              self._settings.overstay_poll_seconds)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._settings.overstay_poll_seconds)
            except TimeoutError:
                pass
        log.info("Overstay checker stopped")
