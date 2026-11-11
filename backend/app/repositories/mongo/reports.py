"""MongoDB access for the reports: the aggregations, returned as plain grouped rows.

Every function here only reads. It returns counts and groups keyed by plain names ("department",
"operator", ...); merging, naming, sorting and limits stay in services/reports.py, so another database
only has to return the same rows (e.g. from GROUP BY queries).
"""
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.report_types import GuardGroups, OverviewCounts

# Only what a report row shows: never the pass, belongings, photo or vehicle.
ROW_PROJECTION = {field: 1 for field in (
    "visit_number", "visitor_id", "host_id", "host_unlisted", "department_id", "gate_id", "reason_code",
    "reason_note", "check_in_at", "check_out_at", "status", "checked_in_by", "checked_out_by", "snapshot")}
DENIAL_FIELDS = dict.fromkeys(("at", "reason", "reason_code", "source", "visitor_id", "visitor_name",
                               "identifier_masked", "watchlist_id", "gate_id", "gate_name", "operator_id",
                               "operator_name", "operator_username"), 1)
# Collections whose documents a report may look up by id (only the fields asked for).
LOOKUP_COLLECTIONS = {"visitors", "hosts", "departments", "users", "watchlist", "gates"}

_COMPLETED = {"$and": [{"$eq": ["$status", "CHECKED_OUT"]}, {"$eq": [{"$type": "$check_out_at"}, "date"]}]}
_STAY_MS = {"$subtract": ["$check_out_at", "$check_in_at"]}
_INSIDE = {"status": "CHECKED_IN"}      # the current state (index status_check_in)
# A host is its directory id; an unlisted host (typed in at the gate, no id) is the name typed.
_HOST_KEY = {"host": "$host_id", "department": "$department_id",
             "unlisted": {"$cond": [{"$eq": [{"$ifNull": ["$host_id", None]}, None]}, "$snapshot.host_name", None]}}
_SNAPSHOT_NAMES = {"host_name": {"$max": "$snapshot.host_name"},
                   "department_name": {"$max": "$snapshot.department_name"}}


async def _aggregate(collection, pipeline: list[dict]) -> list[dict]:
    return await (await collection.aggregate(pipeline)).to_list(length=None)


def _checked_in_within(start: datetime, end: datetime) -> dict:
    return {"check_in_at": {"$gte": start, "$lt": end}}


def after(field: str, direction: int, value, last_id: ObjectId, nullable: bool) -> dict:
    """Keyset condition: the rows that come after (value, last_id) in this order. With `nullable`, rows
    without a value come last."""
    op = "$lt" if direction < 0 else "$gt"
    if value is None:                        # already among the rows without a value (they come last)
        return {field: None, "_id": {op: last_id}}
    later: list[dict] = [{field: {op: value}}, {field: value, "_id": {op: last_id}}]
    if nullable:
        later.append({field: None})
    return {"$or": later}


async def fields_by_id(db: AsyncDatabase, collection: str, ids, fields: tuple[str, ...]) -> dict[ObjectId, dict]:
    """{id: document with only `fields`} for these ids (others, e.g. None, are ignored), in one query."""
    if collection not in LOOKUP_COLLECTIONS:
        raise ValueError(f"not a report lookup collection: {collection}")
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, ObjectId)]
    if not ids:
        return {}
    docs = await db[collection].find({"_id": {"$in": ids}}, dict.fromkeys(fields, 1)).to_list(length=len(ids))
    return {d["_id"]: d for d in docs}


# ------------------------------------------------------------------------------------------ overview
async def overview_counts(db: AsyncDatabase, start: datetime, end: datetime, *, unit: str, tz: str
                          ) -> OverviewCounts:
    """Totals and series for visits that checked in within [start, end), in ONE aggregation (one $facet
    over the indexed check-in range). `unit`: "hour" or "day" buckets, in time zone `tz`."""
    pipeline = [
        {"$match": _checked_in_within(start, end)},
        {"$facet": {
            "totals": [{"$group": {
                "_id": None, "visits": {"$sum": 1},
                "checked_out": {"$sum": {"$cond": [{"$eq": ["$status", "CHECKED_OUT"]}, 1, 0]}},
                # $avg skips nulls: visits still inside never enter the average.
                "avg_ms": {"$avg": {"$cond": [_COMPLETED, _STAY_MS, None]}},
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
    facet = (await _aggregate(db.visits, pipeline))[0]
    totals = facet["totals"][0] if facet["totals"] else {"visits": 0, "checked_out": 0, "avg_ms": None}
    return OverviewCounts(
        visits=totals["visits"], checked_out=totals["checked_out"], avg_ms=totals.get("avg_ms"),
        unique_visitors=facet["unique_visitors"][0]["n"] if facet["unique_visitors"] else 0,
        by_status={d["_id"]: d["count"] for d in facet["by_status"]},
        by_department=[{"id": d["_id"], "name": d["name"], "count": d["count"]} for d in facet["by_department"]],
        peak_hours={d["_id"]: d["count"] for d in facet["peak_hours"]},
        over_time={d["_id"].astimezone(UTC): d["count"] for d in facet["over_time"]},
    )


# ------------------------------------------------------------------------------------------ visit report
async def count_visits(db: AsyncDatabase, query: dict) -> int:
    """Visits matching `query` (from services.visits.visit_query)."""
    return await db.visits.count_documents(query)


async def visit_rows(db: AsyncDatabase, query: dict, *, field: str, direction: int, keyset: dict | None,
                     as_of: datetime, limit: int) -> list[dict]:
    """Report rows (ROW_PROJECTION) matching `query`, ordered by (`field`, _id) in `direction`, after the
    `keyset` condition (from after()). field "duration_ms": time on site, until check-out or `as_of`."""
    order = [(field, direction), ("_id", direction)]
    if field == "duration_ms":
        duration = {"$subtract": [{"$ifNull": ["$check_out_at", as_of]}, "$check_in_at"]}
        pipeline: list[dict] = [{"$match": query}, {"$addFields": {"duration_ms": duration}}]
        if keyset:
            pipeline.append({"$match": keyset})
        pipeline += [{"$sort": dict(order)}, {"$limit": limit}, {"$project": ROW_PROJECTION | {"duration_ms": 1}}]
        return await (await db.visits.aggregate(pipeline)).to_list(length=limit)
    return await db.visits.find({"$and": [query, keyset]} if keyset else query, ROW_PROJECTION) \
        .sort(order).limit(limit).to_list(length=limit)


# ------------------------------------------------------------------------------------------ visitor summary
async def count_visitors(db: AsyncDatabase, query: dict) -> int:
    """Distinct visitors among the visits matching `query`."""
    counted = await _aggregate(db.visits, [{"$match": query}, {"$group": {"_id": "$visitor_id"}}, {"$count": "n"}])
    return counted[0]["n"] if counted else 0


async def visitor_groups(db: AsyncDatabase, query: dict, *, field: str, keyset: dict | None,
                         limit: int) -> list[dict]:
    """Per visitor (key "_id": the visitor id): visits, completed, avg_ms (completed only), first and last
    check-in, latest recorded name; for the visits matching `query`. Ordered by `field` ("last" or
    "visits") then visitor id, both descending, after `keyset`."""
    pipeline: list[dict] = [{"$match": query}, {"$group": {
        "_id": "$visitor_id", "visits": {"$sum": 1},
        "completed": {"$sum": {"$cond": [_COMPLETED, 1, 0]}},
        "avg_ms": {"$avg": {"$cond": [_COMPLETED, _STAY_MS, None]}},       # visits inside: left out
        "first": {"$min": "$check_in_at"}, "last": {"$max": "$check_in_at"},
        "name": {"$max": "$snapshot.visitor_name"},
    }}]
    if keyset:
        pipeline.append({"$match": keyset})
    pipeline += [{"$sort": {field: -1, "_id": -1}}, {"$limit": limit}]
    return await _aggregate(db.visits, pipeline)


async def visitors_inside(db: AsyncDatabase, visitor_ids: list[ObjectId]) -> set[ObjectId]:
    """Which of these visitors are checked in now."""
    if not visitor_ids:
        return set()
    docs = await db.visits.find({"visitor_id": {"$in": visitor_ids}} | _INSIDE, {"visitor_id": 1}) \
        .to_list(length=len(visitor_ids))
    return {d["visitor_id"] for d in docs}


# ------------------------------------------------------------------------------------------ hosts, departments
def _flat_host(g: dict) -> dict:
    key = g.pop("_id")
    return {"host": key.get("host"), "unlisted": key.get("unlisted"), "department": key.get("department"), **g}


async def host_groups(db: AsyncDatabase, start: datetime, end: datetime, *, department_id: ObjectId | None
                      ) -> tuple[list[dict], list[dict]]:
    """(per host and department, visits that checked in within the range: visits, completed;
        per host and department, visits inside now: inside).
    Rows: {"host": id or None, "unlisted": typed name when no id, "department": id, counts, "host_name",
    "department_name" (as recorded on the visits)}."""
    scope = {"department_id": department_id} if department_id else {}
    visited = await _aggregate(db.visits, [{"$match": _checked_in_within(start, end) | scope}, {"$group": {
        "_id": _HOST_KEY, "visits": {"$sum": 1}, "completed": {"$sum": {"$cond": [_COMPLETED, 1, 0]}},
        **_SNAPSHOT_NAMES}}])
    inside = await _aggregate(db.visits, [{"$match": _INSIDE | scope}, {"$group": {
        "_id": _HOST_KEY, "inside": {"$sum": 1}, **_SNAPSHOT_NAMES}}])
    return [_flat_host(g) for g in visited], [_flat_host(g) for g in inside]


async def department_groups(db: AsyncDatabase, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    """(per department, visits that checked in within the range: visits, unique_visitors, completed, stay_ms
        (sum over completed visits), name;
        per department, visits inside now: inside, name).
    Unique visitors are counted in two grouping stages, so no department ever holds a list of its visitors."""
    visited = await _aggregate(db.visits, [
        {"$match": _checked_in_within(start, end)},
        {"$group": {"_id": {"department": "$department_id", "visitor": "$visitor_id"}, "visits": {"$sum": 1},
                    "completed": {"$sum": {"$cond": [_COMPLETED, 1, 0]}},
                    "stay_ms": {"$sum": {"$cond": [_COMPLETED, _STAY_MS, 0]}},
                    "name": {"$max": "$snapshot.department_name"}}},
        {"$group": {"_id": "$_id.department", "visits": {"$sum": "$visits"}, "unique_visitors": {"$sum": 1},
                    "completed": {"$sum": "$completed"}, "stay_ms": {"$sum": "$stay_ms"}, "name": {"$max": "$name"}}},
    ])
    inside = await _aggregate(db.visits, [{"$match": _INSIDE}, {"$group": {
        "_id": "$department_id", "inside": {"$sum": 1}, "name": {"$max": "$snapshot.department_name"}}}])
    return ([{"department": g.pop("_id"), **g} for g in visited], [{"department": g.pop("_id"), **g} for g in inside])


# ------------------------------------------------------------------------------------------ guards
async def guard_groups(db: AsyncDatabase, start: datetime, end: datetime, *, watchlist_reason: str) -> GuardGroups:
    one = {"n": {"$sum": 1}}

    def flat(groups: list[dict]) -> list[dict]:
        return [{"operator": g.pop("_id"), **g} for g in groups]

    check_ins = await _aggregate(db.visits, [{"$match": _checked_in_within(start, end)},
                                             {"$group": {"_id": "$checked_in_by", **one}}])
    check_outs = await _aggregate(db.visits, [
        {"$match": {"check_out_at": {"$type": "date", "$gte": start, "$lt": end}}},   # index check_out
        {"$group": {"_id": "$checked_out_by", **one}}])
    inside = await _aggregate(db.visits, [{"$match": _INSIDE}, {"$group": {"_id": "$checked_in_by", **one}}])
    denials = await _aggregate(db.entry_denials, [
        {"$match": {"at": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": "$operator_id", **one,
                    "watchlist": {"$sum": {"$cond": [{"$eq": ["$reason", watchlist_reason]}, 1, 0]}},
                    "name": {"$max": {"$ifNull": ["$operator_name", "$operator_username"]}}}}])
    return GuardGroups(flat(check_ins), flat(check_outs), flat(inside), flat(denials))


# ------------------------------------------------------------------------------------------ denials
def _denial_query(start: datetime, end: datetime, *, source: str | None, operator_id: ObjectId | None,
                  gate_id: ObjectId | None, reason: str | None) -> dict:
    query: dict = {"at": {"$gte": start, "$lt": end}}
    for field, value in (("source", source), ("operator_id", operator_id), ("gate_id", gate_id),
                         ("reason", reason)):
        if value:
            query[field] = value
    return query


async def count_denials(db: AsyncDatabase, start: datetime, end: datetime, *, source: str | None = None,
                        operator_id: ObjectId | None = None, gate_id: ObjectId | None = None,
                        reason: str | None = None) -> int:
    """Refused entries in [start, end) matching the filters (index (at, _id))."""
    return await db.entry_denials.count_documents(
        _denial_query(start, end, source=source, operator_id=operator_id, gate_id=gate_id, reason=reason))


async def denial_rows(db: AsyncDatabase, start: datetime, end: datetime, *, source: str | None,
                      operator_id: ObjectId | None, gate_id: ObjectId | None,
                      after_row: tuple[datetime, ObjectId] | None, limit: int) -> list[dict]:
    """Refused entries in [start, end), newest first (DENIAL_FIELDS only), after `after_row` (at, id)."""
    query = _denial_query(start, end, source=source, operator_id=operator_id, gate_id=gate_id, reason=None)
    if after_row:
        query = {"$and": [query, after("at", -1, after_row[0], after_row[1], False)]}
    return await db.entry_denials.find(query, DENIAL_FIELDS).sort([("at", -1), ("_id", -1)]) \
        .limit(limit).to_list(length=limit)
