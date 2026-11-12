"""
Names for what services hand to repositories, so that no service imports the driver.

- Db:        the database handle (Database.db), the first argument of every repository function;
- DbSession: the open transaction inside run_in_transaction(), passed on as `session=`;
- RecordId:  a record's ID (repositories/ids.py makes, parses and recognises them).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb

Db = SqlDb
DbSession = AsyncConnection
RecordId = uuid.UUID
