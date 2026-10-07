"""
Visitor passes: the QR code printed on the badge.

The QR holds only "CGP1:" + a 256-bit random token (64 hex digits). It says
nothing about the visitor (no name, ID number, phone) and it is not derived
from the visit number, so it cannot be guessed or constructed. The database
stores only the token's SHA-256, so a database copy cannot be used to print
valid badges. There is nothing in the token to edit: changing any character
gives a token that matches no visit. (A signature would add nothing; the
server never trusts what the QR says, it only looks the token up.)

Lifecycle (on the visit's `pass` sub-document):

    issued at check-in ── ACTIVE ──┬─ visit checked out ─> no longer valid (scan shows "already checked out")
                                   ├─ reissued (lost / damaged badge) ─> old token REPLACED
                                   ├─ revoked ─> REVOKED
                                   └─ past gate closing (pass_day_end) ─> EXPIRED

A pass only ever identifies its own visit. It is used at check-out; check-in
never accepts one, so a pass cannot be replayed to enter again. Scanning never
changes anything by itself: the guard confirms the check-out.
"""
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_token
from app.core.timeutil import pass_expires_at
from app.db.transactions import run_in_transaction
from app.services import audit
from app.services import visits as visits_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta

QR_PREFIX = "CGP1:"
# Upper-case hex so the QR fits the compact alphanumeric mode, and USB scanners
# that type into a text box cannot get the case wrong.
_PAYLOAD = re.compile(r"^CGP1:([0-9A-F]{64})$")


@dataclass
class IssuedPass:
    visit: dict
    qr_text: str
    expires_at: datetime


def _token_hash(token: str) -> str:
    return hash_token(token.upper())


def parse_qr(text: str) -> str | None:
    """The token inside a scanned QR text, or None if it is not one of our passes."""
    match = _PAYLOAD.match((text or "").strip().upper())
    return match.group(1) if match else None


def _is_expired(visit_pass: dict, now: datetime) -> bool:
    return visit_pass["expires_at"] <= now


async def issue(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                visit_id: str) -> IssuedPass:
    """Issues the visit's pass, or a replacement: the previous QR stops working immediately."""
    oid = visits_svc.object_id(visit_id)
    token = secrets.token_hex(32).upper()
    now = datetime.now(UTC)
    expires_at = pass_expires_at(settings.timezone, hour=settings.pass_day_end_hour,
                                 minute=settings.pass_day_end_minute, now=now)
    result: dict = {}

    async def work(s: AsyncClientSession):
        visit = await db.visits.find_one({"_id": oid}, session=s)
        if visit is None:
            raise visits_svc.NOT_FOUND
        if visit["status"] != "CHECKED_IN":
            raise AppError(409, "not_checked_in", "A pass can only be issued while the visitor is inside.")
        old = visit.get("pass") or {}
        revoked = [*old.get("revoked_token_hashes", []), *([old["token_hash"]] if old.get("token_hash") else [])]
        new_pass = {"token_hash": _token_hash(token), "issued_at": now, "expires_at": expires_at,
                    "issued_by": ctx.user["_id"], "revoked_at": None, "revoked_by": None,
                    "revoked_token_hashes": revoked}
        await db.visits.update_one({"_id": oid, "status": "CHECKED_IN"},
                                   {"$set": {"pass": new_pass, "updated_at": now}}, session=s)
        await audit.record(db, AuditAction.PASS_ISSUED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="visit", resource_id=oid,
                           metadata={"visit_number": visit["visit_number"], "replaces_previous": bool(old),
                                     "expires_at": expires_at}, session=s)
        result["visit"] = visit

    await run_in_transaction(db, work)
    return IssuedPass(visit=result["visit"], qr_text=QR_PREFIX + token, expires_at=expires_at)


async def revoke(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visit_id: str) -> dict:
    """The current pass stops working (e.g. badge lost). Idempotent."""
    oid = visits_svc.object_id(visit_id)
    now = datetime.now(UTC)

    async def work(s: AsyncClientSession):
        visit = await db.visits.find_one({"_id": oid}, session=s)
        if visit is None:
            raise visits_svc.NOT_FOUND
        current = visit.get("pass")
        if not current or current.get("revoked_at"):
            return visit
        await db.visits.update_one(
            {"_id": oid}, {"$set": {"pass.revoked_at": now, "pass.revoked_by": ctx.user["_id"], "updated_at": now}},
            session=s)
        await audit.record(db, AuditAction.PASS_REVOKED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="visit", resource_id=oid,
                           metadata={"visit_number": visit["visit_number"]}, session=s)
        return visit

    return await run_in_transaction(db, work)


async def _reject(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, reason: str,
                  visit: dict | None, error: AppError) -> AppError:
    await audit.record(db, AuditAction.PASS_REJECTED, result="FAILURE", actor=actor_from_user(ctx.user), ip=meta.ip,
                       resource_type="visit" if visit else None, resource_id=visit["_id"] if visit else None,
                       metadata={"reason": reason, **({"visit_number": visit["visit_number"]} if visit else {})})
    return error


async def resolve(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, qr_text: str) -> dict:
    """The visit a scanned pass belongs to, if the pass is valid. Changes nothing.

    A pass whose visit is already checked out resolves (so the guard sees who it
    was), and the caller reports it as already checked out.
    """
    token = parse_qr(qr_text)
    if token is None:
        raise await _reject(db, ctx, meta, "malformed", None, AppError(
            422, "invalid_pass", "This is not a Century Gate visitor pass."))
    digest = _token_hash(token)
    visit = await db.visits.find_one({"pass.token_hash": digest})
    if visit is None:
        replaced = await db.visits.find_one({"pass.revoked_token_hashes": digest}, {"visit_number": 1})
        if replaced is not None:
            raise await _reject(db, ctx, meta, "replaced", replaced, AppError(
                409, "pass_replaced",
                "This badge has been replaced by a newer one and is no longer valid. "
                "Keep it and ask the visitor for the new badge."))
        raise await _reject(db, ctx, meta, "unknown", None, AppError(
            404, "invalid_pass", "This pass is not valid. Verify the visitor and use the visit number instead."))

    visit_pass = visit.pop("pass")
    if visit["status"] != "CHECKED_IN":
        return visit
    if visit_pass.get("revoked_at"):
        raise await _reject(db, ctx, meta, "revoked", visit, AppError(
            409, "pass_revoked", f"This badge was cancelled (visit {visit['visit_number']}). "
                                 "Verify the visitor's identity and check out by visit number."))
    if _is_expired(visit_pass, datetime.now(UTC)):
        raise await _reject(db, ctx, meta, "expired", visit, AppError(
            409, "pass_expired", f"This badge has expired (visit {visit['visit_number']}). "
                                 "Verify the visitor's identity and check out by visit number."))
    return visit


async def check_out(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, qr_text: str) -> tuple[dict, bool]:
    """Check-out with a scanned pass, after the guard confirmed it. Idempotent like every check-out."""
    visit = await resolve(db, ctx, meta, qr_text)
    if visit["status"] != "CHECKED_IN":
        return await db.visits.find_one({"_id": visit["_id"]}, visits_svc.LIST_PROJECTION), True
    return await visits_svc.check_out(db, ctx, meta, visit["_id"], "QR")


async def record_badge_print(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visit_id: str) -> None:
    visit = await visits_svc.get_visit(db, visit_id)
    await audit.record(db, AuditAction.BADGE_PRINT_REQUESTED, actor=actor_from_user(ctx.user), ip=meta.ip,
                       resource_type="visit", resource_id=visit["_id"],
                       metadata={"visit_number": visit["visit_number"]})
