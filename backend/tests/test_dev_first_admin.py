"""Development first-run account (python -m app.cli dev-first-admin, run by start-dev.bat)."""
import uuid

import pytest
from pymongo import MongoClient

from app import cli
from app.core.config import get_settings
from app.main import create_app
from tests.conftest import TEST_MONGO_URI, ApiClient, make_settings


@pytest.fixture
def dev_env(monkeypatch, tmp_path):
    db_name = f"cgvms_test_{uuid.uuid4().hex[:10]}"
    for key, value in {"CG_ENVIRONMENT": "development", "CG_MONGO_URI": TEST_MONGO_URI, "CG_MONGO_DB": db_name,
                       "CG_PHOTO_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield db_name
    get_settings.cache_clear()
    MongoClient(TEST_MONGO_URI).drop_database(db_name)


def run(monkeypatch, command="dev-first-admin") -> int:
    monkeypatch.setattr("sys.argv", ["app.cli", command])
    get_settings.cache_clear()
    return cli.main()


def test_creates_admin_admin1234_that_must_be_changed(monkeypatch, dev_env, capsys):
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    assert "admin / admin1234" in capsys.readouterr().out
    user = MongoClient(TEST_MONGO_URI)[dev_env].users.find_one({"username": "admin"})
    assert user["role"] == "ADMIN" and user["must_change_password"] is True
    assert "admin1234" not in str(user)                                  # only the argon2 hash is stored


def test_does_nothing_when_accounts_exist(monkeypatch, dev_env, capsys):
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    before = MongoClient(TEST_MONGO_URI)[dev_env].users.find_one({"username": "admin"})["password_hash"]
    assert run(monkeypatch) == 0
    assert "nothing changed" in capsys.readouterr().out
    users = list(MongoClient(TEST_MONGO_URI)[dev_env].users.find())
    assert len(users) == 1 and users[0]["password_hash"] == before


@pytest.mark.parametrize("environment", ["production", "test"])
def test_refused_outside_development(monkeypatch, dev_env, environment, capsys):
    monkeypatch.setenv("CG_ENVIRONMENT", environment)
    if environment == "production":
        monkeypatch.setenv("CG_MONGO_URI", "mongodb://u:p@localhost:27018/?tls=true&tlsCAFile=ca.pem")
    assert run(monkeypatch) == 2
    assert "only works with CG_ENVIRONMENT=development" in capsys.readouterr().err
    assert MongoClient(TEST_MONGO_URI)[dev_env].users.count_documents({}) == 0


def test_first_login_forces_a_proper_new_password(monkeypatch, dev_env):
    import asyncio

    import httpx
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    change = "/api/v1/auth/change-password"

    async def first_login():
        app = create_app(make_settings(environment="development", mongo_db=dev_env))
        async with app.router.lifespan_context(app):
            async with ApiClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
                r = await c.login("admin", "admin1234")
                assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
                assert (await c.get("/api/v1/visits")).json()["error"]["code"] == "password_change_required"
                weak = await c.post(change, json={"current_password": "admin1234", "new_password": "admin12345"})
                assert weak.status_code == 422                        # the normal policy applies to the new one
                ok = await c.post(change, json={"current_password": "admin1234", "new_password": "Gate-Office-2026"})
                assert ok.status_code == 204, ok.text
            async with ApiClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
                assert (await c.login("admin", "admin1234")).status_code == 401      # the default no longer works
                assert (await c.login("admin", "Gate-Office-2026")).status_code == 200

    asyncio.run(first_login())


def test_the_temporary_password_cannot_skip_the_policy_otherwise():
    import asyncio

    from app.core.errors import AppError
    from app.core.permissions import Role
    from app.services.users import create_user

    async def attempt():
        await create_user(None, actor=None, meta=None, username="admin", display_name="A", role=Role.ADMIN,
                          password="admin1234", must_change_password=False, enforce_policy=False)
    with pytest.raises(AppError):
        asyncio.run(attempt())
