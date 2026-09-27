"""
Test fixtures.

Tests run against a REAL MongoDB replica set (mongomock cannot model
transactions or partial unique indexes faithfully). Default: the local
development instance started by scripts/dev_mongo.py. Override with
CG_TEST_MONGO_URI. Every test gets its own throw-away database
(cgvms_test_<random>), dropped afterwards.
"""
import os
import uuid

import httpx
import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from app.core.config import Settings
from app.db.client import Database
from app.db.migrate import apply_schema
from app.main import create_app

TEST_MONGO_URI = os.environ.get("CG_TEST_MONGO_URI", "mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev")


def pytest_sessionstart(session):
    try:
        MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=2000).admin.command("ping")
    except ConnectionFailure:
        pytest.exit(
            "Test MongoDB is not reachable. Start it with:\n"
            "    api\\.venv\\Scripts\\python scripts\\dev_mongo.py start\n"
            "or set CG_TEST_MONGO_URI to a replica set.", returncode=3)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "mongo_uri": TEST_MONGO_URI,
        "mongo_db": f"cgvms_test_{uuid.uuid4().hex[:10]}",
        "mongo_timeout_ms": 3000,
        "log_level": "INFO",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings():
    s = make_settings()
    yield s
    MongoClient(TEST_MONGO_URI).drop_database(s.mongo_db)


@pytest.fixture
async def database(settings):
    db = Database(settings)
    yield db
    await db.close()


@pytest.fixture
async def migrated(database):
    await apply_schema(database.db)
    return database


async def _client_for(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
async def client(app):
    async for c in _client_for(app):
        yield c


@pytest.fixture
def client_for():
    """Build a client for a custom app (e.g. with extra test-only routes)."""
    return _client_for
