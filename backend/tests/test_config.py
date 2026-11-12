import pytest
from pydantic import ValidationError

from app.core.config import Settings, mssql_server_is_local
from tests.conftest import make_settings


@pytest.mark.parametrize("name", ["century_gate_system", "Century_Gate_System", " century_gate_system "])
def test_legacy_desktop_database_is_refused(name):
    with pytest.raises(ValidationError, match="legacy desktop database"):
        make_settings(mssql_database=name)


@pytest.mark.parametrize("name", ["", "bad/name", "bad.name", "has space", "x]; DROP DATABASE y", "1starts_with_digit",
                                  "a" * 101])
def test_invalid_database_names_are_refused(name):
    with pytest.raises(ValidationError, match="Invalid SQL Server database name"):
        make_settings(mssql_database=name)


def test_default_database_is_the_new_one():
    s = Settings(_env_file=None)
    assert (s.mssql_server, s.mssql_database) == (".\\SQLEXPRESS", "century_gate_vms")
    assert s.mssql_username is None and s.mssql_trust_server_certificate is False      # Windows login, TLS checked


def test_unknown_timezone_is_refused():
    with pytest.raises(ValidationError, match="time zone"):
        make_settings(timezone="Mars/Olympus")


def test_organisation_timezone_default():
    assert Settings(_env_file=None).timezone == "Asia/Karachi"


def test_the_database_password_is_never_shown_in_repr():
    s = make_settings(mssql_username="cgvms_app", mssql_password="Db-Secret-1")
    assert "Db-Secret-1" not in repr(s) and "Db-Secret-1" not in str(s.model_dump())


@pytest.mark.parametrize("environment,expected", [("development", True), ("test", False), ("production", False)])
def test_api_docs_only_in_development_by_default(environment, expected):
    assert make_settings(environment=environment).docs_enabled is expected


def test_api_docs_can_be_forced():
    assert make_settings(environment="production", api_docs=True).docs_enabled is True


def test_production_requires_an_explicit_photo_folder():
    with pytest.raises(ValidationError, match="CG_PHOTO_DIR"):
        Settings(_env_file=None, environment="production")
    assert make_settings(environment="production").photo_dir          # set explicitly (as the tests do)


def test_phase_4_defaults():
    s = Settings(_env_file=None)
    assert s.photo_max_bytes == 2 * 1024 * 1024
    assert s.pass_day_end_hour == 16 and s.pass_day_end_minute == 30
    assert s.overstay_poll_seconds == 60
    assert s.photo_dir.name == "photos" and "web" not in s.photo_dir.parts


# ---------------------------------------------------------------- database connection
@pytest.mark.parametrize("username,password", [("cgvms_app", None), ("cgvms_app", ""), (None, "App-Pass-1")])
def test_a_sql_login_needs_both_its_name_and_password(username, password):
    with pytest.raises(ValidationError, match="CG_MSSQL_USERNAME and CG_MSSQL_PASSWORD") as error:
        make_settings(mssql_username=username, mssql_password=password)
    assert "App-Pass-1" not in str(error.value).split("input_value")[0]     # the message never names the password


@pytest.mark.parametrize("server,local", [
    (".", True), (".\\SQLEXPRESS", True), ("(local)\\VMS", True), ("localhost", True), ("LOCALHOST,1433", True),
    ("127.0.0.1", True), ("::1", True), (" .\\SQLEXPRESS ", True),
    ("db.example.com", False), ("192.168.0.7\\SQLEXPRESS", False), ("localhost.example.com", False),
    ("SERVER01", False), ("tcp:localhost", False),
])
def test_which_servers_are_on_this_pc(server, local):
    assert mssql_server_is_local(server) is local


@pytest.mark.parametrize("environment", ["development", "production"])
def test_skipping_the_certificate_check_is_only_for_an_instance_on_this_pc(environment):
    assert make_settings(environment=environment, mssql_server=".\\SQLEXPRESS",
                         mssql_trust_server_certificate=True).mssql_trust_server_certificate
    with pytest.raises(ValidationError, match="only allowed for a SQL Server instance on this PC"):
        make_settings(environment=environment, mssql_server="db.example.com", mssql_trust_server_certificate=True)


def test_production_accepts_windows_authentication_and_a_sql_login():
    assert make_settings(environment="production", mssql_server=".\\SQLEXPRESS").mssql_username is None
    s = make_settings(environment="production", mssql_server="db.example.com", mssql_trust_server_certificate=False,
                      mssql_username="cgvms_app", mssql_password="App-Pass-1")
    assert s.environment == "production" and s.mssql_trust_server_certificate is False
