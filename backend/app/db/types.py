"""
Database-neutral names for what services hand to repositories, so that no service imports the driver.

- Db:        the database handle (Database.db), the first argument of every repository function;
- DbSession: the open transaction inside run_in_transaction(), passed on as `session=`;
- RecordId:  a record's ID (repositories/ids.py parses and recognises them).

Today they are the MongoDB types. The SQL Server cut-over changes them here, together with the
repositories; the services stay as they are.
"""
from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

Db = AsyncDatabase
DbSession = AsyncClientSession
RecordId = ObjectId
