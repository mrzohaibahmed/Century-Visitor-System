"""
Applies app/db/schema.py to the configured database. Idempotent: safe to run on
every deployment. It creates collections, updates validators and creates
missing indexes. It never drops collections, indexes or documents.

Run:  python -m app.cli migrate
"""
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import LEGACY_DATABASE_NAMES
from app.db.schema import COLLECTIONS, SCHEMA_VERSION

log = logging.getLogger(__name__)

# Collections that only exist in the legacy desktop database. Finding one means
# the configuration points at the wrong database.
LEGACY_MARKERS = {"app_settings"}


class LegacyDatabaseError(RuntimeError):
    pass


@dataclass
class MigrationReport:
    created_collections: list[str] = field(default_factory=list)
    updated_validators: list[str] = field(default_factory=list)
    indexes: dict[str, list[str]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION


async def apply_schema(db: AsyncDatabase) -> MigrationReport:
    if db.name.lower() in LEGACY_DATABASE_NAMES:
        raise LegacyDatabaseError(f"Refusing to migrate the legacy database '{db.name}'.")
    existing = set(await db.list_collection_names())
    if existing & LEGACY_MARKERS:
        raise LegacyDatabaseError(
            f"Database '{db.name}' contains legacy desktop collections {sorted(existing & LEGACY_MARKERS)}; "
            "refusing to modify it. Point CG_MONGO_DB at the new web database.")

    report = MigrationReport()
    for spec in COLLECTIONS:
        options = {}
        if spec.validator:
            options = {"validator": spec.validator, "validationLevel": "strict", "validationAction": "error"}
        if spec.name not in existing:
            await db.create_collection(spec.name, **options)
            report.created_collections.append(spec.name)
        elif options:
            await db.command("collMod", spec.name, **options)
            report.updated_validators.append(spec.name)
        if spec.indexes:
            report.indexes[spec.name] = await db[spec.name].create_indexes(spec.indexes)

    await db.settings.update_one(
        {"_id": "schema"},
        {"$set": {"version": SCHEMA_VERSION, "applied_at": datetime.now(UTC)}},
        upsert=True,
    )
    log.info("Schema version %d applied to database %s (created: %s)",
             SCHEMA_VERSION, db.name, ", ".join(report.created_collections) or "none")
    return report


async def current_schema_version(db: AsyncDatabase) -> int | None:
    doc = await db.settings.find_one({"_id": "schema"}, {"version": 1})
    return doc.get("version") if doc else None
