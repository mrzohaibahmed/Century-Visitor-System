"""
Prepares the end-to-end test database: drops it, migrates it and creates the
first administrator (via the real CLI). Only ever touches databases whose name
starts with "cgvms_e2e", never the development or legacy databases.

Usage (from the backend/ folder, with its virtual environment):
    .venv\\Scripts\\python ..\\scripts\\e2e_reset_db.py
Environment: CG_MONGO_URI, CG_MONGO_DB (must start with cgvms_e2e), E2E_ADMIN_PASSWORD.
"""
import os
import subprocess
import sys

from pymongo import MongoClient

db_name = os.environ.get("CG_MONGO_DB", "")
if not db_name.startswith("cgvms_e2e"):
    sys.exit(f"Refusing to reset '{db_name}': only cgvms_e2e* databases are reset by this script.")

MongoClient(os.environ["CG_MONGO_URI"]).drop_database(db_name)
subprocess.run([sys.executable, "-m", "app.cli", "migrate"], check=True, stdout=subprocess.DEVNULL)
subprocess.run([sys.executable, "-m", "app.cli", "create-admin", "--username", "admin",
                "--display-name", "E2E Administrator", "--password-stdin"],
               input=os.environ["E2E_ADMIN_PASSWORD"] + "\n", text=True, check=True, stdout=subprocess.DEVNULL)
print(f"E2E database {db_name} ready")
