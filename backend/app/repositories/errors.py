"""SQL Server: driver errors in database-neutral terms (see app/repositories/errors.py)."""
from collections.abc import Iterator
from contextlib import contextmanager

import pyodbc
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.errors import DuplicateKey
from app.db.sql.errors import is_duplicate_key

# Every error the database layer can raise. Services that must survive a database failure catch this
# tuple (the original exception, unwrapped: SQL Server messages can quote the duplicated value, e.g. an
# ID number, so callers log only the type name).
DATABASE_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, pyodbc.Error)


@contextmanager
def duplicates_as_domain_error() -> Iterator[None]:
    """Wrap a write: a unique-constraint violation becomes DuplicateKey. Other integrity errors (a foreign
    key, a CHECK) stay as they are: they are bugs, not "already exists". The driver message is not
    copied; it stays only on the chained cause."""
    try:
        yield
    except IntegrityError as exc:
        if is_duplicate_key(exc):
            raise DuplicateKey("unique constraint violated") from exc
        raise
