import pytest

from app.core.config import APP_VERSION
from app.db.sql import revision
from app.main import create_app
from tests.conftest import make_settings, same_database

pytestmark = pytest.mark.anyio


async def test_liveness(client):
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": APP_VERSION}


async def test_ready_on_the_migrated_database(settings, client_for):
    async for client in client_for(create_app(make_settings(**same_database(settings)))):
        r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready",
                        "checks": {"database": "ok", "schema_version": "ok", "transactions": "ok",
                                   "photo_storage": "ok"}}


async def test_ready_reports_an_outdated_schema(settings, client_for, monkeypatch):
    # This code expecting a newer revision than the database has = the database needs `migrate`.
    monkeypatch.setattr(revision, "head_revision", lambda: "9999")
    async for client in client_for(create_app(make_settings(**same_database(settings)))):
        r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["schema_version"] == "outdated"


def test_schema_states():
    head = revision.head_revision()
    assert head is not None
    assert revision.schema_status(None) == "missing"            # never migrated
    assert revision.schema_status(head) == "ok"
    assert revision.schema_status("0001") == "outdated" != head


async def test_an_unreachable_database_fails_fast_without_revealing_where(client_for):
    settings = make_settings(mssql_server="127.0.0.1,1", mssql_database="cgvms_test_unreachable",
                             mssql_username="dbuser", mssql_password="Db-Secret-2", mssql_timeout_seconds=1,
                             mssql_trust_server_certificate=True)
    async for client in client_for(create_app(settings)):
        r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "unavailable"
    assert "Db-Secret-2" not in r.text and "127.0.0.1" not in r.text and "dbuser" not in r.text


async def test_docs_are_disabled_outside_development(client):
    assert (await client.get("/api/docs")).status_code == 404
    assert (await client.get("/api/openapi.json")).status_code == 404
