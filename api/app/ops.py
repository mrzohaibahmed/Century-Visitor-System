"""
Operator checks for backups and restores (run from the command line, never over HTTP).

verify_data()   Read-only integrity check of a database + photo folder:
                record counts, every photo record has its file with the recorded
                SHA-256, visits and visitors point at existing photos. Output holds
                counts and ids only: no names, ID numbers or paths.

restore_check() For a RESTORED COPY only (refuses production settings): runs
                verify_data(), then starts the real API in-process against the
                copy, creates two throw-away accounts in the copy and proves that
                the photo and access rules still hold (admin sees photos, a guard
                only the ones needed at the gate, anonymous nobody).
"""
import asyncio
import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.db.migrate import current_schema_version
from app.db.schema import COLLECTION_NAMES, SCHEMA_VERSION

MAX_LISTED = 20          # ids listed per problem; the counts are complete


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


async def verify_data(db: AsyncDatabase, settings: Settings) -> dict:
    counts = {name: await db[name].estimated_document_count() for name in COLLECTION_NAMES}
    problems: dict[str, list[str]] = {"photo_file_missing": [], "photo_file_changed": [],
                                      "visit_photo_missing": [], "visitor_photo_missing": []}
    totals = {key: 0 for key in problems}

    def note(kind: str, oid: ObjectId) -> None:
        totals[kind] += 1
        if len(problems[kind]) < MAX_LISTED:
            problems[kind].append(str(oid))

    photo_ids: set[ObjectId] = set()
    async for photo in db.photos.find({}, {"storage_key": 1, "sha256": 1}):
        photo_ids.add(photo["_id"])
        path = settings.photo_dir / photo["storage_key"][:2] / f"{photo['storage_key']}.jpg"
        actual = await asyncio.to_thread(_sha256, path)
        if actual is None:
            note("photo_file_missing", photo["_id"])
        elif actual != photo["sha256"]:
            note("photo_file_changed", photo["_id"])
    async for visit in db.visits.find({"photo_id": {"$type": "objectId"}}, {"photo_id": 1}):
        if visit["photo_id"] not in photo_ids:
            note("visit_photo_missing", visit["_id"])
    async for visitor in db.visitors.find({"current_photo_id": {"$type": "objectId"}}, {"current_photo_id": 1}):
        if visitor["current_photo_id"] not in photo_ids:
            note("visitor_photo_missing", visitor["_id"])

    version = await current_schema_version(db)
    return {
        "checked_at": datetime.now(UTC).isoformat(), "database": db.name,
        "schema_version": version, "expected_schema_version": SCHEMA_VERSION,
        "counts": counts, "photo_files_checked": len(photo_ids),
        "problems": {k: {"count": totals[k], "examples": v} for k, v in problems.items() if totals[k]},
        "ok": version == SCHEMA_VERSION and not any(totals.values()),
    }


async def restore_check(settings: Settings) -> dict:
    """verify_data() plus the access rules, on a restored copy (never production)."""
    if settings.environment == "production":
        raise RuntimeError("restore-check writes test accounts and must only run against a restored COPY "
                           "(CG_ENVIRONMENT=test), never against production.")
    import httpx

    from app.core.permissions import Role
    from app.main import create_app
    from app.services.users import create_user

    app = create_app(settings)
    results: dict[str, object] = {}
    async with app.router.lifespan_context(app):
        db = app.state.database.db
        results["data"] = await verify_data(db, settings)

        suffix = secrets.token_hex(3)
        password = f"Restore-Check-{secrets.token_hex(8)}"
        accounts = {"admin": f"restore.admin.{suffix}", "guard": f"restore.guard.{suffix}"}
        for role, username in accounts.items():
            await create_user(db, actor=None, meta=None, username=username, display_name="Restore check",
                              role=Role[role.upper()], password=password, must_change_password=False)

        transport = httpx.ASGITransport(app=app)
        checks: dict[str, bool] = {}

        async def login(username: str) -> httpx.AsyncClient:
            client = httpx.AsyncClient(transport=transport, base_url="https://restore-check")
            r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
            checks[f"login_{username.split('.')[1]}"] = r.status_code == 200
            return client

        async with httpx.AsyncClient(transport=transport, base_url="https://restore-check") as anonymous:
            admin, guard = await login(accounts["admin"]), await login(accounts["guard"])
            try:
                checks["users_readable"] = (await admin.get("/api/v1/users")).status_code == 200
                checks["guard_refused_admin_pages"] = (await guard.get("/api/v1/users")).status_code == 403
                checks["visits_readable"] = (await guard.get("/api/v1/visits?limit=5")).status_code == 200
                checks["watchlist_readable_by_admin"] = (await admin.get("/api/v1/watchlist")).status_code == 200
                checks["watchlist_refused_to_guard"] = (await guard.get("/api/v1/watchlist")).status_code == 403

                current = await db.visitors.find_one({"current_photo_id": {"$type": "objectId"}},
                                                     {"current_photo_id": 1})
                if current:
                    url = f"/api/v1/photos/{current['current_photo_id']}"
                    got = await admin.get(url)
                    checks["admin_sees_photo"] = got.status_code == 200 and got.content[:3] == b"\xff\xd8\xff"
                    checks["guard_sees_current_photo"] = (await guard.get(url)).status_code == 200
                    checks["anonymous_refused_photo"] = (await anonymous.get(url)).status_code == 401
                    visit = await db.visits.find_one({"photo_id": current["current_photo_id"]}, {"_id": 1})
                    if visit:
                        v = await admin.get(f"/api/v1/visits/{visit['_id']}")
                        checks["visit_links_to_photo"] = v.status_code == 200 and \
                            v.json().get("photo_id") == str(current["current_photo_id"])
                older = await db.photos.find_one({"_id": {"$nin": await db.visitors.distinct("current_photo_id")}},
                                                 {"_id": 1, "visitor_id": 1})
                if older and not await db.visits.count_documents({"photo_id": older["_id"], "status": "CHECKED_IN"}):
                    checks["guard_refused_older_photo"] = \
                        (await guard.get(f"/api/v1/photos/{older['_id']}")).status_code == 403
            finally:
                await admin.aclose()
                await guard.aclose()
        results["access"] = checks
        results["photo_checks_ran"] = any(k.endswith("photo") for k in checks)
    results["ok"] = bool(results["data"]["ok"]) and all(checks.values())
    return results
