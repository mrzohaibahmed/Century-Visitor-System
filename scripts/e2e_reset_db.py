"""
Prepares the end-to-end test database on SQL Server: drops it, creates and migrates it, and creates the
first administrator (all through the real CLI except the drop). Only ever touches databases whose name
starts with "cgvms_e2e", never the development, production or legacy databases.

Usage (from the backend/ folder, with its virtual environment):
    .venv\\Scripts\\python ..\\scripts\\e2e_reset_db.py
Environment: CG_MSSQL_SERVER, CG_MSSQL_DATABASE (must start with cgvms_e2e), E2E_ADMIN_PASSWORD.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))     # the app package, below

from sqlalchemy import text

from app.core.config import get_settings
from app.db.sql.engine import sync_engine

settings = get_settings()
db_name = settings.mssql_database
if not db_name.startswith("cgvms_e2e") or db_name != os.environ.get("CG_MSSQL_DATABASE"):
    sys.exit(f"Refusing to reset '{db_name}': only cgvms_e2e* databases named in CG_MSSQL_DATABASE are reset.")

engine = sync_engine(settings, database="master", autocommit=True)
try:
    with engine.connect() as conn:
        if conn.execute(text("SELECT DB_ID(:name)"), {"name": db_name}).scalar() is not None:
            # The name is validated by Settings (letters, digits, _) and checked above: safe unquoted.
            conn.exec_driver_sql(f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            conn.exec_driver_sql(f"DROP DATABASE [{db_name}]")
finally:
    engine.dispose()

for command in ("create-database", "migrate"):
    subprocess.run([sys.executable, "-m", "app.cli", command], check=True, stdout=subprocess.DEVNULL)  # noqa: S603
subprocess.run([sys.executable, "-m", "app.cli", "create-admin", "--username", "admin",
                "--display-name", "E2E Administrator", "--password-stdin"],
               input=os.environ["E2E_ADMIN_PASSWORD"] + "\n", text=True, check=True, stdout=subprocess.DEVNULL)
print(f"E2E database {db_name} ready")
