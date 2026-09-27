"""
Audit trail writer (append-only).

Records WHO did WHAT to WHICH record, WHEN, from WHERE, and with what result.
There is deliberately no update or delete function: audit entries are only ever
inserted. Never pass passwords, tokens or other secrets in `changes`/`metadata`.
"""
from datetime import UTC, datetime
from enum import StrEnum

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.request_context import current_request_id


class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    ACCESS_DENIED = "ACCESS_DENIED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - audit action name
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - audit action name
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    ROLE_CHANGED = "ROLE_CHANGED"
    USER_DISABLED = "USER_DISABLED"
    USER_ENABLED = "USER_ENABLED"
    USER_UNLOCKED = "USER_UNLOCKED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    GATE_SELECTED = "GATE_SELECTED"
    # Directory
    GATE_CREATED = "GATE_CREATED"
    GATE_UPDATED = "GATE_UPDATED"
    DEPARTMENT_CREATED = "DEPARTMENT_CREATED"
    DEPARTMENT_UPDATED = "DEPARTMENT_UPDATED"
    HOST_CREATED = "HOST_CREATED"
    HOST_UPDATED = "HOST_UPDATED"
    # Visitors & visits
    VISITOR_CREATED = "VISITOR_CREATED"
    VISITOR_UPDATED = "VISITOR_UPDATED"
    VISITOR_VIEWED = "VISITOR_VIEWED"          # personal data opened
    VISITOR_LOOKUP = "VISITOR_LOOKUP"          # searched by identity number
    VISIT_CHECKED_IN = "VISIT_CHECKED_IN"
    VISIT_CHECKED_OUT = "VISIT_CHECKED_OUT"
    WATCHLIST_MATCH = "WATCHLIST_MATCH"


def actor_from_user(user: dict | None) -> dict:
    if not user:
        return {"user_id": None, "username": None, "role": None}
    return {"user_id": user["_id"], "username": user.get("username"), "role": user.get("role")}


async def record(
    db: AsyncDatabase,
    action: AuditAction,
    *,
    result: str = "SUCCESS",
    actor: dict | None = None,
    resource_type: str | None = None,
    resource_id: ObjectId | str | None = None,
    ip: str | None = None,
    changes: dict | None = None,
    metadata: dict | None = None,
    session: AsyncClientSession | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(UTC),
        "action": str(action),
        "result": result,
        "actor": actor or actor_from_user(None),
        "resource": {"type": resource_type, "id": resource_id},
        "ip": ip,
        "request_id": current_request_id(),
    }
    if changes:
        entry["changes"] = changes
    if metadata:
        entry["metadata"] = metadata
    await db.audit_logs.insert_one(entry, session=session)
