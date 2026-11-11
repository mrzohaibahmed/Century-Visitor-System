"""Repository: visits. The functions of the backend this process uses (CG_DB_BACKEND; see _backend.py)."""
from app.repositories._backend import load
from app.repositories.visit_filter import VisitFilter  # noqa: F401 - the same class for every backend

globals().update(load(__name__))
