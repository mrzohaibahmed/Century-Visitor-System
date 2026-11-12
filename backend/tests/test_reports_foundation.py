"""Reports, step 1 (foundation): the reports:view permission, report date ranges, the shared visit
filter, masking and the report row schema. No report endpoint exists yet."""
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.core.identity import mask_sensitive
from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission
from app.core.timeutil import MAX_RANGE_DAYS, InvalidRange, RangePreset, resolve_range
from app.repositories import reports as reports_repo
from app.repositories import visits as visits_repo
from app.schemas.reports import ReportRangeOut, VisitReportRow
from app.services import reports as reports_svc
from app.services.visits import TOO_BROAD, VisitFilter, visit_query
from tests.conftest import make_settings, new_record_id, record_id, visitor_ids_in
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
TZ = "Asia/Karachi"                      # UTC+5, no daylight saving


def at_karachi(y, m, d, hh=12, mm=0) -> datetime:
    """A moment given as Karachi wall-clock time, as UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5)


# ------------------------------------------------------------------------------------------ permission
def test_reports_view_is_an_admin_only_permission():
    assert Permission.REPORTS_VIEW == "reports:view"
    assert has_permission(Role.ADMIN, Permission.REPORTS_VIEW) is True
    assert has_permission(Role.GUARD, Permission.REPORTS_VIEW) is False


def test_guard_permissions_are_unchanged():
    assert ROLE_PERMISSIONS[Role.GUARD] == {
        Permission.DASHBOARD_VIEW, Permission.VISIT_CHECK_IN, Permission.VISIT_CHECK_OUT, Permission.VISIT_READ,
        Permission.PASS_ISSUE, Permission.VISITOR_READ, Permission.VISITOR_CREATE, Permission.DIRECTORY_READ,
        Permission.PHOTO_CAPTURE, Permission.PHOTO_VIEW, Permission.ACCOUNT_SELF, Permission.NOTIFICATION_READ,
    }


async def test_the_session_lists_reports_view_for_admins_only(admin, guard):
    assert "reports:view" in (await admin.get("/api/v1/auth/me")).json()["permissions"]
    assert "reports:view" not in (await guard.get("/api/v1/auth/me")).json()["permissions"]


# ------------------------------------------------------------------------------------------ date ranges
@pytest.mark.parametrize("preset,now,first,last", [
    ("today", at_karachi(2026, 9, 30), date(2026, 9, 30), date(2026, 9, 30)),
    ("yesterday", at_karachi(2026, 9, 30), date(2026, 9, 29), date(2026, 9, 29)),
    ("yesterday", at_karachi(2026, 10, 1), date(2026, 9, 30), date(2026, 9, 30)),          # across a month
    ("this_week", at_karachi(2026, 9, 30), date(2026, 9, 28), date(2026, 9, 30)),          # Wednesday
    ("this_week", at_karachi(2026, 9, 28), date(2026, 9, 28), date(2026, 9, 28)),          # Monday: one day
    ("this_week", at_karachi(2026, 10, 4), date(2026, 9, 28), date(2026, 10, 4)),          # Sunday: 7 days
    ("this_month", at_karachi(2026, 9, 30), date(2026, 9, 1), date(2026, 9, 30)),
    ("this_month", at_karachi(2026, 10, 1), date(2026, 10, 1), date(2026, 10, 1)),
    ("this_month", at_karachi(2028, 2, 29), date(2028, 2, 1), date(2028, 2, 29)),          # leap day
])
def test_presets(preset, now, first, last):
    r = resolve_range(preset, None, None, TZ, now=now)
    assert (r.first_day, r.last_day, r.preset) == (first, last, RangePreset(preset))
    assert r.days == (last - first).days + 1


def test_today_is_the_day_at_the_gate_not_in_utc():
    # 19:30 UTC on 29 September is 00:30 on 30 September in Karachi.
    r = resolve_range("today", None, None, TZ, now=datetime(2026, 9, 29, 19, 30, tzinfo=UTC))
    assert r.first_day == date(2026, 9, 30)


def test_bounds_are_local_midnights_in_utc():
    r = resolve_range("custom", date(2026, 9, 25), date(2026, 9, 26), TZ)
    assert r.start == datetime(2026, 9, 24, 19, 0, tzinfo=UTC)         # 25 Sept 00:00 in Karachi
    assert r.end == datetime(2026, 9, 26, 19, 0, tzinfo=UTC)           # 27 Sept 00:00: end excluded
    assert r.days == 2


def test_another_time_zone_moves_the_bounds():
    r = resolve_range("custom", date(2026, 9, 25), date(2026, 9, 25), "UTC")
    assert (r.start, r.end) == (datetime(2026, 9, 25, tzinfo=UTC), datetime(2026, 9, 26, tzinfo=UTC))


def test_custom_ranges_up_to_366_days():
    assert resolve_range("custom", date(2026, 1, 1), date(2026, 1, 1), TZ).days == 1
    assert resolve_range("custom", date(2027, 1, 1), date(2027, 12, 31) + timedelta(days=1), TZ).days \
        == MAX_RANGE_DAYS == 366


@pytest.mark.parametrize("preset,day_from,day_to,message", [
    ("custom", date(2026, 9, 2), date(2026, 9, 1), "The start date is after the end date."),
    ("custom", date(2026, 1, 1), date(2027, 1, 2), "Choose a range of at most 366 days."),
    ("custom", None, date(2026, 9, 1), "Choose both a start date and an end date."),
    ("custom", date(2026, 9, 1), None, "Choose both a start date and an end date."),
    ("today", date(2026, 9, 1), None, "Start and end dates are only used with a custom range."),
    ("this_week", None, date(2026, 9, 1), "Start and end dates are only used with a custom range."),
    ("last_year", None, None, "Choose a date range: today, yesterday, this week, this month or custom."),
])
def test_invalid_ranges(preset, day_from, day_to, message):
    with pytest.raises(InvalidRange, match=message):
        resolve_range(preset, day_from, day_to, TZ)


def test_invalid_ranges_become_a_safe_422():
    with pytest.raises(AppError) as e:
        reports_svc.report_range(make_settings(), "custom", date(2026, 9, 2), date(2026, 9, 1))
    assert (e.value.status_code, e.value.code) == (422, "invalid_range")


def test_the_range_uses_the_configured_time_zone():
    r = reports_svc.report_range(make_settings(), "today", None, None, now=datetime(2026, 9, 29, 19, 30, tzinfo=UTC))
    assert r.first_day == date(2026, 9, 30) and r.tz_name == "Asia/Karachi"
    out = ReportRangeOut.from_range(r).model_dump(mode="json", by_alias=True)
    assert out == {"preset": "today", "from": "2026-09-30", "to": "2026-09-30", "timezone": "Asia/Karachi"}


# ------------------------------------------------------------------------------------------ masking
@pytest.mark.parametrize("value,masked", [
    ("35201-1234567-1", "***********67-1"),       # CNIC: last 4 characters, as in the audit log
    ("+923001234567", "*********4567"),           # phone
    ("AB1234567", "*****4567"),                   # passport
    ("ABC1234", "****234"),                       # 7 characters: never more than half
    ("AB1", "**1"),
    ("A", "*"),
    ("", ""),
    (None, None),
])
def test_mask_sensitive(value, masked):
    assert mask_sensitive(value) == masked


# ------------------------------------------------------------------------------------------ shared filter
async def test_a_name_search_finds_visitors(harness, guard):
    v = await new_visitor(guard)
    for q in ("ali", CNIC, "0300-1234567"):
        assert visitor_ids_in(await visit_query(harness.db, VisitFilter(q=q))) == [record_id(v["id"])]
    # Searching within one visitor's visits: both conditions hold.
    other = new_record_id()
    assert visitor_ids_in(await visit_query(harness.db, VisitFilter(q="ali", visitor_id=other))) == []
    assert visitor_ids_in(await visit_query(harness.db, VisitFilter(q="ali", visitor_id=record_id(v["id"])))) == [
        record_id(v["id"])]


async def test_reports_refuse_a_search_that_matches_too_many_visitors(harness, monkeypatch):
    monkeypatch.setattr(reports_svc, "REPORT_VISITOR_MATCHES", 2)
    now = datetime.now(UTC)
    await harness.store.visitors.insert_many([{"full_name": f"Ali {n}", "name_search": f"ali {n}", "created_at": now,
                                            "updated_at": now} for n in ("a", "b", "c")])
    with pytest.raises(AppError) as e:
        await reports_svc.report_visit_query(harness.db, VisitFilter(q="ali"))
    assert e.value is TOO_BROAD and e.value.status_code == 422
    # Exactly at the limit is fine; the visit history keeps its silent cap.
    monkeypatch.setattr(reports_svc, "REPORT_VISITOR_MATCHES", 3)
    assert len(visitor_ids_in(await reports_svc.report_visit_query(harness.db, VisitFilter(q="ali")))) == 3
    assert len(visitor_ids_in(await visit_query(harness.db, VisitFilter(q="ali")))) == 3


async def test_the_history_and_the_filter_builder_agree(harness, guard, directory):  # noqa: F811
    """GET /visits now builds its filter with visit_query(): same results for the same filter."""
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    params = {"status": "CHECKED_OUT", "host_id": directory["host"]["id"], "gate_id": directory["gate"]["id"],
              "department_id": directory["dep"]["id"], "q": "ali"}
    listed = (await guard.get("/api/v1/visits", params=params)).json()["items"]
    query = await visit_query(harness.db, VisitFilter(
        status="CHECKED_OUT", host_id=record_id(directory["host"]["id"]), gate_id=record_id(directory["gate"]["id"]),
        department_id=record_id(directory["dep"]["id"]), q="ali"))
    found = await visits_repo.list_page(harness.db, query, after=None, limit=10)   # the filter, run as such
    assert [i["id"] for i in listed] == [str(d["_id"]) for d in found] == [visit["id"]]


# ------------------------------------------------------------------------------------------ report rows
async def test_report_rows_mask_the_id_and_phone_and_look_them_up_in_one_query(harness, guard, directory,  # noqa: F811
                                                                               monkeypatch):
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    doc = await harness.store.visits.find_one({"_id": record_id(visit["id"])})
    calls = []
    # Count the lookups (each is one query).
    original_lookup = reports_repo.fields_by_id

    async def counting_lookup(db, collection, ids, fields):
        calls.append((collection, fields))
        return await original_lookup(db, collection, ids, fields)
    monkeypatch.setattr(reports_repo, "fields_by_id", counting_lookup)
    expected = [("visitors", ("identity", "phone"))]
    people = await reports_svc.visitor_identities(harness.db, [doc["visitor_id"], doc["visitor_id"]])
    monkeypatch.undo()
    assert calls == expected                                              # one query, two fields only
    assert await reports_svc.visitor_identities(harness.db, []) == {}

    now = doc["check_in_at"] + timedelta(minutes=47, seconds=30)
    row = VisitReportRow.from_doc(doc, people[doc["visitor_id"]], now)
    text = row.model_dump_json()
    assert row.id_type == "CNIC" and row.id_number == "***********67-1" and row.phone == "*******4567"
    assert CNIC not in text and CNIC.replace("-", "") not in text and "03001234567" not in text
    assert "token_hash" not in text and "photo" not in text and "belongings" not in text
    assert row.duration_minutes == 47 and row.status == "CHECKED_IN" and row.checked_out_by is None
    assert row.host.name == "Sara Ahmed" and row.gate.name == "Main Gate" and row.department.name == "HR"
    assert row.checked_in_by.name == "Guard1" and row.reason_code == "OFFICIAL_MEETING"

    # Checked out: the duration ends at check-out; a visitor without an identity has no masked values.
    out = doc | {"status": "CHECKED_OUT", "check_out_at": doc["check_in_at"] + timedelta(hours=2),
                 "checked_out_by": doc["checked_in_by"], "snapshot": doc["snapshot"] | {"checked_out_by_name": "g"}}
    row = VisitReportRow.from_doc(out, None, now + timedelta(days=3))
    assert row.duration_minutes == 120 and row.id_number is None and row.phone is None
    assert row.checked_out_by.name == "g"
