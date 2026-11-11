"""
Watchlist screening on SQL Server matches exactly the entries the MongoDB regex matched.

MongoDB: identifier in the exact list, OR identifier ~ ^OTHER:<c1>[ /-]*<c2>[ /-]*...<cn>$ (case-sensitive).
SQL Server has no regex: repositories/mssql/watchlist.find_active_match() writes the rule out. Here both
are evaluated for many tricky identifiers and must agree on every one.
"""
import re
from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.mssql import users as sql_users
from app.repositories.mssql import watchlist as sql_watchlist
from app.repositories.mssql.connection import connection
from app.repositories.mssql.ids import new_id
from app.repositories.mssql.tables import watchlist as watchlist_table

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)

STORED = [
    "OTHER:AB12", "OTHER:AB 12", "OTHER:A/B-1 2", "OTHER:A B / 1 - 2", "OTHER:AB12-", "OTHER:-AB12",
    "OTHER: AB12", "OTHER:AB12 ", "OTHER:AB1", "OTHER:AB123", "OTHER:ab12", "OTHER:Ab12", "OTHER:A_B12",
    "OTHER:A%B12", "OTHER:ABÉ12", "CNIC:AB12", "PASSPORT:AB12", "OTHER:AB12X", "XOTHER:AB12",
    "OTHER:AB12  ", "OTHER:AB12\U0001F600", "CNIC:AB12 ",
]
SEARCHES = ["AB12", "AB1", "AB123", "A", "B12", "AB1 2", "ab12", "AB12\U0001F600"]


def mongo_matches(identifier: str, identifiers: list[str], compact: str) -> bool:
    """The MongoDB query of mongo/watchlist.find_active_match, evaluated in Python."""
    if identifier in identifiers:
        return True
    return bool(compact) and re.match("^OTHER:" + "[ /-]*".join(compact) + "$", identifier) is not None


async def add_entries(db, creator) -> None:
    async with connection(db) as conn:
        for n, identifier in enumerate(STORED):
            await conn.execute(watchlist_table.insert(), {
                "id": new_id(),
                "identifier": identifier, "identity_type": "OTHER", "identity_number": f"N{n}", "reason": "Test.",
                "is_active": False, "created_by": creator, "created_at": NOW})


async def test_other_numbers_match_exactly_as_the_mongodb_regex(sql_database):
    db = sql_database.db
    creator = await sql_users.insert(db, {"username": "admin", "password_hash": "x", "role": "ADMIN",
                                          "is_active": True, "must_change_password": False, "failed_login_count": 0,
                                          "created_at": NOW, "updated_at": NOW})
    await add_entries(db, creator)
    disagreements = []
    for identifier in STORED:
        async with connection(db) as conn:          # only this entry active: is it the match?
            await conn.execute(watchlist_table.update().values(is_active=False))
            await conn.execute(watchlist_table.update().where(watchlist_table.c.identifier == identifier)
                               .where(watchlist_table.c.identity_number == f"N{STORED.index(identifier)}")
                               .values(is_active=True))
        for search in SEARCHES:
            compact = re.sub(r"[^0-9A-Za-z]", "", search)       # (lower case only to prove the match is exact)
            exact = [f"OTHER:{search}", f"CNIC:{search}"]
            found = await sql_watchlist.find_active_match(db, exact, compact or None, NOW)
            expected = mongo_matches(identifier, exact, compact)
            if (found is not None) != expected:
                disagreements.append((identifier, search, "sql" if found else "mongo"))
    assert disagreements == []


async def test_expired_and_inactive_entries_never_match(sql_database):
    db = sql_database.db
    creator = await sql_users.insert(db, {"username": "admin", "password_hash": "x", "role": "ADMIN",
                                          "is_active": True, "must_change_password": False, "failed_login_count": 0,
                                          "created_at": NOW, "updated_at": NOW})
    for identifier, active, expires in (("OTHER:AB12", True, NOW - timedelta(seconds=1)),
                                        ("OTHER:AB 12", False, None)):
        identity = {"type": "OTHER", "number": identifier[6:]}
        await sql_watchlist.insert(db, {"identifier": identifier, "identity": identity,
                                        "reason": "Test.", "is_active": active, "expires_at": expires,
                                        "created_by": creator, "created_at": NOW})
    assert await sql_watchlist.find_active_match(db, ["OTHER:AB12"], "AB12", NOW) is None
    later_ban = {"identifier": "OTHER:A-B12", "identity": {"type": "OTHER", "number": "A-B12"}, "reason": "Test.",
                 "is_active": True, "expires_at": NOW + timedelta(days=1), "created_by": creator, "created_at": NOW}
    await sql_watchlist.insert(db, later_ban)
    found = await sql_watchlist.find_active_match(db, ["OTHER:AB12"], "AB12", NOW)
    assert found["_id"] == later_ban["_id"] and found["identity"] == {"type": "OTHER", "number": "A-B12"}
    assert "identifier_compact" not in found
