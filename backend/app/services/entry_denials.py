"""
Refused entries (entry_denials), for reporting. One document per refused attempt, keyed by the
WATCHLIST_MATCH audit entry that recorded it (source_audit_id, unique).

The security decision never depends on this collection:
- the watchlist check and its audit entries run first, exactly as before;
- the denial document is written afterwards, best effort, with a time limit: if it fails or times out,
  the failure is logged (only the audit id and the error type, never personal data) and the refusal
  goes ahead unchanged; `python -m app.cli backfill-entry-denials` then recreates the missing document
  from its audit entry;
- no transaction: a failed reporting write must never roll back the security audit trail.

Sources:
- "check_in": POST /visits refused the entry (services/visits.check_in);
- "lookup": the check-in lookup (GET /visitors/lookup) answered BLOCKED;
- "audit_backfill": rebuilt from an older WATCHLIST_MATCH audit entry. Only what that entry recorded
  is kept (ids, masked identifier); names and purpose stay null, nothing is guessed.

Stored: ids, names as they were at the time, the masked identifier (mask_sensitive), the validated
purpose code. Never: a full ID number, phone, photo, pass, belongings, reason note or request payload.
"""
import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.identity import mask_identity, mask_sensitive
from app.services import audit
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta

log = logging.getLogger(__name__)

RECORD_TIMEOUT_SECONDS = 2.0
WATCHLIST = "WATCHLIST"


def masked_identifier(identity: dict | None) -> str | None:
    """"CNIC:***********67-1": the stricter report masking, never the full number."""
    if not identity or not identity.get("number"):
        return None
    return f"{identity.get('type')}:{mask_sensitive(identity['number'])}"


def _operator_name(user: dict) -> str:
    return user.get("display_name") or user["username"]


async def _record(db: AsyncDatabase, source: str, match: dict, build) -> None:
    """Best effort: builds and inserts the denial document within RECORD_TIMEOUT_SECONDS. Never raises
    (except cancellation), so the caller's refusal is never changed by it."""
    async def work():
        doc = await build()
        doc |= {"at": match["timestamp"], "reason": WATCHLIST, "source": source, "source_audit_id": match["_id"]}
        await db.entry_denials.insert_one(doc)

    try:
        await asyncio.wait_for(work(), timeout=RECORD_TIMEOUT_SECONDS)
    except DuplicateKeyError:
        pass                                            # already recorded (e.g. by a backfill run)
    except (PyMongoError, TimeoutError) as e:
        # Database errors can quote the document: log the type only.
        log.error("Entry denial not recorded (%s, audit %s): %s. Run backfill-entry-denials to repair.",
                  source, match["_id"], type(e).__name__)
    except Exception:                                   # noqa: BLE001 - a bug here must not change the refusal
        log.exception("Entry denial not recorded (%s, audit %s): unexpected error. Run backfill-entry-denials "
                      "to repair.", source, match["_id"])


async def record_check_in_denial(db: AsyncDatabase, *, match: dict, visitor: dict, ban: dict, gate: dict,
                                 user: dict, reason_code: str | None) -> None:
    """After POST /visits refused the entry. `match`: the WATCHLIST_MATCH audit entry (its _id and
    timestamp are reused); gate and operator come from the session."""
    async def build() -> dict:
        return {"visitor_id": visitor["_id"], "visitor_name": visitor.get("full_name"),
                "identifier_masked": masked_identifier(visitor.get("identity")), "watchlist_id": ban["_id"],
                "gate_id": gate["_id"], "gate_name": gate.get("name"), "operator_id": user["_id"],
                "operator_username": user.get("username"), "operator_name": _operator_name(user),
                "reason_code": str(reason_code) if reason_code else None}

    await _record(db, "check_in", match, build)


async def _gate_without_selecting(db: AsyncDatabase, session: dict) -> dict | None:
    """The session's gate if it is active, or the only active gate; None otherwise. Read-only: unlike
    auth.session_gate() it never stores a gate on the session (a lookup does not need one)."""
    if session.get("gate_id"):
        gate = await db.gates.find_one({"_id": session["gate_id"], "is_active": True}, {"name": 1})
        if gate:
            return gate
    active = await db.gates.find({"is_active": True}, {"name": 1}).limit(2).to_list(length=2)
    return active[0] if len(active) == 1 else None


async def record_blocked_lookup(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visitor: dict,
                                ban: dict) -> None:
    """The check-in lookup found a visitor on the watchlist: the attempt is refused at the gate. Audited
    like a refused check-in (WATCHLIST_MATCH, marked context "lookup"), then recorded as a denial. The
    lookup's answer (screening BLOCKED) is unchanged."""
    gate = await _gate_without_selecting(db, ctx.session)
    ident = visitor.get("identity") or {}
    match = await audit.record(db, AuditAction.WATCHLIST_MATCH, actor=actor_from_user(ctx.user), ip=meta.ip,
                               resource_type="visitor", resource_id=visitor["_id"],
                               metadata={"watchlist_id": ban["_id"], "gate_id": gate["_id"] if gate else None,
                                         "identifier": f"{ident.get('type')}:{mask_identity(ident.get('number', ''))}",
                                         "context": "lookup"})

    async def build() -> dict:
        return {"visitor_id": visitor["_id"], "visitor_name": visitor.get("full_name"),
                "identifier_masked": masked_identifier(ident), "watchlist_id": ban["_id"],
                "gate_id": gate["_id"] if gate else None, "gate_name": gate.get("name") if gate else None,
                "operator_id": ctx.user["_id"], "operator_username": ctx.user.get("username"),
                "operator_name": _operator_name(ctx.user), "reason_code": None}

    await _record(db, "lookup", match, build)


# ------------------------------------------------------------------------------------------ backfill
@dataclass
class BackfillReport:
    scanned: int = 0
    created: int = 0
    already_present: int = 0
    incomplete: int = 0          # of those created: the audit entry lacked some ids (stored as null)
    skipped: int = 0             # unusable audit entry (no timestamp): nothing created
    failed: int = 0              # database error for this entry (logged); the next run retries it

    def as_dict(self) -> dict:
        return asdict(self)


def _oid(value) -> ObjectId | None:
    return value if isinstance(value, ObjectId) else None


def _remask(identifier) -> str | None:
    """An audit identifier ("CNIC:***********67-1") with its number masked again by mask_sensitive():
    the audit's mask_identity() shows short numbers (4 characters or fewer) in full."""
    if not isinstance(identifier, str) or not identifier:
        return None
    kind, sep, number = identifier.partition(":")
    return f"{kind}:{mask_sensitive(number)}" if sep else mask_sensitive(identifier)


def from_audit(entry: dict) -> tuple[dict | None, bool]:
    """(the denial fields recorded by one WATCHLIST_MATCH audit entry, complete?). None if unusable.
    Only what the entry itself recorded: names, purpose and anything else stay null."""
    if not isinstance(entry.get("timestamp"), datetime):
        return None, False
    meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    resource = entry.get("resource") if isinstance(entry.get("resource"), dict) else {}
    actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else {}
    doc = {
        "at": entry["timestamp"], "reason": WATCHLIST, "source": "audit_backfill",
        "visitor_id": _oid(resource.get("id")), "visitor_name": None,
        "identifier_masked": _remask(meta.get("identifier")), "watchlist_id": _oid(meta.get("watchlist_id")),
        "gate_id": _oid(meta.get("gate_id")), "gate_name": None,
        "operator_id": _oid(actor.get("user_id")),
        "operator_username": actor.get("username") if isinstance(actor.get("username"), str) else None,
        "operator_name": None, "reason_code": None,
    }
    required = ("visitor_id", "identifier_masked", "watchlist_id", "operator_id")
    # A lookup refusal may legitimately have no gate; a check-in refusal always had one.
    gate_expected = meta.get("context") != "lookup"
    complete = all(doc[k] is not None for k in required) and (doc["gate_id"] is not None or not gate_expected)
    return doc, complete


async def backfill_from_audit(db: AsyncDatabase) -> BackfillReport:
    """Creates the missing denial documents from WATCHLIST_MATCH audit entries. Idempotent and safe to run
    concurrently: the unique source_audit_id means at most one document per audit entry, $setOnInsert
    never changes an existing document, and a document written at runtime is simply found present."""
    report = BackfillReport()
    async for entry in db.audit_logs.find({"action": str(AuditAction.WATCHLIST_MATCH)}).sort("_id", 1):
        report.scanned += 1
        doc, complete = from_audit(entry)
        if doc is None:
            report.skipped += 1
            continue
        try:
            result = await db.entry_denials.update_one(
                {"source_audit_id": entry["_id"]}, {"$setOnInsert": doc}, upsert=True)
        except DuplicateKeyError:                    # another run inserted it at the same moment
            report.already_present += 1
            continue
        except PyMongoError as e:
            report.failed += 1
            log.error("Backfill: audit %s not copied: %s", entry["_id"], type(e).__name__)
            continue
        if result.upserted_id is not None:
            report.created += 1
            report.incomplete += 0 if complete else 1
        else:
            report.already_present += 1
    return report
