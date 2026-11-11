"""MongoDB: driver errors in database-neutral terms (see app/repositories/errors.py)."""
from collections.abc import Iterator
from contextlib import contextmanager

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.db.errors import DuplicateKey

# Every error the database driver can raise. Services that must survive a database failure catch this
# tuple (the original exception, unwrapped: its message can quote document values, so callers log only
# its type name).
DATABASE_ERRORS: tuple[type[Exception], ...] = (PyMongoError,)


@contextmanager
def duplicates_as_domain_error() -> Iterator[None]:
    """Wrap a write: the driver's duplicate-key error becomes DuplicateKey. The driver message (which can
    quote the duplicated value) is not copied; it stays only on the chained cause."""
    try:
        yield
    except DuplicateKeyError as exc:
        raise DuplicateKey("unique constraint violated") from exc
