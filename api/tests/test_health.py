import pytest

from app.core.config import APP_VERSION
from app.db.migrate import apply_schema
from app.main import create_app
from tests.conftest import make_settings

pytestmark = pytest.mark.anyio


async def test_liveness(client):
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": APP_VERSION}


async def test_ready_reports_unmigrated_database(client):
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready",
                        "checks": {"database": "ok", "schema_version": "missing", "transactions": "ok",
                                   "photo_storage": "ok"}}


async def test_ready_after_migration(client, app):
    await apply_schema(app.state.database.db)
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready",
                        "checks": {"database": "ok", "schema_version": "ok", "transactions": "ok",
                                   "photo_storage": "ok"}}


async def test_ready_reports_outdated_schema(client, app):
    await apply_schema(app.state.database.db)
    await app.state.database.db.settings.update_one({"_id": "schema"}, {"$set": {"version": 0}})
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["schema_version"] == "outdated"


async def test_unreachable_database_fails_fast_without_revealing_the_uri(client_for):
    settings = make_settings(mongo_uri="mongodb://dbuser:Db-Secret-2@127.0.0.1:1/?directConnection=true",
                             mongo_timeout_ms=300)
    async for client in client_for(create_app(settings)):
        r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "unavailable"
    assert "Db-Secret-2" not in r.text and "127.0.0.1" not in r.text


async def test_docs_are_disabled_outside_development(client):
    assert (await client.get("/api/docs")).status_code == 404
    assert (await client.get("/api/openapi.json")).status_code == 404
