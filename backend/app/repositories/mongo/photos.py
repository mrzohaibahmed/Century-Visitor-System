"""MongoDB access for photo metadata (the image files themselves live in CG_PHOTO_DIR)."""
from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def find_by_id(db: AsyncDatabase, photo_id: ObjectId) -> dict | None:
    return await db.photos.find_one({"_id": photo_id})


async def link_first_visit(db: AsyncDatabase, photo_id: ObjectId, visit_id: ObjectId,
                           session: AsyncClientSession | None = None) -> None:
    """Records the visit where the photo was taken (only once: a later visit may reuse the photo)."""
    await db.photos.update_one({"_id": photo_id, "visit_id": None}, {"$set": {"visit_id": visit_id}},
                               session=session)


async def insert(db: AsyncDatabase, doc: dict, session: AsyncClientSession | None = None) -> ObjectId:
    return (await db.photos.insert_one(doc, session=session)).inserted_id
