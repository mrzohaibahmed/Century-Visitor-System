"""
SQL Server access for notifications: the in-app inbox and the e-mail queue (queries only).
Notifications come back as documents ("email" as a
sub-dictionary from the email_* columns, "data" from its JSON column).

The e-mail queue is claimed with UPDLOCK + READPAST: several API processes never claim the same e-mail,
and none waits for another's claim (MongoDB's find_one_and_update gave the same guarantee).
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, bindparam, func, or_, select, text, update
from sqlalchemy import insert as sql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.json_values import from_json, to_json
from app.repositories.rows import checked, new_row
from app.repositories.types import UtcDateTime

notifications = tables.notifications
EMAIL_FIELDS = ("status", "to", "attempts", "next_attempt_at", "last_attempt_at", "lease_until", "sent_at",
                "reason", "error")
NEWEST_FIRST = (notifications.c.created_at.desc(), notifications.c.id.desc())


def notification_doc(row) -> dict | None:
    if row is None:
        return None
    m = dict(row._mapping)
    doc = {key: value for key, value in m.items() if key not in ("id", "data") and not key.startswith("email_")}
    doc["_id"] = m["id"]
    doc["data"] = from_json(m["data"])
    doc["email"] = {field: m[f"email_{field}"] for field in EMAIL_FIELDS}
    return doc


def notification_columns(doc: dict) -> dict:
    """A notification document as the columns of its row (without the id)."""
    columns = {key: value for key, value in doc.items() if key not in ("_id", "data", "email")}
    columns["data"] = to_json(doc.get("data") or {})
    email = doc.get("email") or {}
    unknown = set(email) - set(EMAIL_FIELDS)
    if unknown:
        raise ValueError(f"notification e-mail has no field(s) {sorted(unknown)}")
    columns |= {f"email_{field}": email.get(field) for field in EMAIL_FIELDS}
    columns["email_attempts"] = email.get("attempts") or 0
    return columns


async def insert(db: SqlDb, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey if a notification with this event_key exists (one per visit and kind).
    Sets doc["_id"]."""
    row = new_row(notifications, doc, notification_columns(doc))
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(notifications), row)
    return doc["_id"]


# --- in-app inbox (always restricted to one recipient) ---

async def list_for_recipient(db: SqlDb, user_id: UUID, *, unread_only: bool,
                             after: tuple[datetime, UUID] | None, limit: int) -> list[dict]:
    """Newest first. `after`: the (created_at, ID) of the last row already shown."""
    query = select(notifications).where(notifications.c.recipient_user_id == user_id)
    if unread_only:
        query = query.where(notifications.c.read_at.is_(None))
    if after:
        last_at, last_id = after
        query = query.where(or_(notifications.c.created_at < last_at,
                                and_(notifications.c.created_at == last_at, notifications.c.id < last_id)))
    async with connection(db) as conn:
        return [notification_doc(row) for row in await conn.execute(query.order_by(*NEWEST_FIRST).limit(limit))]


async def count_unread(db: SqlDb, user_id: UUID) -> int:
    query = select(func.count()).select_from(notifications).where(
        notifications.c.recipient_user_id == user_id, notifications.c.read_at.is_(None))
    async with connection(db) as conn:
        return (await conn.execute(query)).scalar_one()


async def find_for_recipient(db: SqlDb, user_id: UUID, notification_id: UUID) -> dict | None:
    query = select(notifications).where(notifications.c.recipient_user_id == user_id,
                                        notifications.c.id == notification_id)
    async with connection(db) as conn:
        return notification_doc((await conn.execute(query)).first())


async def mark_read(db: SqlDb, user_id: UUID, notification_id: UUID, now: datetime) -> None:
    """Sets read_at if still unread (idempotent); someone else's notification is not touched."""
    async with connection(db) as conn:
        await conn.execute(update(notifications).where(
            notifications.c.recipient_user_id == user_id, notifications.c.id == notification_id,
            notifications.c.read_at.is_(None)).values(read_at=now))


async def mark_all_read(db: SqlDb, user_id: UUID, now: datetime) -> int:
    async with connection(db) as conn:
        result = await conn.execute(update(notifications).where(
            notifications.c.recipient_user_id == user_id, notifications.c.read_at.is_(None)).values(read_at=now))
    return result.rowcount


# --- e-mail queue ---

async def fail_expired_claims(db: SqlDb, now: datetime) -> None:
    """E-mails still SENDING after their lease (a crashed send) become FAILED, never sent again."""
    async with connection(db) as conn:
        await conn.execute(update(notifications).where(
            notifications.c.email_status == "SENDING", notifications.c.email_lease_until < now).values(
            email_status="FAILED", email_error="interrupted", email_lease_until=None, email_next_attempt_at=None))


async def claim_next_due(db: SqlDb, now: datetime, lease_until: datetime) -> dict | None:
    """Atomically moves the earliest due PENDING e-mail to SENDING (one attempt more) and returns it;
    several API processes never claim the same one. None when nothing is due."""
    claim = text(
        "WITH next_due AS ("
        "  SELECT TOP (1) * FROM dbo.notifications WITH (UPDLOCK, READPAST, ROWLOCK)"
        "  WHERE email_status = 'PENDING' AND email_next_attempt_at <= :now"
        "  ORDER BY email_next_attempt_at, id) "
        "UPDATE next_due SET email_status = 'SENDING', email_lease_until = :lease, email_last_attempt_at = :now, "
        "email_attempts = email_attempts + 1 OUTPUT inserted.id;"
    ).bindparams(_utc("now", now), _utc("lease", lease_until))
    async with connection(db) as conn:
        claimed = (await conn.execute(claim)).scalar_one_or_none()
        if claimed is None:
            return None
        return notification_doc((await conn.execute(select(notifications).where(notifications.c.id == claimed)))
                                .first())


def _utc(name: str, value: datetime):
    """A time parameter for raw SQL, converted like the UtcDateTime columns (UTC, whole milliseconds)."""
    return bindparam(name, value, type_=UtcDateTime())


async def finish_claim(db: SqlDb, notification_id: UUID, attempt: int, email_fields: dict) -> None:
    """Records the result of an attempt, only while that attempt still holds the claim. `email_fields`
    (status, error, next_attempt_at, sent_at) are set on the e-mail; the lease is cleared."""
    values = checked(notifications, {f"email_{key}": value for key, value in email_fields.items()}
                     | {"email_lease_until": None})
    async with connection(db) as conn:
        await conn.execute(update(notifications).where(
            notifications.c.id == notification_id, notifications.c.email_status == "SENDING",
            notifications.c.email_attempts == attempt).values(**values))
