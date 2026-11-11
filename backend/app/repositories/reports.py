"""Repository: reports. The functions of the backend this process uses (CG_DB_BACKEND; see _backend.py)."""
from app.repositories._backend import load
from app.repositories.report_types import GuardGroups, OverviewCounts  # noqa: F401 - shared by every backend

globals().update(load(__name__))
