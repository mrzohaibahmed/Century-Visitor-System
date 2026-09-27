"""
Operator commands (run on the server, never exposed over HTTP):

    python -m app.cli migrate    create/update collections, validators and indexes
    python -m app.cli check      same checks as GET /api/v1/health/ready
    python -m app.cli create-admin --username admin [--display-name "..."] [--password-stdin]

create-admin is the only way to create the first administrator: there is no
web "first-run" page, because such a page would be reachable by anyone on the
network. Whoever can run commands on the server is already trusted.

Later phases add: create-gate, purge-retention.
"""
import argparse
import asyncio
import getpass
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.client import Database
from app.db.migrate import LegacyDatabaseError, apply_schema, current_schema_version
from app.db.schema import SCHEMA_VERSION


async def _migrate() -> int:
    settings = get_settings()
    database = Database(settings)
    try:
        report = await apply_schema(database.db)
    except LegacyDatabaseError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        await database.close()
    print(json.dumps({"database": settings.mongo_db, "schema_version": report.schema_version,
                      "created_collections": report.created_collections,
                      "indexes": report.indexes}, indent=2))
    return 0


async def _check() -> int:
    settings = get_settings()
    database = Database(settings)
    try:
        await database.db.command("ping")
        version = await current_schema_version(database.db)
        hello = await database.db.command("hello")
    finally:
        await database.close()
    ok = version == SCHEMA_VERSION and bool(hello.get("setName"))
    print(json.dumps({"database": settings.mongo_db, "schema_version": version,
                      "expected_schema_version": SCHEMA_VERSION, "replica_set": bool(hello.get("setName")),
                      "ready": ok}, indent=2))
    return 0 if ok else 1


def _read_password(from_stdin: bool, username: str) -> str | None:
    from app.core.security import password_policy_error
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("New administrator password: ")
        if getpass.getpass("Repeat the password: ") != password:
            print("ERROR: the passwords do not match.", file=sys.stderr)
            return None
    problem = password_policy_error(password, username)
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return None
    return password


async def _create_admin(username: str, display_name: str, password: str) -> int:
    from app.core.errors import AppError
    from app.core.permissions import Role
    from app.services.users import create_user
    database = Database(get_settings())
    try:
        user = await create_user(database.db, actor=None, meta=None, username=username, display_name=display_name,
                                 role=Role.ADMIN, password=password, must_change_password=False)
    except AppError as e:
        print(f"ERROR: {e.message}", file=sys.stderr)
        return 2
    finally:
        await database.close()
    print(json.dumps({"created": {"id": str(user["_id"]), "username": username, "role": "ADMIN"}}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="create/update collections, validators and indexes")
    sub.add_parser("check", help="readiness checks")
    admin = sub.add_parser("create-admin", help="create an administrator account")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="Administrator")
    admin.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)

    if args.command == "create-admin":
        from pydantic import TypeAdapter, ValidationError

        from app.schemas.users import DisplayName, Username
        try:
            TypeAdapter(Username).validate_python(args.username)
            TypeAdapter(DisplayName).validate_python(args.display_name)
        except ValidationError:
            print("ERROR: username must be 3-32 characters (letters, digits, . _ -), "
                  "display name 1-80 characters.", file=sys.stderr)
            return 2
        password = _read_password(args.password_stdin, args.username)
        if password is None:
            return 2
        return asyncio.run(_create_admin(args.username.strip(), args.display_name.strip(), password))
    return asyncio.run({"migrate": _migrate, "check": _check}[args.command]())


if __name__ == "__main__":
    sys.exit(main())
