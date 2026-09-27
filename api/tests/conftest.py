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
from argon2 import PasswordHasher
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from app.core import security
from app.core.config import Settings
from app.db.client import Database
from app.db.migrate import apply_schema
from app.main import create_app

TEST_MONGO_URI = os.environ.get("CG_TEST_MONGO_URI", "mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev")

# Production argon2 costs ~150 ms per hash; tests use tiny parameters.
# tests/test_auth.py checks the production parameters separately.
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


@pytest.fixture(autouse=True)
def fast_password_hashing():
    security.use_hasher(FAST_HASHER)
    yield
    security.use_hasher(PasswordHasher())


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


BASE_URL = "https://testserver"      # https: session cookies are Secure


async def _client_for(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client


class ApiClient(httpx.AsyncClient):
    """A browser stand-in: keeps cookies and echoes the CSRF cookie as X-CSRF-Token,
    exactly like web/src/lib/api/client.ts."""

    async def request(self, method, url, *args, **kwargs):
        if method.upper() not in ("GET", "HEAD", "OPTIONS"):
            csrf = self.cookies.get("cg_csrf")
            if csrf:
                kwargs["headers"] = {"X-CSRF-Token": csrf, **(kwargs.get("headers") or {})}
        return await super().request(method, url, *args, **kwargs)

    async def post_without_csrf(self, url, **kwargs) -> httpx.Response:
        """Sends only the headers given (simulates a forged cross-site request)."""
        return await httpx.AsyncClient.request(self, "POST", url, **kwargs)

    async def login(self, username: str, password: str) -> httpx.Response:
        return await self.post("/api/v1/auth/login", json={"username": username, "password": password})


class AuthHarness:
    """A migrated app plus helpers to create users and get logged-in clients."""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self._clients: list[ApiClient] = []

    def client(self) -> ApiClient:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
        c = ApiClient(transport=transport, base_url=BASE_URL)
        self._clients.append(c)
        return c

    async def create_user(self, username: str, password: str, role: str = "GUARD", *,
                          must_change_password: bool = False, display_name: str | None = None) -> dict:
        from app.core.permissions import Role
        from app.services.users import create_user
        return await create_user(self.db, actor=None, meta=None, username=username,
                                 display_name=display_name or username.title(), role=Role(role),
                                 password=password, must_change_password=must_change_password)

    async def logged_in(self, username: str, password: str) -> ApiClient:
        c = self.client()
        r = await c.login(username, password)
        assert r.status_code == 200, r.text
        return c

    async def close(self):
        for c in self._clients:
            await c.aclose()


@pytest.fixture
async def harness(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await apply_schema(app.state.database.db)
        h = AuthHarness(app, app.state.database.db)
        yield h
        await h.close()


ADMIN_PASSWORD = "Gatekeeper-Pass-1"
GUARD_PASSWORD = "Guard-Test-Pass-1"


@pytest.fixture
async def admin(harness):
    await harness.create_user("admin", ADMIN_PASSWORD, "ADMIN")
    return await harness.logged_in("admin", ADMIN_PASSWORD)


@pytest.fixture
async def guard(harness):
    await harness.create_user("guard1", GUARD_PASSWORD, "GUARD")
    return await harness.logged_in("guard1", GUARD_PASSWORD)


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
