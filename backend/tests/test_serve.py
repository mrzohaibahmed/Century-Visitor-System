"""The production server entry point (python -m app.serve)."""
import pytest

from app import serve


@pytest.fixture
def ran(monkeypatch):
    calls = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda **kw: calls.append(kw))
    return calls


def production_env(monkeypatch, tmp_path, **extra):
    # SQL Server on this PC with Windows authentication: a valid production database setting.
    env = {"CG_ENVIRONMENT": "production", "CG_MSSQL_SERVER": ".\\SQLEXPRESS", "CG_PHOTO_DIR": str(tmp_path)}
    for key, value in {**env, **extra}.items():
        monkeypatch.setenv(key, value)


def test_production_server_settings(monkeypatch, tmp_path, ran):
    production_env(monkeypatch, tmp_path)
    assert serve.main([]) == 0
    options = ran[0]
    assert options["host"] == "127.0.0.1" and options["port"] == 8000 and options["workers"] == 1
    assert options["reload"] is False and options["server_header"] is False and options["proxy_headers"] is False
    assert options["factory"] is True and options["app"] == "app.main:create_app"


def test_refuses_to_run_with_development_settings(monkeypatch, tmp_path, ran, capsys):
    production_env(monkeypatch, tmp_path, CG_ENVIRONMENT="development")
    assert serve.main([]) == 2 and ran == []
    assert "CG_ENVIRONMENT=production" in capsys.readouterr().err


def test_an_invalid_configuration_stops_the_start_without_showing_secrets(monkeypatch, tmp_path, ran, capsys):
    production_env(monkeypatch, tmp_path, CG_MSSQL_SERVER="db.example.com", CG_MSSQL_TRUST_SERVER_CERTIFICATE="true",
                   CG_MSSQL_USERNAME="cgvms_app", CG_MSSQL_PASSWORD="Leak-Me-1")
    assert serve.main([]) == 2 and ran == []
    err = capsys.readouterr().err
    assert "only allowed for a SQL Server instance on this PC" in err and "Leak-Me-1" not in err


def test_insecure_cookies_are_refused_in_production(monkeypatch, tmp_path, ran, capsys):
    production_env(monkeypatch, tmp_path, CG_COOKIE_SECURE="false")
    assert serve.main([]) == 2 and "cookie_secure" in capsys.readouterr().err


def test_the_cli_reports_configuration_problems_without_secrets(monkeypatch, tmp_path, capsys):
    from app import cli
    from app.core.config import get_settings
    production_env(monkeypatch, tmp_path, CG_MSSQL_SERVER="db.example.com", CG_MSSQL_TRUST_SERVER_CERTIFICATE="true",
                   CG_MSSQL_USERNAME="cgvms_app", CG_MSSQL_PASSWORD="Leak-Me-2")
    monkeypatch.setattr("sys.argv", ["app.cli", "check"])
    get_settings.cache_clear()
    try:
        assert cli.main() == 2
    finally:
        get_settings.cache_clear()
    err = capsys.readouterr().err
    assert "only allowed for a SQL Server instance on this PC" in err and "Leak-Me-2" not in err
    assert "Traceback" not in err
