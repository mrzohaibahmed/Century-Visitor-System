"""
Reports: the overview (cards and chart series) and the visit report. Administrators only
(reports:view; the routers enforce it).

- report_range(): the local days a report covers ("today", "this week", a custom range...), worked out
  on the server in the organisation's time zone (Asia/Karachi) and turned into UTC bounds for the database;
- report_visit_query(): the visit filter, built by the same code as the visit history
  (services/visits.visit_query), so a report and GET /visits never disagree about what a filter means;
- visitor_identities(): the ID number and phone for one page of rows in ONE query (no N+1), with a
  projection that never reads photos or anything else;
- security_counts(): denied entries and watchlist matches, the ONLY place that reads them, from the
  entry_denials table (one record per refused attempt; see services/entry_denials).

Every query is bounded by the report's date range (at most 366 days) on check_in_at, which is indexed.
All aggregation happens in the database (repositories/reports.py); the browser receives totals and short,
pre-filled series.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import decode_sort_cursor, encode_sort_cursor
from app.core.timeutil import DayRange, InvalidRange, RangePreset, day_bounds_utc, resolve_range
from app.db.types import Db, RecordId
from app.repositories import directory as directory_repo
from app.repositories import reports as reports_repo
from app.repositories import visits as visits_repo
from app.schemas.reports import VisitReportSort
from app.services.entry_denials import WATCHLIST
from app.services.visits import VisitFilter, visit_query

# A name search in a report that matches more visitors than this is refused ("search_too_broad")
# instead of silently showing only some of them.
REPORT_VISITOR_MATCHES = 200
PAGE_LIMIT_MAX = 100
STATUSES = ("CHECKED_IN", "CHECKED_OUT")        # the statuses a visit actually takes (others are reserved)

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


async def report_visit_query(db: Db, f: VisitFilter) -> dict:
    return await visit_query(db, f, max_visitor_matches=REPORT_VISITOR_MATCHES)


async def visitor_identities(db: Db, visitor_ids: list[RecordId], *,
                             with_name: bool = False) -> dict[RecordId, dict]:
    """{visitor id: {"identity": ..., "phone": ...}} for these visitors (masked later, in the schema);
    also "full_name" if asked."""
    fields = ("identity", "phone", *(("full_name",) if with_name else ()))
    return await reports_repo.fields_by_id(db, "visitors", visitor_ids, fields)


# ------------------------------------------------------------------------------------------ security counts
@dataclass(frozen=True)
class SecurityCounts:
    denied_entries: int
    watchlist_matches: int


async def security_counts(db: Db, start: datetime, end: datetime) -> SecurityCounts:
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
    denied = await reports_repo.count_denials(db, start, end)
    matches = await reports_repo.count_denials(db, start, end, reason=WATCHLIST)
    return SecurityCounts(denied_entries=denied, watchlist_matches=matches)


# ------------------------------------------------------------------------------------------ overview
def _buckets(r: DayRange) -> tuple[str, list[datetime]]:
    """Every bucket start of the range (UTC): hours for one day, days otherwise."""
    if r.days == 1:
        return "hour", [r.start + timedelta(hours=h) for h in range(int((r.end - r.start).total_seconds() // 3600))]
    return "day", [day_bounds_utc(r.first_day + timedelta(days=i), None, r.tz_name)[0] for i in range(r.days)]


async def overview(db: Db, r: DayRange, *, now: datetime | None = None) -> dict:
    """Totals and chart series for visits that checked in within the range, in ONE aggregation (one
    $facet over the indexed check-in range), plus the current number inside and the security counts."""
    now = now or datetime.now(UTC)
    unit, buckets = _buckets(r)
    tz = r.tz_name
    counts = await reports_repo.overview_counts(db, r.start, r.end, unit=unit, tz=tz)
    inside_now = await visits_repo.count_active(db)     # current state, not the range
    security = await security_counts(db, r.start, r.end)

    # Department names as they are now (a renamed department shows its new name); the snapshot otherwise.
    dep_ids = {d["id"] for d in counts.by_department if d["id"]}
    current = await directory_repo.names_by_id(db, "departments", dep_ids)
    by_department = sorted(
        ({"id": str(d["id"]) if d["id"] else None, "name": current.get(d["id"], d["name"]), "count": d["count"]}
         for d in counts.by_department),
        key=lambda d: (-d["count"], (d["name"] or "").casefold()))

    counted = counts.over_time
    local = ZoneInfo(tz)
    by_status = counts.by_status
    by_hour = counts.peak_hours
    avg_ms = counts.avg_ms
    return {
        "generated_at": now,
        "totals": {
            "visits": counts.visits,
            "unique_visitors": counts.unique_visitors,
            "inside_now": inside_now,
            "checked_out": counts.checked_out,
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
_after = reports_repo.after


async def visit_report(db: Db, f: VisitFilter, *, sort: VisitReportSort, cursor: str | None,
                       limit: int, now: datetime | None = None, bounded: bool = True,
                       count: bool = True) -> tuple[list[dict], str | None, int | None, datetime]:
    """One page of the visit report: (rows, next cursor, total matching the filters, the moment used for
    the durations of visits still inside). Keyset pagination only; `f` must carry the report's range,
    except for the currently-inside report (bounded=False, status CHECKED_IN: the current state)."""
    if bounded and (f.start is None or f.end is None):
        raise ValueError("A visit report is always bounded by a date range.")
    if not bounded and f.status != "CHECKED_IN":
        raise ValueError("Only the visits inside now may be listed without a date range.")
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
    total = await reports_repo.count_visits(db, query) if count else None      # an export counts once, up front
    # field "duration_ms" (DURATION_DESC): time on site, until check-out or until `as_of` for visits inside.
    docs = await reports_repo.visit_rows(db, query, field=field, direction=direction, keyset=last, as_of=as_of,
                                         limit=limit + 1)

    next_cursor = None
    if len(docs) > limit:
        docs = docs[:limit]
        tail = docs[-1]
        next_cursor = encode_sort_cursor(str(sort), tail.get(field), tail["_id"],
                                         as_of if sort is VisitReportSort.DURATION_DESC else None)
    return docs, next_cursor, total, as_of


async def count_visits(db: Db, f: VisitFilter) -> int:
    """The visit report's total for these filters (the same query as visit_report)."""
    return await reports_repo.count_visits(db, await report_visit_query(db, f))


# ------------------------------------------------------------------------------------------ shared by step 5
GROUP_LIMIT_MAX = 500                   # hosts, departments, guards: directory-sized lists, bounded


def _bounded(rows: list[dict], key, limit: int | None) -> tuple[list[dict], int, bool]:
    """(the first `limit` rows in this order, how many there were, whether some were left out).
    limit None: every row (exports; these lists are directory-sized)."""
    rows = sorted(rows, key=key)
    if limit is None:
        return rows, len(rows), False
    limit = max(1, min(limit, GROUP_LIMIT_MAX))
    return rows[:limit], len(rows), len(rows) > limit


def _name_key(name: str | None) -> str:
    return (name or "").casefold()


# ------------------------------------------------------------------------------------------ visitor summary
_VISITOR_SORTS = {"last_visit_desc": "last", "visits_desc": "visits"}


_count_visitors = reports_repo.count_visitors


async def count_visitors(db: Db, f: VisitFilter) -> int:
    """The visitor summary's total for these filters (the same query as visitor_summary)."""
    return await _count_visitors(db, await report_visit_query(db, f))


async def visitor_summary(db: Db, f: VisitFilter, *, sort: str, cursor: str | None, limit: int,
                          count: bool = True
                          ) -> tuple[list[dict], str | None, int | None, dict[RecordId, dict], set[RecordId]]:
    """Per visitor: their visits that checked in within the range and match the filters, grouped in
    the database, one page at a time (keyset on the sort value, then the visitor id). Returns (groups, next
    cursor, number of visitors, their identity/phone/name, the ids of those inside now)."""
    if f.start is None or f.end is None:
        raise ValueError("A visitor summary is always bounded by a date range.")
    limit = max(1, min(limit, PAGE_LIMIT_MAX))
    field = _VISITOR_SORTS[sort]
    query = await report_visit_query(db, f)
    keyset = None
    if cursor:
        value, last_id, _ = decode_sort_cursor(cursor, sort)
        keyset = _after(field, -1, value, last_id, False)
    groups = await reports_repo.visitor_groups(db, query, field=field, keyset=keyset, limit=limit + 1)
    total = await _count_visitors(db, query) if count else None
    next_cursor = None
    if len(groups) > limit:
        groups = groups[:limit]
        next_cursor = encode_sort_cursor(sort, groups[-1][field], groups[-1]["_id"])
    ids = [g["_id"] for g in groups]
    people = await visitor_identities(db, ids, with_name=True)
    inside = await reports_repo.visitors_inside(db, ids)
    return groups, next_cursor, total, people, inside


# ------------------------------------------------------------------------------------------ hosts, departments
# A host is its directory id; an unlisted host (typed in at the gate, no id) is the name typed.
async def host_report(db: Db, r: DayRange, *, department_id: RecordId | None, limit: int | None
                      ) -> tuple[list[dict], int, bool]:
    """Visits per host and department (as recorded on each visit) within the range, plus how many of each
    host's visitors are inside now (current state: a host whose visitors are inside is listed even without
    a visit in the range)."""
    visited, inside = await reports_repo.host_groups(db, r.start, r.end, department_id=department_id)

    rows: dict[tuple, dict] = {}
    for g in visited + inside:
        key = (g.get("host"), g.get("unlisted"), g.get("department"))
        row = rows.setdefault(key, {"visits": 0, "completed": 0, "inside": 0, "host_name": g.get("host_name"),
                                    "department_name": g.get("department_name")})
        for field in ("visits", "completed", "inside"):
            row[field] += g.get(field, 0)
    hosts = await reports_repo.fields_by_id(db, "hosts", [k[0] for k in rows], ("name",))
    deps = await reports_repo.fields_by_id(db, "departments", [k[2] for k in rows], ("name",))
    out = [{
        "host": {"id": str(host) if host else None,
                 "name": hosts.get(host, {}).get("name") or (unlisted if host is None else row["host_name"])},
        "host_unlisted": host is None,
        "department": {"id": str(dep) if dep else None,
                       "name": deps.get(dep, {}).get("name") or row["department_name"]},
        "visits": row["visits"], "completed_visits": row["completed"], "inside_now": row["inside"],
    } for (host, unlisted, dep), row in rows.items()]
    return _bounded(out, lambda x: (-x["visits"], -x["inside_now"], _name_key(x["host"]["name"]),
                                    _name_key(x["department"]["name"])), limit)


async def department_report(db: Db, r: DayRange, *, limit: int | None) -> tuple[list[dict], int, bool]:
    """Visits per department within the range (unique visitors counted in two grouping stages, so no
    department ever holds a list of its visitors), plus visitors inside now (current state)."""
    visited, inside = await reports_repo.department_groups(db, r.start, r.end)
    rows: dict = {}
    for g in visited + inside:
        row = rows.setdefault(g["department"], {"visits": 0, "unique_visitors": 0, "completed": 0, "stay_ms": 0,
                                         "inside": 0, "name": g.get("name")})
        for field in ("visits", "unique_visitors", "completed", "stay_ms", "inside"):
            row[field] += g.get(field, 0)
    current = await reports_repo.fields_by_id(db, "departments", list(rows), ("name",))
    out = [{
        "department": {"id": str(dep) if dep else None, "name": current.get(dep, {}).get("name") or row["name"]},
        "visits": row["visits"], "completed_visits": row["completed"], "unique_visitors": row["unique_visitors"],
        "avg_duration_minutes": round(row["stay_ms"] / row["completed"] / 60000) if row["completed"] else None,
        "inside_now": row["inside"],
    } for dep, row in rows.items()]
    return _bounded(out, lambda x: (-x["visits"], -x["inside_now"], _name_key(x["department"]["name"])), limit)


# ------------------------------------------------------------------------------------------ guards
async def guard_report(db: Db, r: DayRange, *, limit: int | None) -> tuple[list[dict], int, bool]:
    """Per operator, from the ids recorded with each event (written from the session at the time, never
    taken from a request): check-ins within the range (by check-in time), check-outs within the range (by
    check-out time), visitors they checked in who are inside now (current state), and refusals within the
    range (entry_denials). Accounts are read for their name, role and active state only."""
    found = await reports_repo.guard_groups(db, r.start, r.end, watchlist_reason=WATCHLIST)

    counters = ("check_ins", "check_outs", "inside_now", "denied_entries", "watchlist_matches")
    rows: dict = {}
    for groups, field in ((found.check_ins, "check_ins"), (found.check_outs, "check_outs"),
                          (found.inside, "inside_now"), (found.denials, "denied_entries")):
        for g in groups:
            row = rows.setdefault(g["operator"], dict.fromkeys(counters, 0) | {"recorded_name": None})
            row[field] += g["n"]
            if field == "denied_entries":
                row["watchlist_matches"] += g["watchlist"]
                row["recorded_name"] = g.get("name")
    users = await reports_repo.fields_by_id(db, "users", list(rows), ("username", "display_name", "role", "is_active"))
    out = []
    for operator, row in rows.items():
        user = users.get(operator)
        out.append({
            "guard": {"id": str(operator) if operator else None,
                      "name": (user.get("display_name") or user.get("username")) if user else row["recorded_name"],
                      "role": user.get("role") if user else None,
                      "is_active": user.get("is_active") if user else None},
            **{field: row[field] for field in counters},
        })
    return _bounded(out, lambda x: (-(x["check_ins"] + x["check_outs"]), -x["denied_entries"],
                                    _name_key(x["guard"]["name"])), limit)


# ------------------------------------------------------------------------------------------ denials
DENIALS_SORT = "denials_newest"


def _denial_row(d: dict, bans: dict, visitors: dict, gates: dict, users: dict) -> dict:
    current: list[str] = []

    def ref(kind: str, id_field: str, recorded: str | None, lookup: dict, current_name) -> dict:
        record_id = d.get(id_field)
        name = recorded
        if not name and record_id in lookup:          # not recorded (older rebuilt record): the current name, flagged
            name = current_name(lookup[record_id])
            current.append(kind)
        return {"id": str(record_id) if record_id else None, "name": name}

    return {
        "id": str(d["_id"]), "at": d["at"], "reason": d["reason"], "reason_code": d.get("reason_code"),
        "source": d["source"], "identifier": d.get("identifier_masked"),
        "visitor": ref("visitor", "visitor_id", d.get("visitor_name"), visitors, lambda v: v.get("full_name")),
        "gate": ref("gate", "gate_id", d.get("gate_name"), gates, lambda g: g.get("name")),
        "operator": ref("operator", "operator_id", d.get("operator_name") or d.get("operator_username"), users,
                        lambda u: u.get("display_name") or u.get("username")),
        "watchlist": {"id": str(d["watchlist_id"]) if d.get("watchlist_id") else None,
                      "reason": bans.get(d.get("watchlist_id"), {}).get("reason")},
        "current_names": current,
    }


async def count_denials(db: Db, r: DayRange, *, source: str | None, operator_id: RecordId | None,
                        gate_id: RecordId | None) -> int:
    """The denial report's total for these filters (the same query as denial_report)."""
    return await reports_repo.count_denials(db, r.start, r.end, source=source, operator_id=operator_id,
                                            gate_id=gate_id)


async def denial_report(db: Db, r: DayRange, *, source: str | None, operator_id: RecordId | None,
                        gate_id: RecordId | None, cursor: str | None, limit: int, count: bool = True
                        ) -> tuple[list[dict], str | None, int | None]:
    """Refused entries within the range, newest first (index newest_first), from entry_denials only.
    Returns (rows, next cursor, rows matching the filters)."""
    limit = max(1, min(limit, PAGE_LIMIT_MAX))
    filters = {"source": source, "operator_id": operator_id, "gate_id": gate_id}
    total = await reports_repo.count_denials(db, r.start, r.end, **filters) if count else None
    after_row = None
    if cursor:
        value, last_id, _ = decode_sort_cursor(cursor, DENIALS_SORT)
        after_row = (value, last_id)
    docs = await reports_repo.denial_rows(db, r.start, r.end, **filters, after_row=after_row, limit=limit + 1)
    next_cursor = None
    if len(docs) > limit:
        docs = docs[:limit]
        next_cursor = encode_sort_cursor(DENIALS_SORT, docs[-1]["at"], docs[-1]["_id"])

    # One query per referenced table for the page (no N+1); only the fields shown.
    by_id = reports_repo.fields_by_id
    bans = await by_id(db, "watchlist", [d.get("watchlist_id") for d in docs], ("reason",))
    visitors = await by_id(db, "visitors", [d.get("visitor_id") for d in docs if not d.get("visitor_name")],
                           ("full_name",))
    gates = await by_id(db, "gates", [d.get("gate_id") for d in docs if not d.get("gate_name")], ("name",))
    users = await by_id(db, "users", [d.get("operator_id") for d in docs
                                      if not (d.get("operator_name") or d.get("operator_username"))],
                        ("username", "display_name"))
    return [_denial_row(d, bans, visitors, gates, users) for d in docs], next_cursor, total
