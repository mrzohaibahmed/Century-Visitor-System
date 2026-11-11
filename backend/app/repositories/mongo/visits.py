"""MongoDB access for visits and their passes (queries only; rules live in services)."""
from datetime import date, datetime

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.mongo.errors import duplicates_as_domain_error
from app.repositories.visit_filter import VisitFilter

# Lists retain only the badge expiry needed by the UI. Authentication and
# revocation details remain excluded from every visit response.
LIST_PROJECTION = {
    "pass.token_hash": 0,
    "pass.issued_at": 0,
    "pass.issued_by": 0,
    "pass.revoked_at": 0,
    "pass.revoked_by": 0,
    "pass.revoked_token_hashes": 0,
    "pass.qr_sealed": 0,
}
NEWEST_FIRST = [("check_in_at", -1), ("_id", -1)]


def filter_query(f: VisitFilter, *, visit_number: str | None = None,
                 visitor_ids: list[ObjectId] | None = None) -> dict:
    """The database filter for `f`, with the free-text search `f.q` already resolved by the caller into
    a `visit_number` or a list of `visitor_ids` (which replaces `f.visitor_id`). Starts from check_in_at
    (indexed) when a range is given."""
    query: dict = {}
    if f.status:
        query["status"] = f.status
    if f.start or f.end:
        query["check_in_at"] = {k: v for k, v in (("$gte", f.start), ("$lt", f.end)) if v}
    for field, value in (("host_id", f.host_id), ("department_id", f.department_id), ("gate_id", f.gate_id),
                         ("visitor_id", f.visitor_id)):
        if value:
            query[field] = value
    if f.guard_id:
        query["$or"] = [{"checked_in_by": f.guard_id}, {"checked_out_by": f.guard_id}]
    if f.reason_code:
        query["reason_code"] = f.reason_code
    if visit_number is not None:
        query["visit_number"] = visit_number
    elif visitor_ids is not None:
        query["visitor_id"] = {"$in": visitor_ids}
    return query


async def find_by_id(db: AsyncDatabase, visit_id: ObjectId, *, hide_pass_secrets: bool = False,
                     session: AsyncClientSession | None = None) -> dict | None:
    """The visit; with hide_pass_secrets, without the pass token, revocation and print data."""
    return await db.visits.find_one({"_id": visit_id}, LIST_PROJECTION if hide_pass_secrets else None,
                                    session=session)


async def find_by_number(db: AsyncDatabase, visit_number: str) -> dict | None:
    return await db.visits.find_one({"visit_number": visit_number})


async def find_active_for_visitor(db: AsyncDatabase, visitor_id: ObjectId) -> dict | None:
    """The visitor's visit that is CHECKED_IN right now (at most one, enforced by a unique index)."""
    return await db.visits.find_one({"visitor_id": visitor_id, "status": "CHECKED_IN"})


async def is_photo_of_active_visit(db: AsyncDatabase, photo_id: ObjectId) -> bool:
    return bool(await db.visits.count_documents({"photo_id": photo_id, "status": "CHECKED_IN"}, limit=1))


async def list_overstayed(db: AsyncDatabase, now: datetime, limit: int) -> list[dict]:
    """CHECKED_IN visits whose badge expired at or before `now` (full documents)."""
    return await db.visits.find({"status": "CHECKED_IN", "pass.expires_at": {"$lte": now}}) \
        .limit(limit).to_list(length=limit)


async def next_daily_number(db: AsyncDatabase, day: date, session: AsyncClientSession) -> int:
    """1, 2, 3, ... per (local) day; atomic across gates and part of the caller's transaction."""
    counter = await db.counters.find_one_and_update(
        {"_id": f"visit_number:{day.isoformat()}"}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER, session=session)
    return counter["seq"]


async def insert(db: AsyncDatabase, visit: dict, session: AsyncClientSession | None = None) -> ObjectId:
    """Raises DuplicateKey if the visitor already has a CHECKED_IN visit (or the number is taken)."""
    with duplicates_as_domain_error():
        return (await db.visits.insert_one(visit, session=session)).inserted_id


async def check_out_if_active(db: AsyncDatabase, visit_id: ObjectId, *, now: datetime, user_id: ObjectId,
                              user_name: str, gate_id: ObjectId | None, gate_name: str | None, method: str,
                              session: AsyncClientSession | None = None) -> dict | None:
    """CHECKED_IN -> CHECKED_OUT in one conditional update (only one request can win).
    Returns the updated visit, or None if it was not checked in."""
    fields = {"status": "CHECKED_OUT", "check_out_at": now, "checked_out_by": user_id,
              "checkout_gate_id": gate_id, "checkout_method": method,
              "snapshot.checked_out_by_name": user_name, "snapshot.checkout_gate_name": gate_name,
              "updated_at": now}
    return await db.visits.find_one_and_update(
        {"_id": visit_id, "status": "CHECKED_IN"}, {"$set": fields}, return_document=ReturnDocument.AFTER,
        session=session)


async def update_belongings_if_active(db: AsyncDatabase, visit_id: ObjectId, *, belongings: list[str],
                                      vehicle_registration: str | None, set_personal_material: bool,
                                      personal_material: dict | None, now: datetime,
                                      session: AsyncClientSession | None = None) -> dict | None:
    """Replaces belongings and vehicle (and, with set_personal_material, the Personal Material slip) on a
    CHECKED_IN visit. Returns the updated visit without pass secrets, or None if it was not checked in."""
    fields: dict = {"belongings": belongings, "vehicle_registration": vehicle_registration, "updated_at": now}
    if set_personal_material:
        fields["personal_material"] = personal_material
    return await db.visits.find_one_and_update(
        {"_id": visit_id, "status": "CHECKED_IN"}, {"$set": fields},
        return_document=ReturnDocument.AFTER, projection=LIST_PROJECTION, session=session)


async def list_active(db: AsyncDatabase, limit: int) -> list[dict]:
    """CHECKED_IN visits, latest check-in first, without pass secrets."""
    return await db.visits.find({"status": "CHECKED_IN"}, LIST_PROJECTION).sort("check_in_at", -1) \
        .limit(limit).to_list(length=limit)


async def count_active(db: AsyncDatabase) -> int:
    return await db.visits.count_documents({"status": "CHECKED_IN"})


async def list_page(db: AsyncDatabase, query: dict, *, after: tuple[datetime, ObjectId] | None,
                    limit: int) -> list[dict]:
    """Visits matching `query` (from filter_query), newest check-in first, without pass secrets.
    `after`: the (check_in_at, ID) of the last row already shown."""
    if after:
        last_at, last_id = after
        query = {"$and": [query, {"$or": [{"check_in_at": {"$lt": last_at}},
                                          {"check_in_at": last_at, "_id": {"$lt": last_id}}]}]}
    return await db.visits.find(query, LIST_PROJECTION).sort(NEWEST_FIRST).limit(limit).to_list(length=limit)


# --- passes (the `pass` sub-document of a visit) ---

async def set_pass_if_active(db: AsyncDatabase, visit_id: ObjectId, new_pass: dict, now: datetime,
                             session: AsyncClientSession | None = None) -> None:
    """Replaces the whole pass (token, expiry, revoked tokens, print data) on a CHECKED_IN visit."""
    await db.visits.update_one({"_id": visit_id, "status": "CHECKED_IN"},
                               {"$set": {"pass": new_pass, "updated_at": now}}, session=session)


async def revoke_pass(db: AsyncDatabase, visit_id: ObjectId, *, user_id: ObjectId, now: datetime,
                      session: AsyncClientSession | None = None) -> None:
    await db.visits.update_one(
        {"_id": visit_id}, {"$set": {"pass.revoked_at": now, "pass.revoked_by": user_id, "updated_at": now}},
        session=session)


async def find_by_pass_token(db: AsyncDatabase, token_hash: str) -> dict | None:
    """The visit whose current pass has this token hash (full document, including the pass)."""
    return await db.visits.find_one({"pass.token_hash": token_hash})


async def find_by_replaced_pass_token(db: AsyncDatabase, token_hash: str) -> dict | None:
    """_id and visit_number of the visit whose pass was reissued, replacing this token."""
    return await db.visits.find_one({"pass.revoked_token_hashes": token_hash}, {"visit_number": 1})
