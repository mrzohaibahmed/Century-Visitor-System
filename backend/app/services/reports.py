"""
Reports: the overview (cards and chart series) and the visit report. Administrators only
(reports:view; the routers enforce it).

- report_range(): the local days a report covers ("today", "this week", a custom range...), worked out
  on the server in the organisation's time zone (Asia/Karachi) and turned into UTC bounds for MongoDB;
- report_visit_query(): the visit filter, built by the same code as the visit history
  (services/visits.visit_query), so a report and GET /visits never disagree about what a filter means;
- visitor_identities(): the ID number and phone for one page of rows in ONE query (no N+1), with a
  projection that never reads photos or anything else;
- security_counts(): denied entries and watchlist matches, the ONLY place that reads them, from the
  entry_denials collection (one document per refused attempt; see services/entry_denials).

Every query is bounded by the report's date range (at most 366 days) on check_in_at, which is indexed.
All aggregation happens in MongoDB; the browser receives totals and short, pre-filled series.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import decode_sort_cursor, encode_sort_cursor
from app.core.timeutil import DayRange, InvalidRange, RangePreset, day_bounds_utc, resolve_range
from app.schemas.reports import VisitReportSort
from app.services.entry_denials import WATCHLIST
from app.services.visits import VisitFilter, visit_query

# A name search in a report that matches more visitors than this is refused ("search_too_broad")
# instead of silently showing only some of them.
REPORT_VISITOR_MATCHES = 200
PAGE_LIMIT_MAX = 100
STATUSES = ("CHECKED_IN", "CHECKED_OUT")        # the statuses a visit actually takes (others are reserved)

# Only what a report row shows: never the pass, belongings, photo or vehicle.
ROW_PROJECTION = {field: 1 for field in (
    "visit_number", "visitor_id", "host_id", "host_unlisted", "department_id", "gate_id", "reason_code",
    "reason_note", "check_in_at", "check_out_at", "status", "checked_in_by", "checked_out_by", "snapshot")}

# sort -> (field, direction, can the field be null?)
_SORTS: dict[VisitReportSort, tuple[str, int, bool]] = {
    VisitReportSort.CHECK_IN_DESC: ("check_in_at", -1, False),
    VisitReportSort.CHECK_IN_ASC: ("check_in_at", 1, False),
    VisitReportSort.CHECK_OUT_DESC: ("check_out_at", -1, True),       # visits still inside come last
    VisitReportSort.DURATION_DESC: ("duration_ms", -1, False),        # computed, see _duration_ms
}


def report_range(settings: Settings, preset: RangePreset | str, day_from: date | None, day_to: date | None,
                 *, now: datetime | None = None) -> DayRange:
    try:
        return resolve_range(preset, day_from, day_to, settings.timezone, now=now)
    except InvalidRange as e:
        raise AppError(422, "invalid_range", str(e)) from None


async def report_visit_query(db: AsyncDatabase, f: VisitFilter) -> dict:
    return await visit_query(db, f, max_visitor_matches=REPORT_VISITOR_MATCHES)


async def visitor_identities(db: AsyncDatabase, visitor_ids: list[ObjectId]) -> dict[ObjectId, dict]:
    """{visitor id: {"identity": ..., "phone": ...}} for these visitors (masked later, in the schema)."""
    unique = list(dict.fromkeys(visitor_ids))
    if not unique:
        return {}
    docs = await db.visitors.find({"_id": {"$in": unique}}, {"identity": 1, "phone": 1}).to_list(length=len(unique))
    return {d["_id"]: d for d in docs}


# ------------------------------------------------------------------------------------------ security counts
@dataclass(frozen=True)
class SecurityCounts:
    denied_entries: int
    watchlist_matches: int


async def security_counts(db: AsyncDatabase, start: datetime, end: datetime) -> SecurityCounts:
    """Refused entries and watchlist matches between start (included) and end (excluded), UTC.

    Source: entry_denials only (never audit_logs as well, which would count each refusal twice). One
    document per refused attempt, whatever its source: refused at check-in, BLOCKED at the check-in
    lookup, or rebuilt from an older audit entry by backfill-entry-denials; the unique source_audit_id
    keeps a runtime record and its backfill from both existing.
    - denied_entries: every refusal in the range;
    - watchlist_matches: the refusals whose reason is WATCHLIST. Every refusal is one today, so the two are
      equal, but they stay separate counts should other refusal reasons be added.
    Both use the index (at, _id); the first is answered from the index alone.
    """
    window = {"at": {"$gte": start, "$lt": end}}
    denied = await db.entry_denials.count_documents(window)
    matches = await db.entry_denials.count_documents(window | {"reason": WATCHLIST})
    return SecurityCounts(denied_entries=denied, watchlist_matches=matches)


# ------------------------------------------------------------------------------------------ overview
def _buckets(r: DayRange) -> tuple[str, list[datetime]]:
    """Every bucket start of the range (UTC): hours for one day, days otherwise."""
    if r.days == 1:
        return "hour", [r.start + timedelta(hours=h) for h in range(int((r.end - r.start).total_seconds() // 3600))]
    return "day", [day_bounds_utc(r.first_day + timedelta(days=i), None, r.tz_name)[0] for i in range(r.days)]


async def overview(db: AsyncDatabase, r: DayRange, *, now: datetime | None = None) -> dict:
    """Totals and chart series for visits that checked in within the range, in ONE aggregation (one
    $facet over the indexed check-in range), plus the current number inside and the security counts."""
    now = now or datetime.now(UTC)
    unit, buckets = _buckets(r)
    tz = r.tz_name
    completed = {"$and": [{"$eq": ["$status", "CHECKED_OUT"]}, {"$eq": [{"$type": "$check_out_at"}, "date"]}]}
    pipeline = [
        {"$match": {"check_in_at": {"$gte": r.start, "$lt": r.end}}},
        {"$facet": {
            "totals": [{"$group": {
                "_id": None, "visits": {"$sum": 1},
                "checked_out": {"$sum": {"$cond": [{"$eq": ["$status", "CHECKED_OUT"]}, 1, 0]}},
                # $avg skips nulls: visits still inside never enter the average.
                "avg_ms": {"$avg": {"$cond": [completed, {"$subtract": ["$check_out_at", "$check_in_at"]}, None]}},
            }}],
            "unique_visitors": [{"$group": {"_id": "$visitor_id"}}, {"$count": "n"}],
            "by_status": [{"$group": {"_id": "$status", "count": {"$sum": 1}}}],
            "by_department": [
                {"$sort": {"check_in_at": -1}},
                {"$group": {"_id": "$department_id", "name": {"$first": "$snapshot.department_name"},
                            "count": {"$sum": 1}}},
            ],
            "peak_hours": [{"$group": {"_id": {"$hour": {"date": "$check_in_at", "timezone": tz}},
                                       "count": {"$sum": 1}}}],
            "over_time": [{"$group": {"_id": {"$dateTrunc": {"date": "$check_in_at", "unit": unit, "timezone": tz}},
                                      "count": {"$sum": 1}}}],
        }},
    ]
    facet = (await (await db.visits.aggregate(pipeline)).to_list(length=1))[0]
    totals = facet["totals"][0] if facet["totals"] else {"visits": 0, "checked_out": 0, "avg_ms": None}
    inside_now = await db.visits.count_documents({"status": "CHECKED_IN"})     # current state, not the range
    security = await security_counts(db, r.start, r.end)

    # Department names as they are now (a renamed department shows its new name); the snapshot otherwise.
    dep_ids = [d["_id"] for d in facet["by_department"] if d["_id"]]
    current = {d["_id"]: d["name"] for d in await db.departments.find(
        {"_id": {"$in": dep_ids}}, {"name": 1}).to_list(length=len(dep_ids))} if dep_ids else {}
    by_department = sorted(
        ({"id": str(d["_id"]) if d["_id"] else None, "name": current.get(d["_id"], d["name"]), "count": d["count"]}
         for d in facet["by_department"]),
        key=lambda d: (-d["count"], (d["name"] or "").casefold()))

    counted = {d["_id"].astimezone(UTC): d["count"] for d in facet["over_time"]}
    local = ZoneInfo(tz)
    by_status = {d["_id"]: d["count"] for d in facet["by_status"]}
    by_hour = {d["_id"]: d["count"] for d in facet["peak_hours"]}
    avg_ms = totals.get("avg_ms")
    return {
        "generated_at": now,
        "totals": {
            "visits": totals["visits"],
            "unique_visitors": facet["unique_visitors"][0]["n"] if facet["unique_visitors"] else 0,
            "inside_now": inside_now,
            "checked_out": totals["checked_out"],
            "denied_entries": security.denied_entries,
            "watchlist_matches": security.watchlist_matches,
            "avg_duration_minutes": round(avg_ms / 60000) if avg_ms is not None else None,
        },
        "series": {
            "bucket": unit,
            "over_time": [{"start": b.astimezone(local), "count": counted.get(b, 0)} for b in buckets],
            "by_department": by_department,
            "by_status": [{"status": s, "count": by_status.get(s, 0)} for s in STATUSES]
                         + [{"status": s, "count": c} for s, c in by_status.items() if s not in STATUSES],
            "peak_hours": [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)],
        },
    }


# ------------------------------------------------------------------------------------------ visit report
def _after(field: str, direction: int, value, last_id: ObjectId, nullable: bool) -> dict:
    """Keyset condition: the rows that come after (value, last_id) in this order."""
    op = "$lt" if direction < 0 else "$gt"
    if value is None:                        # already among the rows without a value (they come last)
        return {field: None, "_id": {op: last_id}}
    after: list[dict] = [{field: {op: value}}, {field: value, "_id": {op: last_id}}]
    if nullable:
        after.append({field: None})
    return {"$or": after}


def _duration_ms(as_of: datetime) -> dict:
    """Time on site in ms: until check-out, or until `as_of` for visits still inside."""
    return {"$subtract": [{"$ifNull": ["$check_out_at", as_of]}, "$check_in_at"]}


async def visit_report(db: AsyncDatabase, f: VisitFilter, *, sort: VisitReportSort, cursor: str | None,
                       limit: int, now: datetime | None = None) -> tuple[list[dict], str | None, int, datetime]:
    """One page of the visit report: (rows, next cursor, total matching the filters, the moment used for
    the durations of visits still inside). Keyset pagination only; `f` must carry the report's range."""
    if f.start is None or f.end is None:
        raise ValueError("A visit report is always bounded by a date range.")
    limit = max(1, min(limit, PAGE_LIMIT_MAX))
    field, direction, nullable = _SORTS[sort]
    as_of = now or datetime.now(UTC)
    last = None
    if cursor:
        value, last_id, pinned = decode_sort_cursor(cursor, str(sort))
        if sort is VisitReportSort.DURATION_DESC and pinned is not None:
            as_of = pinned                   # every page of a duration-sorted list uses the same "now"
        last = _after(field, direction, value, last_id, nullable)

    query = await report_visit_query(db, f)
    total = await db.visits.count_documents(query)
    order = [(field, direction), ("_id", direction)]
    if sort is VisitReportSort.DURATION_DESC:
        pipeline: list[dict] = [{"$match": query}, {"$addFields": {"duration_ms": _duration_ms(as_of)}}]
        if last:
            pipeline.append({"$match": last})
        pipeline += [{"$sort": dict(order)}, {"$limit": limit + 1}, {"$project": ROW_PROJECTION | {"duration_ms": 1}}]
        docs = await (await db.visits.aggregate(pipeline)).to_list(length=limit + 1)
    else:
        docs = await db.visits.find({"$and": [query, last]} if last else query, ROW_PROJECTION) \
            .sort(order).limit(limit + 1).to_list(length=limit + 1)

    next_cursor = None
    if len(docs) > limit:
        docs = docs[:limit]
        tail = docs[-1]
        next_cursor = encode_sort_cursor(str(sort), tail.get(field), tail["_id"],
                                         as_of if sort is VisitReportSort.DURATION_DESC else None)
    return docs, next_cursor, total, as_of
