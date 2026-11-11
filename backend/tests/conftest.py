"""
Test fixtures.

Tests run against a REAL MongoDB replica set (mongomock cannot model
transactions or partial unique indexes faithfully). Default: the local
development instance started by scripts/dev_mongo.py. Override with
CG_TEST_MONGO_URI. Every test gets its own throw-away database
(cgvms_test_<random>), dropped afterwards.

SQL Server (the move from MongoDB): with CG_DB_BACKEND=mssql the whole run
uses one throw-away SQL Server database, created and migrated once per session
and emptied before every test (see tests/mssql_support.py). Tests that inspect
stored records use harness.store (tests/store.py), which works on both. The
mssql_test_settings / sql_database fixtures (SQL Server foundation tests) are
skipped when no SQL Server is reachable.
"""
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from sqlalchemy.exc import DBAPIError

from app.core import security
from app.core.config import Settings
from app.db.backend import BACKEND
from app.db.client import Database
from app.db.migrate import apply_schema
from app.db.sql.database import SqlDatabase
from app.db.sql.engine import describe_error
from app.main import create_app
from tests.mssql_support import (
    create_test_database,
    drop_test_database,
    empty_all_tables,
    empty_all_tables_sync,
    new_test_database_name,
    sql_settings_overrides,
)
from tests.store import SqlStore

TEST_MONGO_URI = os.environ.get("CG_TEST_MONGO_URI", "mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev")
PRODUCTION_LIKE_URI = ("mongodb://cgvms_app:not-a-real-password@localhost:27018/century_gate_vms"
                       "?replicaSet=cgvms&tls=true&tlsCAFile=ca.pem&authSource=century_gate_vms")

# Production argon2 costs ~150 ms per hash; tests use tiny parameters.
# tests/test_auth.py checks the production parameters separately.
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


@pytest.fixture(autouse=True)
def fast_password_hashing():
    security.use_hasher(FAST_HASHER)
    yield
    security.use_hasher(PasswordHasher())


def pytest_sessionstart(session):
    if BACKEND != "mongo":          # SQL Server: the session database fixture checks the server (or skips)
        return
    try:
        MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=2000).admin.command("ping")
    except ConnectionFailure:
        pytest.exit(
            "Test MongoDB is not reachable. Start it with:\n"
            "    backend\\.venv\\Scripts\\python scripts\\dev_mongo.py start\n"
            "or set CG_TEST_MONGO_URI to a replica set.", returncode=3)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "mongo_uri": TEST_MONGO_URI,
        "mongo_db": f"cgvms_test_{uuid.uuid4().hex[:10]}",
        # Photos go to a throw-away folder per test, never to the development folder.
        "photo_dir": Path(tempfile.gettempdir()) / "cgvms_test_photos" / uuid.uuid4().hex[:10],
        "mongo_timeout_ms": 3000,
        "log_level": "INFO",
    }
    if overrides.get("environment") == "production" and "mongo_uri" not in overrides:
        # Production insists on an authenticated TLS connection; these settings are never connected.
        values["mongo_uri"] = PRODUCTION_LIKE_URI
    if "mssql_database" not in overrides:
        # Never the real database: settings made without a test database (same_database) point at one that
        # does not exist, so a test that connects with them fails instead of touching century_gate_vms.
        values |= sql_settings_overrides("cgvms_test_no_such_database")
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(request):
    if BACKEND == "mssql":
        # The session's SQL Server test database, emptied for this test.
        s = make_settings(**same_database(request.getfixturevalue("mssql_test_settings")))
        empty_all_tables_sync(s)
        yield s
    else:
        s = make_settings()
        yield s
        MongoClient(TEST_MONGO_URI).drop_database(s.mongo_db)
    shutil.rmtree(s.photo_dir, ignore_errors=True)


def same_database(settings: Settings) -> dict:
    """make_settings() overrides that point new settings at the same test database as `settings`."""
    if BACKEND == "mssql":
        return sql_settings_overrides(settings.mssql_database)
    return {"mongo_db": settings.mongo_db}


def database_env(settings: Settings) -> dict:
    """Environment variables that point a subprocess (python -m app.cli ...) at the test database."""
    if BACKEND == "mssql":
        return {"CG_DB_BACKEND": "mssql", "CG_MSSQL_SERVER": settings.mssql_server,
                "CG_MSSQL_DATABASE": settings.mssql_database, "CG_MSSQL_USERNAME": "", "CG_MSSQL_PASSWORD": "",
                "CG_MSSQL_TRUST_SERVER_CERTIFICATE": str(settings.mssql_trust_server_certificate).lower()}
    return {"CG_DB_BACKEND": "mongo", "CG_MONGO_URI": TEST_MONGO_URI, "CG_MONGO_DB": settings.mongo_db}


async def prepare_schema(database) -> None:
    """The schema for a test app. MongoDB: applied to the test's new database. SQL Server: already migrated
    once for the session (and the tables emptied by the settings fixture)."""
    if BACKEND == "mongo":
        await apply_schema(database.db)


mongo_only = pytest.mark.skipif(BACKEND != "mongo", reason="checks MongoDB itself (its schema or driver)")
mssql_only = pytest.mark.skipif(BACKEND != "mssql", reason="checks SQL Server itself (its schema or driver)")


def new_record_id():
    """A new record ID of the backend this run uses (ObjectId / GUID), for records made up in tests."""
    if BACKEND == "mssql":
        from app.repositories.mssql.ids import new_id
        return new_id()
    from bson import ObjectId
    return ObjectId()


def raw_database_errors() -> tuple[type[Exception], type[Exception]]:
    """(the driver's error for a duplicate key, its error for a record the schema rejects), for tests that
    write records directly: MongoDB (DuplicateKeyError, WriteError), SQL Server (IntegrityError twice)."""
    if BACKEND == "mssql":
        from sqlalchemy.exc import IntegrityError
        return IntegrityError, IntegrityError
    from pymongo.errors import DuplicateKeyError, WriteError
    return DuplicateKeyError, WriteError


def stored_bytes(docs: list[dict]) -> bytes:
    """Every value of these stored records as bytes, to prove a secret is not stored in the clear: the raw
    BSON for MongoDB; for SQL Server every text (UTF-8) and byte value, keys included."""
    if BACKEND == "mongo":
        import bson
        return b"".join(bson.encode(d) for d in docs)
    out = bytearray()

    def walk(value):
        if isinstance(value, (bytes, bytearray, memoryview)):
            out.extend(bytes(value))
        elif isinstance(value, str):
            out.extend(value.encode("utf-8"))
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        elif value is not None:
            out.extend(str(value).encode("utf-8"))

    walk(docs)
    return bytes(out)


def unknown_id() -> str:
    """A well-formed record ID that no record has, in the format of the backend this run uses (an
    ObjectId for MongoDB, a GUID for SQL Server): for "valid but not found" cases."""
    if BACKEND == "mssql":
        from app.repositories.mssql.ids import new_id
        return str(new_id())
    from bson import ObjectId
    return str(ObjectId())


def record_id(text: str):
    """An ID from an API response as the backend's record ID, to compare with stored records."""
    from app.repositories.ids import to_id
    return to_id(text)


def visitor_ids_in(query) -> list | None:
    """The visitor IDs a visit filter (services.visits.visit_query) is narrowed to, read from the backend's
    query (a MongoDB filter, or a SQL condition); None if it is not narrowed to a list of visitors."""
    if BACKEND == "mongo":
        value = query.get("visitor_id")
        return value["$in"] if isinstance(value, dict) and "$in" in value else None
    from sqlalchemy.sql import operators

    from app.repositories.mssql.tables import visits
    for clause in getattr(query, "clauses", [query]):
        if getattr(clause, "left", None) is visits.c.visitor_id and clause.operator is operators.in_op:
            return list(clause.right.value)
    return None


def store_of(db):
    """harness.store for a services' database handle (harness.db), for helpers that are given only that."""
    return SqlStore(db) if BACKEND == "mssql" else db


async def insert_seed(store, collection: str, doc: dict, *, unchecked_values: bool = False):
    """Inserts a made-up record for a report test, whose references (visitor, department, guard...) need not
    exist: MongoDB never checked references; on SQL Server this one insert runs with the table's foreign
    keys paused (the throw-away test database only). unchecked_values: also values the schema does not
    allow, like MongoDB's bypass_document_validation (SQL Server: its CHECK constraints paused too). Unique
    indexes always apply. Returns what insert_one returns (.inserted_id); doc["_id"] is set."""
    if BACKEND == "mssql":
        return await store[collection].insert_one(doc, pause_constraints="all" if unchecked_values else "foreign_keys")
    return await store[collection].insert_one(doc, bypass_document_validation=unchecked_values)


def store_for(database):
    """harness.store: the stored records, for tests that inspect or prepare them (see tests/store.py)."""
    return SqlStore(database.db) if BACKEND == "mssql" else database.db


@pytest.fixture
async def database(settings):
    db = Database(settings)
    yield db
    await db.close()


@pytest.fixture
async def migrated(database):
    await apply_schema(database.db)
    return database


@pytest.fixture(scope="session")
def mssql_test_settings():
    """Settings for the session's SQL Server test database (created and migrated once, dropped at the end).
    Every test that needs it is skipped when no SQL Server is reachable."""
    s = make_settings(**sql_settings_overrides(new_test_database_name()))
    try:
        create_test_database(s)
    except DBAPIError as e:
        pytest.skip(f"SQL Server test instance not reachable ({describe_error(e)})")
    yield s
    drop_test_database(s)


@pytest.fixture
async def sql_database(mssql_test_settings):
    """The SQL Server test database with every table emptied first (SqlDatabase; .db for repositories)."""
    database = SqlDatabase(mssql_test_settings)
    await empty_all_tables(database)
    yield database
    await database.close()


BASE_URL = "https://testserver"      # https: session cookies are Secure


async def _client_for(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client


class ApiClient(httpx.AsyncClient):
    """A browser stand-in: keeps cookies and echoes the CSRF cookie as X-CSRF-Token,
    exactly like frontend/src/lib/api/client.ts."""

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

    def __init__(self, app, db, store=None):
        self.app = app
        self.db = db                # what services receive
        # the stored records, for inspecting or preparing them in tests (see store_for)
        self.store = store if store is not None else (SqlStore(db) if BACKEND == "mssql" else db)
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
        await prepare_schema(app.state.database)
        h = AuthHarness(app, app.state.database.db, store_for(app.state.database))
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
