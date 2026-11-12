"""The database for the app's lifetime: SQL Server (app/db/sql/database.py), opened in the FastAPI lifespan
and by the operator commands (app/cli.py). Routes receive it as `Database` (app/api/deps.py)."""
from app.core.config import Settings
from app.db.sql.database import SqlDatabase as Database

__all__ = ["Database", "open_database"]


def open_database(settings: Settings) -> Database:
    return Database(settings)
