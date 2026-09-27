"""
Local development MongoDB for the Century Gate VMS web application.

Starts a SEPARATE mongod process on 127.0.0.1:27018 as a single-node replica
set (transactions need a replica set), with its data in .dev/mongo/ inside this
repository. It never connects to, reconfigures or restarts the MongoDB Windows
service on port 27017, which holds the legacy desktop database.

Run with the API virtual environment (it provides pymongo):

    backend\\.venv\\Scripts\\python scripts\\dev_mongo.py start
    backend\\.venv\\Scripts\\python scripts\\dev_mongo.py status
    backend\\.venv\\Scripts\\python scripts\\dev_mongo.py stop

Set CG_MONGOD to the full path of mongod.exe if it is not found automatically.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ConnectionFailure, OperationFailure

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / ".dev" / "mongo"
DATA_DIR = BASE_DIR / "data"
LOG_FILE = BASE_DIR / "mongod.log"
HOST = "127.0.0.1"
PORT = int(os.environ.get("CG_DEV_MONGO_PORT", "27018"))
REPLICA_SET = "cgvms-dev"
LEGACY_PORT = 27017


def _version_key(path: str):
    match = re.search(r"Server[\\/](\d+)\.(\d+)", path)
    return tuple(int(x) for x in match.groups()) if match else (0, 0)


def find_mongod() -> str:
    explicit = os.environ.get("CG_MONGOD")
    if explicit:
        return explicit
    candidates = glob.glob(r"C:\Program Files\MongoDB\Server\*\bin\mongod.exe")
    if candidates:
        return max(candidates, key=_version_key)
    found = shutil.which("mongod")
    if found:
        return found
    sys.exit("mongod not found. Install MongoDB Community Server or set CG_MONGOD.")


def client() -> MongoClient:
    return MongoClient(host=HOST, port=PORT, directConnection=True, serverSelectionTimeoutMS=1500)


def is_running() -> bool:
    try:
        client().admin.command("ping")
        return True
    except ConnectionFailure:
        return False


def ensure_replica_set():
    c = client()
    try:
        c.admin.command("replSetGetStatus")
    except OperationFailure as e:
        if e.code != 94:  # NotYetInitialized
            raise
        c.admin.command("replSetInitiate", {"_id": REPLICA_SET, "members": [{"_id": 0, "host": f"{HOST}:{PORT}"}]})
        print(f"Initialised replica set '{REPLICA_SET}'.")
    for _ in range(60):
        if c.admin.command("hello").get("isWritablePrimary"):
            return
        time.sleep(0.5)
    sys.exit("Replica set did not elect a primary in time; see " + str(LOG_FILE))


def start():
    if PORT == LEGACY_PORT:
        sys.exit("Refusing to use port 27017: that is the legacy desktop MongoDB service.")
    if not is_running():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        mongod = find_mongod()
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(  # noqa: S603 - fixed arguments, local mongod binary
            [mongod, "--dbpath", str(DATA_DIR), "--port", str(PORT), "--bind_ip", HOST,
             "--replSet", REPLICA_SET, "--logpath", str(LOG_FILE), "--logappend"],
            creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        for _ in range(60):
            if is_running():
                break
            time.sleep(0.5)
        else:
            sys.exit("mongod did not start; see " + str(LOG_FILE))
        print(f"Started mongod ({mongod}) on {HOST}:{PORT}.")
    ensure_replica_set()
    print(f"Ready: mongodb://{HOST}:{PORT}/?replicaSet={REPLICA_SET}")


def stop():
    if not is_running():
        print("Not running.")
        return
    try:
        client().admin.command("shutdown")
    except (AutoReconnect, ConnectionFailure):
        pass
    print("Stopped.")


def status():
    if not is_running():
        print(f"Not running (expected on {HOST}:{PORT}).")
        return
    hello = client().admin.command("hello")
    print(f"Running on {HOST}:{PORT}; replica set={hello.get('setName')!r}; primary={hello.get('isWritablePrimary')}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"start": start, "stop": stop, "status": status}.get(command, lambda: sys.exit(__doc__))()
