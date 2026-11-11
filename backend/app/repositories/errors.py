"""Database errors in database-neutral terms. DuplicateKey is shared by every backend; DATABASE_ERRORS and
duplicates_as_domain_error() are those of the backend this process uses (CG_DB_BACKEND; see _backend.py)."""
from app.db.errors import DuplicateKey  # noqa: F401 - the same class for every backend (services catch it)
from app.repositories._backend import load

globals().update(load(__name__))
