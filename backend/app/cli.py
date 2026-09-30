"""
Operator commands (run on the server, never exposed over HTTP):

    python -m app.cli migrate    create/update collections, validators and indexes
    python -m app.cli check      same checks as GET /api/v1/health/ready
    python -m app.cli create-admin --username admin [--display-name "..."] [--password-stdin]
    python -m app.cli verify-data     read-only: photo files present and unchanged, links intact (exit 1 if not)
    python -m app.cli restore-check   on a RESTORED COPY only: verify-data + access rules (refuses production)
    python -m app.cli dev-first-admin DEVELOPMENT only: admin / admin1234 when no account exists yet
                                      (must be changed at the first login; start-dev.bat runs it)
    python -m app.cli generate-secrets-key   prints a new key for CG_SECRETS_KEY (nothing is changed)
    python -m app.cli backfill-entry-denials creates the missing entry_denials documents from WATCHLIST_MATCH
                                      audit entries; repeatable and safe to run concurrently (also repairs
                                      a denial whose reporting write failed at the gate)

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

from pydantic import ValidationError
from pymongo.errors import OperationFailure

from app.core.config import configuration_problems, get_settings
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
    except OperationFailure as e:
        if e.code != 13:                                   # 13 = Unauthorized
            raise
        print("ERROR: this database account may not change the schema. In production run migrations with the "
              r"cgvms_migrate account (deploy\windows\migrate.ps1), not the application's account.", file=sys.stderr)
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


async def _verify_data() -> int:
    from app.ops import verify_data
    settings = get_settings()
    database = Database(settings)
    try:
        report = await verify_data(database.db, settings)
    finally:
        await database.close()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


async def _restore_check() -> int:
    from app.ops import restore_check
    try:
        report = await restore_check(get_settings())
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


async def _backfill_entry_denials() -> int:
    from app.services.entry_denials import backfill_from_audit
    settings = get_settings()
    database = Database(settings)
    try:
        report = await backfill_from_audit(database.db)
    finally:
        await database.close()
    print(json.dumps({"database": settings.mongo_db, **report.as_dict()}, indent=2))
    return 1 if report.failed else 0


DEV_ADMIN_USERNAME = "admin"
DEV_ADMIN_PASSWORD = "admin1234"         # noqa: S105 - documented development default, changed at first login


async def _dev_first_admin() -> int:
    from app.core.permissions import Role
    from app.services.users import create_user
    settings = get_settings()
    if settings.environment != "development":
        print("ERROR: dev-first-admin only works with CG_ENVIRONMENT=development. "
              "Use create-admin (with your own password) for any other database.", file=sys.stderr)
        return 2
    database = Database(settings)
    try:
        if await database.db.users.estimated_document_count():
            print("Accounts already exist: nothing changed.")
            return 0
        await create_user(database.db, actor=None, meta=None, username=DEV_ADMIN_USERNAME,
                          display_name="Administrator", role=Role.ADMIN, password=DEV_ADMIN_PASSWORD,
                          must_change_password=True, enforce_policy=False, source="dev-first-admin")
    finally:
        await database.close()
    print(f"First administrator created: {DEV_ADMIN_USERNAME} / {DEV_ADMIN_PASSWORD} "
          "(a new password must be chosen at the first login).")
    return 0


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
    sub.add_parser("verify-data", help="read-only integrity check of the database and the photo folder")
    sub.add_parser("restore-check", help="checks a restored copy (never production)")
    sub.add_parser("dev-first-admin", help="development only: admin / admin1234 if no account exists")
    sub.add_parser("generate-secrets-key", help="print a new random key for CG_SECRETS_KEY")
    sub.add_parser("backfill-entry-denials",
                   help="create missing entry_denials from WATCHLIST_MATCH audit entries (repeatable)")
    admin = sub.add_parser("create-admin", help="create an administrator account")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="Administrator")
    admin.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    args = parser.parse_args()
    if args.command == "generate-secrets-key":            # needs no configuration: it may be the first step
        from app.core.secrets import generate_key
        print(generate_key())
        return 0
    try:
        configure_logging(get_settings().log_level)
    except ValidationError as e:
        print(f"ERROR: configuration is not valid: {configuration_problems(e)}", file=sys.stderr)
        return 2

    if args.command == "create-admin":
        from pydantic import TypeAdapter

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
    commands = {"migrate": _migrate, "check": _check, "verify-data": _verify_data, "restore-check": _restore_check,
                "dev-first-admin": _dev_first_admin, "backfill-entry-denials": _backfill_entry_denials}
    return asyncio.run(commands[args.command]())


if __name__ == "__main__":
    sys.exit(main())
