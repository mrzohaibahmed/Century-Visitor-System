"""MongoDB access for the directory collections: gates, departments and hosts (queries only)."""
import re
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.db.schema import CASE_INSENSITIVE
from app.repositories.errors import duplicates_as_domain_error

COLLECTIONS = {"gates", "departments", "hosts"}


def _collection(db: AsyncDatabase, name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"not a directory collection: {name}")
    return db[name]


async def find_by_id(db: AsyncDatabase, collection: str, item_id: ObjectId,
                     session: AsyncClientSession | None = None) -> dict | None:
    return await _collection(db, collection).find_one({"_id": item_id}, session=session)


async def list_items(db: AsyncDatabase, collection: str, *, include_inactive: bool, limit: int,
                     name_search_prefix: str | None = None, by_department: bool = False,
                     department_id: ObjectId | None = None) -> list[dict]:
    """Gates and departments sort by name (ignoring case); hosts by their search key.
    Host filters: `name_search_prefix`, and with `by_department` the hosts whose department is
    `department_id` (None: hosts without a department)."""
    query: dict = {} if include_inactive else {"is_active": True}
    if name_search_prefix:
        query["name_search"] = {"$regex": "^" + re.escape(name_search_prefix)}
    if by_department:
        query["department_id"] = department_id
    cursor = _collection(db, collection).find(query)
    if collection == "hosts":
        cursor = cursor.sort([("name_search", 1)])
    else:
        cursor = cursor.sort([("name", 1)]).collation(CASE_INSENSITIVE)
    return await cursor.limit(limit).to_list(length=limit)


async def names_by_id(db: AsyncDatabase, collection: str, ids: set[ObjectId]) -> dict[ObjectId, str]:
    if not ids:
        return {}
    docs = await _collection(db, collection).find({"_id": {"$in": list(ids)}}, {"name": 1}).to_list(length=len(ids))
    return {d["_id"]: d["name"] for d in docs}


async def insert(db: AsyncDatabase, collection: str, doc: dict, session: AsyncClientSession | None = None
                 ) -> ObjectId:
    """Raises DuplicateKey for a gate or department name that already exists (ignoring case)."""
    with duplicates_as_domain_error():
        return (await _collection(db, collection).insert_one(doc, session=session)).inserted_id


async def update_fields(db: AsyncDatabase, collection: str, item_id: ObjectId, fields: dict,
                        session: AsyncClientSession | None = None) -> None:
    """Sets `fields` and updated_at. Raises DuplicateKey for a name that already exists."""
    with duplicates_as_domain_error():
        await _collection(db, collection).update_one(
            {"_id": item_id}, {"$set": {**fields, "updated_at": datetime.now(UTC)}}, session=session)
