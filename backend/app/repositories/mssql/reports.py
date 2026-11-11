"""
SQL Server access for the reports: the aggregations, returned as plain grouped rows. Same functions as
mongo/reports.py, returning the same rows; merging, naming, sorting and limits stay in services/reports.py.

Two things MongoDB did that SQL Server does differently:
- Local hours and days (Asia/Karachi, or CG_TIMEZONE). MongoDB took an IANA time zone in $hour/$dateTrunc;
  SQL Server only knows Windows zone names. Here the zone's UTC offsets for the report's range come from
  Python's zoneinfo and are applied in SQL (a CASE over the offset changes, if any); local bucket starts go
  back to UTC in Python. Exact for every zone, daylight saving included.
- Text. MongoDB grouped and took maximums byte for byte; SQL Server's columns ignore case. Names are
  grouped and compared with a binary collation, so "Sara" and "sara" stay apart as before.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Float, and_, case, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories.mssql import tables
from app.repositories.mssql.connection import connection
from app.repositories.mssql.rows import with_identity
from app.repositories.mssql.visits import SNAPSHOT
from app.repositories.report_types import GuardGroups, OverviewCounts

visits = tables.visits
denials = tables.entry_denials
BINARY = "Latin1_General_100_BIN2"
ROW_COLUMNS = ("visit_number", "visitor_id", "host_id", "host_unlisted", "department_id", "gate_id", "reason_code",
               "reason_note", "check_in_at", "check_out_at", "status", "checked_in_by", "checked_out_by")
DENIAL_COLUMNS = ("at", "reason", "reason_code", "source", "visitor_id", "visitor_name", "identifier_masked",
                  "watchlist_id", "gate_id", "gate_name", "operator_id", "operator_name", "operator_username")
LOOKUP_TABLES = {"visitors": tables.visitors, "hosts": tables.hosts, "departments": tables.departments,
                 "users": tables.users, "watchlist": tables.watchlist, "gates": tables.gates}

_MS = literal_column("millisecond")
_COMPLETED = and_(visits.c.status == "CHECKED_OUT", visits.c.check_out_at.is_not(None))
_STAY_MS = func.datediff_big(_MS, visits.c.check_in_at, visits.c.check_out_at)
_INSIDE = visits.c.status == "CHECKED_IN"


def _exact_max(column):
    """MAX compared byte for byte (MongoDB's $max on strings)."""
    return func.max(column.collate(BINARY))


def _count_if(condition):
    return func.sum(case((condition, 1), else_=0))


def _checked_in_within(start: datetime, end: datetime):
    return and_(visits.c.check_in_at >= start, visits.c.check_in_at < end)


# ------------------------------------------------------------------------------------------ keyset pages
@dataclass(frozen=True)
class Keyset:
    """The rows that come after (value, last_id) in an order by (field, id): built by after(), turned into a
    condition by the function that runs the query (it knows which column `field` is)."""
    field: str
    direction: int
    value: object
    last_id: UUID
    nullable: bool

    def condition(self, column, id_column):
        later = (lambda a, b: a < b) if self.direction < 0 else (lambda a, b: a > b)
        if self.value is None:                # already among the rows without a value (they come last)
            return and_(column.is_(None), later(id_column, self.last_id))
        clauses = [later(column, self.value), and_(column == self.value, later(id_column, self.last_id))]
        if self.nullable:
            clauses.append(column.is_(None))
        return or_(*clauses)


def after(field: str, direction: int, value, last_id: UUID, nullable: bool) -> Keyset:
    """Keyset condition: the rows that come after (value, last_id) in this order. With `nullable`, rows
    without a value come last."""
    return Keyset(field, direction, value, last_id, nullable)


async def fields_by_id(db: SqlDb, collection: str, ids, fields: tuple[str, ...]) -> dict[UUID, dict]:
    """{id: document with only `fields`} for these ids (others, e.g. None, are ignored), in one query."""
    if collection not in LOOKUP_TABLES:
        raise ValueError(f"not a report lookup collection: {collection}")
    table = LOOKUP_TABLES[collection]
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, UUID)]
    if not ids:
        return {}
    columns = []
    for field in fields:
        columns += [table.c.identity_type, table.c.identity_number] if field == "identity" else [table.c[field]]
    async with connection(db) as conn:
        rows = await conn.execute(select(table.c.id, *columns).where(table.c.id.in_(ids)))
        found = {}
        for row in rows:
            doc = {key: value for key, value in row._mapping.items() if key != "id"} | {"_id": row.id}
            found[row.id] = with_identity(doc) if "identity" in fields else doc
        return found


# ------------------------------------------------------------------------------------------ local time
def _offsets(start: datetime, end: datetime, tz: str) -> list[tuple[datetime | None, int]]:
    """The zone's UTC offset (minutes) over [start, end]: [(until, offset), ..., (None, last offset)]."""
    zone = ZoneInfo(tz)

    def offset(moment: datetime) -> int:
        return int(moment.astimezone(zone).utcoffset().total_seconds() // 60)

    segments, current, moment = [], offset(start), start
    while moment < end:
        step = min(moment + timedelta(hours=1), end)
        if offset(step) != current:
            low, high = moment, step                     # the change is in (low, high]: find the minute
            while high - low > timedelta(minutes=1):
                middle = low + (high - low) / 2
                low, high = (middle, high) if offset(middle) == current else (low, middle)
            segments.append((high, current))
            current = offset(high)
        moment = step
    return [*segments, (None, current)]


def _local(column, start: datetime, end: datetime, tz: str):
    """The UTC column as local (naive) time, exact for the offsets that apply in [start, end]."""
    segments = _offsets(start, end, tz)
    if len(segments) == 1:
        return func.dateadd(literal_column("minute"), segments[0][1], column)
    whens = [(column < until, func.dateadd(literal_column("minute"), minutes, column))
             for until, minutes in segments[:-1]]
    return case(*whens, else_=func.dateadd(literal_column("minute"), segments[-1][1], column))


def _to_utc(local: datetime, tz: str) -> datetime:
    return local.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


# ------------------------------------------------------------------------------------------ overview
async def overview_counts(db: SqlDb, start: datetime, end: datetime, *, unit: str, tz: str) -> OverviewCounts:
    """Totals and series for visits that checked in within [start, end). `unit`: "hour" or "day" buckets,
    in time zone `tz`."""
    within = _checked_in_within(start, end)
    local = _local(visits.c.check_in_at, start, end, tz)
    # The local hour or day a check-in falls in (DATEADD(unit, DATEDIFF(unit, 0, t), 0) truncates t).
    bucket = func.dateadd(literal_column(unit), func.datediff(literal_column(unit), 0, local), 0)
    totals = select(func.count(), _count_if(visits.c.status == "CHECKED_OUT"),
                    func.avg(case((_COMPLETED, cast(_STAY_MS, Float)), else_=None)),
                    func.count(visits.c.visitor_id.distinct())).where(within)
    by_status = select(visits.c.status, func.count()).where(within).group_by(visits.c.status)
    # Each department's name as recorded on its most recent visit in the range (MongoDB: $sort + $first).
    ranked = select(visits.c.department_id, visits.c.snap_department_name.label("name"),
                    func.row_number().over(partition_by=visits.c.department_id,
                                           order_by=(visits.c.check_in_at.desc(), visits.c.id.desc())).label("n"),
                    func.count().over(partition_by=visits.c.department_id).label("count")
                    ).where(within).subquery()
    by_department = select(ranked.c.department_id, ranked.c.name, ranked.c["count"]).where(ranked.c.n == 1)
    hour = func.datepart(literal_column("hour"), local)
    peak = select(hour.label("hour"), func.count()).where(within).group_by(hour)
    over_time = select(bucket.label("bucket"), func.count()).where(within).group_by(bucket)
    async with connection(db) as conn:
        visits_n, checked_out, avg_ms, unique = (await conn.execute(totals)).one()
        statuses = {status: n for status, n in await conn.execute(by_status)}
        departments = [{"id": row.department_id, "name": row.name, "count": row._mapping["count"]}
                       for row in await conn.execute(by_department)]           # (row.count is a tuple method)
        hours = {int(h): n for h, n in await conn.execute(peak)}
        buckets = {_to_utc(b, tz): n for b, n in await conn.execute(over_time)}
    return OverviewCounts(visits=visits_n, checked_out=int(checked_out or 0), avg_ms=avg_ms, unique_visitors=unique,
                          by_status=statuses, by_department=departments, peak_hours=hours, over_time=buckets)


# ------------------------------------------------------------------------------------------ visit report
async def count_visits(db: SqlDb, query) -> int:
    """Visits matching `query` (from services.visits.visit_query)."""
    async with connection(db) as conn:
        return (await conn.execute(select(func.count()).select_from(visits).where(query))).scalar_one()


def _report_row(row) -> dict:
    m = row._mapping
    doc = {"_id": m["id"], **{key: m[key] for key in ROW_COLUMNS}}
    doc["snapshot"] = {key: m[column] for key, column in SNAPSHOT.items()}
    if "duration_ms" in m:
        doc["duration_ms"] = m["duration_ms"]
    return doc


async def visit_rows(db: SqlDb, query, *, field: str, direction: int, keyset: Keyset | None, as_of: datetime,
                     limit: int) -> list[dict]:
    """Report rows (the columns a report shows) matching `query`, ordered by (`field`, id) in `direction`,
    after the `keyset`. field "duration_ms": time on site, until check-out or `as_of`."""
    shown = [visits.c.id, *(visits.c[key] for key in ROW_COLUMNS), *(visits.c[c] for c in SNAPSHOT.values())]
    if field == "duration_ms":
        until = func.coalesce(visits.c.check_out_at, as_of)
        duration = func.datediff_big(_MS, visits.c.check_in_at, until)
        inner = select(*shown, duration.label("duration_ms")).where(query).subquery()
        column, id_column = inner.c.duration_ms, inner.c.id
        statement = select(inner)
    else:
        column, id_column = visits.c[field], visits.c.id
        statement = select(*shown).where(query)
    if keyset:
        statement = statement.where(keyset.condition(column, id_column))
    order = (column.desc(), id_column.desc()) if direction < 0 else (column.asc(), id_column.asc())
    async with connection(db) as conn:
        return [_report_row(row) for row in await conn.execute(statement.order_by(*order).limit(limit))]


# ------------------------------------------------------------------------------------------ visitor summary
async def count_visitors(db: SqlDb, query) -> int:
    """Distinct visitors among the visits matching `query`."""
    statement = select(func.count(visits.c.visitor_id.distinct())).where(query)
    async with connection(db) as conn:
        return (await conn.execute(statement)).scalar_one()


async def visitor_groups(db: SqlDb, query, *, field: str, keyset: Keyset | None, limit: int) -> list[dict]:
    """Per visitor (key "_id": the visitor id): visits, completed, avg_ms (completed only), first and last
    check-in, latest recorded name; for the visits matching `query`. Ordered by `field` ("last" or
    "visits") then visitor id, both descending, after `keyset`."""
    groups = select(
        visits.c.visitor_id.label("_id"), func.count().label("visits"), _count_if(_COMPLETED).label("completed"),
        func.avg(case((_COMPLETED, cast(_STAY_MS, Float)), else_=None)).label("avg_ms"),
        func.min(visits.c.check_in_at).label("first"), func.max(visits.c.check_in_at).label("last"),
        _exact_max(visits.c.snap_visitor_name).label("name"),
    ).where(query).group_by(visits.c.visitor_id).subquery()
    statement = select(groups)
    if keyset:
        statement = statement.where(keyset.condition(groups.c[field], groups.c["_id"]))
    statement = statement.order_by(groups.c[field].desc(), groups.c["_id"].desc()).limit(limit)
    async with connection(db) as conn:
        return [dict(row._mapping) for row in await conn.execute(statement)]


async def visitors_inside(db: SqlDb, visitor_ids: list[UUID]) -> set[UUID]:
    """Which of these visitors are checked in now."""
    if not visitor_ids:
        return set()
    statement = select(visits.c.visitor_id).where(visits.c.visitor_id.in_(visitor_ids), _INSIDE)
    async with connection(db) as conn:
        return set((await conn.execute(statement)).scalars())


# ------------------------------------------------------------------------------------------ hosts, departments
_UNLISTED = case((visits.c.host_id.is_(None), visits.c.snap_host_name.collate(BINARY)), else_=None)


async def _host_rows(conn: AsyncConnection, where, counts: dict) -> list[dict]:
    """Grouped by host, unlisted host name and department; `counts`: {name: aggregate}."""
    statement = select(visits.c.host_id.label("host"), _UNLISTED.label("unlisted"),
                       visits.c.department_id.label("department"), *(v.label(k) for k, v in counts.items()),
                       _exact_max(visits.c.snap_host_name).label("host_name"),
                       _exact_max(visits.c.snap_department_name).label("department_name"),
                       ).where(where).group_by(visits.c.host_id, _UNLISTED, visits.c.department_id)
    return [dict(row._mapping) for row in await conn.execute(statement)]


async def host_groups(db: SqlDb, start: datetime, end: datetime, *, department_id: UUID | None
                      ) -> tuple[list[dict], list[dict]]:
    """(per host and department, visits that checked in within the range: visits, completed;
        per host and department, visits inside now: inside).
    Rows: {"host": id or None, "unlisted": typed name when no id, "department": id, counts, "host_name",
    "department_name" (as recorded on the visits)}."""
    scope = visits.c.department_id == department_id if department_id else None
    within = _checked_in_within(start, end) if scope is None else and_(_checked_in_within(start, end), scope)
    inside = _INSIDE if scope is None else and_(_INSIDE, scope)
    async with connection(db) as conn:
        visited = await _host_rows(conn, within, {"visits": func.count(), "completed": _count_if(_COMPLETED)})
        now_inside = await _host_rows(conn, inside, {"inside": func.count()})
    return visited, now_inside


async def department_groups(db: SqlDb, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    """(per department, visits that checked in within the range: visits, unique_visitors, completed, stay_ms
        (sum over completed visits), name;
        per department, visits inside now: inside, name)."""
    visited = select(visits.c.department_id.label("department"), func.count().label("visits"),
                     func.count(visits.c.visitor_id.distinct()).label("unique_visitors"),
                     _count_if(_COMPLETED).label("completed"),
                     func.coalesce(func.sum(case((_COMPLETED, _STAY_MS), else_=0)), 0).label("stay_ms"),
                     _exact_max(visits.c.snap_department_name).label("name"),
                     ).where(_checked_in_within(start, end)).group_by(visits.c.department_id)
    inside = select(visits.c.department_id.label("department"), func.count().label("inside"),
                    _exact_max(visits.c.snap_department_name).label("name"),
                    ).where(_INSIDE).group_by(visits.c.department_id)
    async with connection(db) as conn:
        return ([dict(row._mapping) for row in await conn.execute(visited)],
                [dict(row._mapping) for row in await conn.execute(inside)])


# ------------------------------------------------------------------------------------------ guards
async def guard_groups(db: SqlDb, start: datetime, end: datetime, *, watchlist_reason: str) -> GuardGroups:
    def per(operator, where):
        return select(operator.label("operator"), func.count().label("n")).where(where).group_by(operator)

    check_ins = per(visits.c.checked_in_by, _checked_in_within(start, end))
    check_outs = per(visits.c.checked_out_by, and_(visits.c.check_out_at.is_not(None),
                                                    visits.c.check_out_at >= start, visits.c.check_out_at < end))
    inside = per(visits.c.checked_in_by, _INSIDE)
    refused = select(denials.c.operator_id.label("operator"), func.count().label("n"),
                     _count_if(denials.c.reason == watchlist_reason).label("watchlist"),
                     _exact_max(func.coalesce(denials.c.operator_name, denials.c.operator_username)).label("name"),
                     ).where(denials.c.at >= start, denials.c.at < end).group_by(denials.c.operator_id)
    async with connection(db) as conn:
        found = [[dict(row._mapping) for row in await conn.execute(query)]
                 for query in (check_ins, check_outs, inside, refused)]
    return GuardGroups(*found)


# ------------------------------------------------------------------------------------------ denials
def _denial_where(start: datetime, end: datetime, *, source, operator_id, gate_id, reason):
    clauses = [denials.c.at >= start, denials.c.at < end]
    for column, value in ((denials.c.source, source), (denials.c.operator_id, operator_id),
                          (denials.c.gate_id, gate_id), (denials.c.reason, reason)):
        if value:
            clauses.append(column == value)
    return and_(*clauses)


async def count_denials(db: SqlDb, start: datetime, end: datetime, *, source: str | None = None,
                        operator_id: UUID | None = None, gate_id: UUID | None = None,
                        reason: str | None = None) -> int:
    """Refused entries in [start, end) matching the filters (index (at, id))."""
    where = _denial_where(start, end, source=source, operator_id=operator_id, gate_id=gate_id, reason=reason)
    async with connection(db) as conn:
        return (await conn.execute(select(func.count()).select_from(denials).where(where))).scalar_one()


async def denial_rows(db: SqlDb, start: datetime, end: datetime, *, source: str | None,
                      operator_id: UUID | None, gate_id: UUID | None,
                      after_row: tuple[datetime, UUID] | None, limit: int) -> list[dict]:
    """Refused entries in [start, end), newest first (the columns a report shows), after `after_row` (at, id)."""
    where = _denial_where(start, end, source=source, operator_id=operator_id, gate_id=gate_id, reason=None)
    statement = select(denials.c.id, *(denials.c[c] for c in DENIAL_COLUMNS)).where(where)
    if after_row:
        statement = statement.where(after("at", -1, after_row[0], after_row[1], False)
                                    .condition(denials.c.at, denials.c.id))
    statement = statement.order_by(denials.c.at.desc(), denials.c.id.desc()).limit(limit)
    async with connection(db) as conn:
        return [{"_id": row.id, **{c: row._mapping[c] for c in DENIAL_COLUMNS}}
                for row in await conn.execute(statement)]
