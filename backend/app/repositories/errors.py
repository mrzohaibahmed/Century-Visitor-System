"""Database-neutral errors raised by repositories, so services never catch driver exceptions."""
from collections.abc import Iterator
from contextlib import contextmanager

from pymongo.errors import DuplicateKeyError


class DuplicateKey(Exception):
    """A write broke a unique constraint (e.g. a name or username that already exists)."""


@contextmanager
def duplicates_as_domain_error() -> Iterator[None]:
    """Wrap a write: the driver's duplicate-key error becomes DuplicateKey."""
    try:
        yield
    except DuplicateKeyError as exc:
        raise DuplicateKey(str(exc)) from exc
