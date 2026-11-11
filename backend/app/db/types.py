"""
Database-neutral names for what services hand to repositories, so that no service imports the driver.

- Db:        the database handle (Database.db), the first argument of every repository function;
- DbSession: the open transaction inside run_in_transaction(), passed on as `session=`;
- RecordId:  a record's ID (repositories/ids.py parses and recognises them).

They are the types of the backend this process uses (CG_DB_BACKEND, app/db/backend.py).
"""
from app.db.backend import BACKEND

if BACKEND == "mssql":
    import uuid

    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.db.sql.database import SqlDb

    Db = SqlDb
    DbSession = AsyncConnection
    RecordId = uuid.UUID
else:
    from bson import ObjectId
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.asynchronous.database import AsyncDatabase

    Db = AsyncDatabase
    DbSession = AsyncClientSession
    RecordId = ObjectId
