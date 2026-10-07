import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import make_settings


@pytest.mark.parametrize("name", ["century_gate_system", "Century_Gate_System", " century_gate_system "])
def test_legacy_desktop_database_is_refused(name):
    with pytest.raises(ValidationError, match="legacy desktop database"):
        make_settings(mongo_db=name)


@pytest.mark.parametrize("name", ["", "bad/name", "bad.name", "has space"])
def test_invalid_database_names_are_refused(name):
    with pytest.raises(ValidationError):
        make_settings(mongo_db=name)


def test_default_database_is_the_new_one():
    assert Settings(_env_file=None).mongo_db == "century_gate_vms"


def test_unknown_timezone_is_refused():
    with pytest.raises(ValidationError, match="time zone"):
        make_settings(timezone="Mars/Olympus")


def test_organisation_timezone_default():
    assert Settings(_env_file=None).timezone == "Asia/Karachi"


def test_mongo_uri_is_never_shown_in_repr():
    s = make_settings(mongo_uri="mongodb://app:Db-Secret-1@db.internal:27017/?replicaSet=rs0")
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


# ---------------------------------------------------------------- production database connection (Phase 7A)
SECURE = "mongodb://cgvms_app:App-Pass-1@localhost:27018/?replicaSet=cgvms&tls=true&tlsCAFile=C:/vms/ca.pem"


def test_a_secure_production_connection_is_accepted():
    assert make_settings(environment="production", mongo_uri=SECURE).environment == "production"


@pytest.mark.parametrize("uri,message", [
    ("mongodb://localhost:27018/?replicaSet=cgvms&tls=true&tlsCAFile=ca.pem", "user and password"),
    ("mongodb://cgvms_app:App-Pass-1@localhost:27018/?replicaSet=cgvms", "must use TLS"),
    ("mongodb://cgvms_app:App-Pass-1@localhost:27018/?tls=false", "must use TLS"),
    (SECURE + "&tlsAllowInvalidCertificates=true", "tlsAllowInvalidCertificates"),
    (SECURE + "&tlsAllowInvalidHostnames=true", "tlsAllowInvalidHostnames"),
    (SECURE + "&tlsInsecure=true", "tlsInsecure"),
    ("not a uri", "not a valid MongoDB connection string"),
])
def test_an_insecure_production_connection_is_refused(uri, message):
    with pytest.raises(ValidationError, match=message) as error:
        make_settings(environment="production", mongo_uri=uri)
    assert "App-Pass-1" not in str(error.value).split("input_value")[0]     # the message never names the password


@pytest.mark.parametrize("uri", ["mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev",
                                 "mongodb://localhost:27018/?replicaSet=cgvms-dev"])
def test_production_accepts_a_local_database_without_login_only_when_allowed(uri):
    with pytest.raises(ValidationError, match="user and password"):
        make_settings(environment="production", mongo_uri=uri)
    s = make_settings(environment="production", mongo_uri=uri, mongo_localhost_without_login=True)
    assert s.environment == "production" and s.cookie_secure is True


@pytest.mark.parametrize("uri", ["mongodb://192.168.0.7:27018/?replicaSet=cgvms-dev",
                                 "mongodb://127.0.0.1:27018,db2.example.com:27018/?replicaSet=x",
                                 "mongodb+srv://cluster.example.com/"])
def test_the_no_login_exception_never_covers_another_machine(uri):
    with pytest.raises(ValidationError):
        make_settings(environment="production", mongo_uri=uri, mongo_localhost_without_login=True)


def test_development_keeps_the_local_unauthenticated_database():
    assert make_settings(environment="development").mongo_uri.get_secret_value().startswith("mongodb://127.0.0.1")
