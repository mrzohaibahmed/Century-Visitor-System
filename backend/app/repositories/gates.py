"""MongoDB access for gates (queries only; rules live in services)."""
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase


async def active_ids(db: AsyncDatabase, limit: int) -> list[ObjectId]:
    """IDs of up to `limit` active gates (callers use limit=2 to tell "exactly one" from "several")."""
    docs = await db.gates.find({"is_active": True}, {"_id": 1}).limit(limit).to_list(length=limit)
    return [d["_id"] for d in docs]


async def count_active(db: AsyncDatabase, limit: int) -> int:
    """Number of active gates, counted up to `limit`."""
    return await db.gates.count_documents({"is_active": True}, limit=limit)


async def find_active(db: AsyncDatabase, gate_id: ObjectId | str) -> dict | None:
    """The gate if it exists and is active. A string ID must already be validated (see schemas.common)."""
    return await db.gates.find_one({"_id": ObjectId(gate_id), "is_active": True})


async def find_any_active(db: AsyncDatabase) -> dict | None:
    return await db.gates.find_one({"is_active": True})
