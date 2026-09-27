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
