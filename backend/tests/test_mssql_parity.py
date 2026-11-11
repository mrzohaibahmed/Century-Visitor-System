"""
Every repository area marked as ported has a SQL Server version of EVERY function its MongoDB version has,
with the same parameters (names, kinds, defaults), so services can call either without noticing. A function
missing on SQL Server would otherwise only show up as NotPortedYet in the middle of some request.
"""
import inspect
from importlib import import_module

import pytest

from app.repositories._backend import own_public_names

# Areas whose SQL Server module is complete. Grows with each step of the move (4b: auth and accounts,
# 4c: directory, 4d: visitors, photos, watchlist, 4e: visits, 4f: notifications, entry denials, settings,
# 4h: reports). With reports every area is ported.
PORTED = ["audit_logs", "directory", "entry_denials", "errors", "gates", "ids", "notifications", "photos",
          "rate_limits", "reports", "sessions", "settings", "users", "visitors", "visits", "watchlist"]


def _functions(module) -> dict:
    return {name: value for name, value in own_public_names(module).items() if inspect.isfunction(value)}


def _parameters(function) -> list[tuple]:
    return [(p.name, p.kind, p.default) for p in inspect.signature(function).parameters.values()]


@pytest.mark.parametrize("area", PORTED)
def test_the_sql_server_module_has_every_function_with_the_same_parameters(area):
    mongo = _functions(import_module(f"app.repositories.mongo.{area}"))
    sql = _functions(import_module(f"app.repositories.mssql.{area}"))
    assert sorted(set(mongo) - set(sql)) == []
    different = {name: (_parameters(mongo[name]), _parameters(sql[name])) for name in mongo
                 if _parameters(mongo[name]) != _parameters(sql[name])}
    assert different == {}
    for name in mongo:                   # an async function stays async, a plain one plain
        assert inspect.iscoroutinefunction(mongo[name]) == inspect.iscoroutinefunction(sql[name]), name
        assert inspect.isasyncgenfunction(mongo[name]) == inspect.isasyncgenfunction(sql[name]), name
