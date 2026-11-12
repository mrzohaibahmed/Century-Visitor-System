"""First-run account (python -m app.cli first-admin, run by start-dev.bat and production.ps1)."""
import pytest
from sqlalchemy import select

from app import cli
from app.core.config import get_settings
from app.db.sql.engine import sync_engine
from app.main import create_app
from app.repositories import tables
from tests.conftest import ApiClient, database_env, make_settings, same_database


@pytest.fixture
def dev_env(monkeypatch, tmp_path, settings):
    """The commands run in this process, on the (emptied) test database."""
    for key, value in {**database_env(settings), "CG_ENVIRONMENT": "development", "CG_PHOTO_DIR": str(tmp_path),
                       "CG_FIRST_ADMIN_PASSWORD": "admin1234"}.items():    # independent of backend/.env
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield settings
    get_settings.cache_clear()


def stored_users(settings) -> list[dict]:
    engine = sync_engine(settings)
    try:
        with engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(select(tables.users))]
    finally:
        engine.dispose()


def stored_admin(settings) -> dict:
    [user] = [u for u in stored_users(settings) if u["username"] == "admin"]
    return user


def run(monkeypatch, command="first-admin") -> int:
    monkeypatch.setattr("sys.argv", ["app.cli", command])
    get_settings.cache_clear()
    return cli.main()


def test_creates_admin_admin1234_that_must_be_changed(monkeypatch, dev_env, capsys):
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    assert "admin / admin1234" in capsys.readouterr().out
    user = stored_admin(dev_env)
    assert user["role"] == "ADMIN" and user["must_change_password"] is True
    assert "admin1234" not in str(user)                                  # only the argon2 hash is stored


def test_does_nothing_when_accounts_exist(monkeypatch, dev_env, capsys):
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    before = stored_admin(dev_env)["password_hash"]
    assert run(monkeypatch) == 0
    assert "nothing changed" in capsys.readouterr().out
    users = stored_users(dev_env)
    assert len(users) == 1 and users[0]["password_hash"] == before


def test_works_in_production_as_started_by_production_ps1(monkeypatch, dev_env, capsys):
    # SQL Server on this PC with Windows authentication (the service account), as production.ps1 sets it up.
    for key, value in {"CG_ENVIRONMENT": "production", "CG_DEPLOYMENT_MODE": "http-lan"}.items():
        monkeypatch.setenv(key, value)
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    assert "admin / admin1234" in capsys.readouterr().out
    user = stored_admin(dev_env)
    assert user["role"] == "ADMIN" and user["must_change_password"] is True


def test_password_from_the_environment_is_used_and_not_printed(monkeypatch, dev_env, capsys):
    monkeypatch.setenv("CG_FIRST_ADMIN_PASSWORD", "Gate-First-Run-7")
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    out = capsys.readouterr().out
    assert "Gate-First-Run-7" not in out and "CG_FIRST_ADMIN_PASSWORD" in out
    from app.core.security import verify_password
    user = stored_admin(dev_env)
    assert user["must_change_password"] is True
    assert verify_password("Gate-First-Run-7", user["password_hash"])


def test_blank_environment_password_falls_back_to_the_default(monkeypatch, dev_env):
    monkeypatch.setenv("CG_FIRST_ADMIN_PASSWORD", "  ")
    assert get_settings().first_admin_password.get_secret_value() == "admin1234"


def test_old_command_name_still_works(monkeypatch, dev_env):
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch, "dev-first-admin") == 0
    assert len(stored_users(dev_env)) == 1


def test_first_login_forces_a_proper_new_password(monkeypatch, dev_env):
    import asyncio

    import httpx
    assert run(monkeypatch, "migrate") == 0
    assert run(monkeypatch) == 0
    change = "/api/v1/auth/change-password"

    async def first_login():
        app = create_app(make_settings(environment="development", **same_database(dev_env)))
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
