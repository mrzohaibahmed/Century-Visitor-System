"""
Loads a repository area (users, visits, ...) from the backend this process uses (app.db.backend.BACKEND).

- CG_DB_BACKEND=mongo (default): app/repositories/mongo/<area>.py, exactly as before.
- CG_DB_BACKEND=mssql: app/repositories/mssql/<area>.py. While SQL Server is being built area by area,
  a function that has no SQL Server version yet still exists but raises NotPortedYet when called, so the
  app starts and every finished area can be tested on SQL Server. An area's classes and constants are
  taken from the MongoDB module until its SQL Server module defines its own.

Temporary scaffolding: after the cut-over, mongo/ and this loader are removed and the SQL Server modules
become the repositories.
"""
import inspect
from importlib import import_module
from types import ModuleType

from app.db.backend import BACKEND


class NotPortedYet(NotImplementedError):
    """This repository function has no SQL Server version yet (CG_DB_BACKEND=mssql)."""


def own_public_names(module: ModuleType) -> dict[str, object]:
    """The public names `module` itself defines (functions, classes, constants), not what it imports."""
    names = {}
    for name, value in vars(module).items():
        if name.startswith("_") or inspect.ismodule(value):
            continue
        if getattr(value, "__module__", module.__name__) == module.__name__:
            names[name] = value
    return names


def _not_ported(area: str, name: str, original) -> object:
    def not_ported(*args, **kwargs):
        raise NotPortedYet(f"repositories.{area}.{name} has no SQL Server version yet")
    not_ported.__name__ = not_ported.__qualname__ = name
    not_ported.__doc__ = original.__doc__
    return not_ported


def _optional_module(name: str) -> ModuleType | None:
    try:
        return import_module(name)
    except ModuleNotFoundError as e:
        if e.name != name:                 # the module exists but something it imports is missing
            raise
        return None


def load(facade_module: str) -> dict[str, object]:
    """The public names of the configured backend's version of this façade's area."""
    area = facade_module.rsplit(".", 1)[1]
    mongo = own_public_names(import_module(f"app.repositories.mongo.{area}"))
    if BACKEND == "mongo":
        return mongo
    sql_module = _optional_module(f"app.repositories.mssql.{area}")
    sql = own_public_names(sql_module) if sql_module else {}
    names: dict[str, object] = {}
    for name, value in mongo.items():
        if name in sql:
            names[name] = sql[name]
        elif inspect.isfunction(value):
            names[name] = _not_ported(area, name, value)
        else:
            names[name] = value
    return names | {name: value for name, value in sql.items() if name not in names}
