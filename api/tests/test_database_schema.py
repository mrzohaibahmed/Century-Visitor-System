"""The new database's collections, validators and constraint indexes."""
from datetime import UTC, datetime

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from app.db.migrate import LegacyDatabaseError, apply_schema
from app.db.schema import CASE_INSENSITIVE, COLLECTIONS, SCHEMA_VERSION

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC)


def visit(visitor_id, status="CHECKED_IN", number="V-2026-000001"):
    return {"visit_number": number, "visitor_id": visitor_id, "status": status, "check_in_at": NOW,
            "checked_in_by": ObjectId(), "snapshot": {"visitor_name": "Ali Khan"},
            "created_at": NOW, "updated_at": NOW}


async def test_migration_creates_all_collections_and_named_indexes(migrated):
    db = migrated.db
    assert {spec.name for spec in COLLECTIONS} <= set(await db.list_collection_names())
    for spec in COLLECTIONS:
        names = set((await db[spec.name].index_information()).keys())
        assert {ix.document["name"] for ix in spec.indexes} <= names, spec.name
    assert (await db.settings.find_one({"_id": "schema"}))["version"] == SCHEMA_VERSION


async def test_migration_is_idempotent(migrated):
    report = await apply_schema(migrated.db)
    assert report.created_collections == []


async def test_migration_refuses_a_database_with_legacy_collections(database):
    await database.db.create_collection("app_settings")          # marker of the desktop database
    with pytest.raises(LegacyDatabaseError):
        await apply_schema(database.db)
    assert await database.db.list_collection_names() == ["app_settings"]   # nothing else touched


async def test_username_is_unique_ignoring_case(migrated):
    users = migrated.db.users
    doc = {"password_hash": "x", "role": "GUARD", "is_active": True, "created_at": NOW, "updated_at": NOW}
    await users.insert_one({"username": "guard1", **doc})
    with pytest.raises(DuplicateKeyError):
        await users.insert_one({"username": "GUARD1", **doc})


async def test_validator_rejects_unknown_role(migrated):
    with pytest.raises(WriteError):
        await migrated.db.users.insert_one({"username": "guard1", "password_hash": "x", "role": "SUPERUSER",
                                            "is_active": True, "created_at": NOW, "updated_at": NOW})


async def test_validator_rejects_unknown_visit_status_and_bad_visit_number(migrated):
    with pytest.raises(WriteError):
        await migrated.db.visits.insert_one(visit(ObjectId(), status="Checked Out"))
    with pytest.raises(WriteError):
        await migrated.db.visits.insert_one(visit(ObjectId(), number="42"))


async def test_one_active_visit_per_visitor(migrated):
    visits = migrated.db.visits
    person = ObjectId()
    await visits.insert_one(visit(person, "CHECKED_OUT", "V-2026-000001"))
    await visits.insert_one(visit(person, "CHECKED_OUT", "V-2026-000002"))    # history is fine
    await visits.insert_one(visit(person, "CHECKED_IN", "V-2026-000003"))
    with pytest.raises(DuplicateKeyError):
        await visits.insert_one(visit(person, "CHECKED_IN", "V-2026-000004"))
    await visits.insert_one(visit(ObjectId(), "CHECKED_IN", "V-2026-000005"))  # someone else is fine


async def test_one_active_watchlist_entry_per_identity(migrated):
    watchlist = migrated.db.watchlist
    entry = {"identifier": "CNIC:12345-1234567-1", "identity": {"type": "CNIC", "number": "12345-1234567-1"},
             "reason": "Theft", "created_by": ObjectId(), "created_at": NOW}
    await watchlist.insert_one({**entry, "is_active": False})
    await watchlist.insert_one({**entry, "is_active": True})
    with pytest.raises(DuplicateKeyError):
        await watchlist.insert_one({**entry, "is_active": True})


async def test_department_names_unique_ignoring_case(migrated):
    doc = {"is_active": True, "created_at": NOW, "updated_at": NOW}
    await migrated.db.departments.insert_one({"name": "Security", **doc})
    with pytest.raises(DuplicateKeyError):
        await migrated.db.departments.insert_one({"name": "SECURITY", **doc})
    found = await migrated.db.departments.find_one({"name": "security"}, collation=CASE_INSENSITIVE)
    assert found["name"] == "Security"


async def test_multi_document_transactions_are_available(migrated):
    """Check-in will write the visit and its audit record in one transaction."""
    db = migrated.db
    async with db.client.start_session() as session:
        async with await session.start_transaction():
            await db.counters.insert_one({"_id": "tx-test", "seq": 1}, session=session)
            await session.abort_transaction()
    assert await db.counters.find_one({"_id": "tx-test"}) is None
