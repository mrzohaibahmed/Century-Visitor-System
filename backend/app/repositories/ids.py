"""Repository: ids. The functions of the backend this process uses (CG_DB_BACKEND; see _backend.py)."""
from app.repositories._backend import load

globals().update(load(__name__))
