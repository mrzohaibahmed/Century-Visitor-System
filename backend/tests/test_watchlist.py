"""Watchlist management: administrators add, edit, expire and disable entries; screening uses them."""
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio

URL = "/api/v1/watchlist"


async def add(client, number="3520112345671", reason="Theft of company property.", **extra):
    body = {"identity": {"type": "CNIC", "number": number}, "reason": reason, **extra}
    return await client.post(URL, json=body)


def future(days=30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- add
async def test_admin_adds_an_entry_with_a_normalised_id(harness, admin):
    r = await add(admin, number=" 35201 1234567 1 ", name="  ali   khan ")
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["identity"] == {"type": "CNIC", "number": CNIC} and entry["name"] == "ali khan"
    assert entry["status"] == "ACTIVE" and entry["expires_at"] is None
    assert entry["created_by"]["name"] == "Admin" and entry["created_at"]
    stored = await harness.db.watchlist.find_one({"_id": ObjectId(entry["id"])})
    assert stored["identifier"] == f"CNIC:{CNIC}"


async def test_adding_is_audited_without_the_full_id_number(harness, admin):
    entry = (await add(admin)).json()
    record = await harness.db.audit_logs.find_one({"action": "WATCHLIST_ADDED"})
    assert record["resource"] == {"type": "watchlist", "id": ObjectId(entry["id"])}
    assert record["actor"]["username"] == "admin" and record["metadata"]["identifier"] == "CNIC:***********67-1"
    assert "1234567" not in str(record)


async def test_the_listed_person_is_blocked_at_the_gate(admin, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    await add(admin, number="35201-1234567-1")
    lookup = await guard.get("/api/v1/visitors/lookup", params={"id_type": "CNIC", "id_number": "3520112345671"})
    assert lookup.json()["screening"] == {"status": "BLOCKED", "reason": "Theft of company property."}
    r = await check_in(guard, visitor["id"], directory)
    assert r.status_code == 403 and r.json()["error"]["code"] == "entry_denied"


@pytest.mark.parametrize("ban,visitor", [
    (("CNIC", "35201-1234567-1"), ("PASSPORT", "3520112345671")),   # banned CNIC typed in as a passport
    (("CNIC", "35201-1234567-1"), ("OTHER", "35201-1234567-1")),    # ... or as another ID
    (("PASSPORT", "AB1234567"), ("OTHER", "ab 1234567")),
    (("OTHER", "DL-7788 99"), ("OTHER", "DL778899")),                # separators in "other" numbers
    (("OTHER", "DL778899"), ("PASSPORT", "DL778899")),
])
async def test_choosing_another_id_type_does_not_get_round_a_ban(admin, guard, directory, ban, visitor):  # noqa: F811
    body = {"identity": {"type": ban[0], "number": ban[1]}, "reason": "Theft of company property."}
    assert (await admin.post(URL, json=body)).status_code == 201
    person = await new_visitor(guard, id_type=visitor[0], number=visitor[1])
    lookup = await guard.get(f"/api/v1/visitors/{person['id']}")
    assert lookup.json()["screening"]["status"] == "BLOCKED"
    r = await check_in(guard, person["id"], directory)
    assert r.status_code == 403 and r.json()["error"]["code"] == "entry_denied"


async def test_other_id_numbers_are_not_caught_by_a_ban(admin, guard, directory):  # noqa: F811
    await add(admin, number="35201-1234567-1")
    for id_type, number in (("CNIC", "35201-1234567-2"), ("PASSPORT", "352011234567"), ("OTHER", "35201-1234567")):
        person = await new_visitor(guard, id_type=id_type, number=number)
        assert (await check_in(guard, person["id"], directory)).status_code == 201, (id_type, number)


async def test_the_name_is_taken_from_the_registered_visitor(admin, guard):
    await new_visitor(guard, name="Ali Khan")
    assert (await add(admin)).json()["name"] == "Ali Khan"


async def test_adding_someone_who_is_inside_says_so(admin, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    visit = (await check_in(guard, visitor["id"], directory)).json()
    assert (await add(admin)).json()["inside_visit_number"] == visit["visit_number"]


async def test_one_active_entry_per_person_in_any_format(admin):
    assert (await add(admin, number="35201-1234567-1")).status_code == 201
    r = await add(admin, number="3520112345671")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_listed"


@pytest.mark.parametrize("body,field", [
    ({"identity": {"type": "CNIC", "number": "123"}, "reason": "Theft."}, "identity"),
    ({"identity": {"type": "CNIC", "number": CNIC}, "reason": "  "}, "reason"),
    ({"identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft.", "expires_at": "2020-01-01T00:00:00Z"},
     "expires_at"),
    ({"identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft.", "expires_at": "2099-01-01T00:00:00"},
     "expires_at"),                                                                  # no time zone
    ({"identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft.", "is_active": False}, "is_active"),
])
async def test_invalid_entries_are_refused(admin, body, field):
    r = await admin.post(URL, json=body)
    assert r.status_code == 422 and field in str(r.json()["error"]["details"])


# ---------------------------------------------------------------- edit, expire, disable
async def test_edit_reason_and_end_date(harness, admin):
    entry = (await add(admin)).json()
    until = future()
    r = await admin.patch(f"{URL}/{entry['id']}", json={"reason": "Threatened staff.", "expires_at": until})
    assert r.status_code == 200 and r.json()["reason"] == "Threatened staff." and r.json()["expires_at"]
    assert r.json()["status"] == "ACTIVE" and r.json()["updated_at"]
    record = await harness.db.audit_logs.find_one({"action": "WATCHLIST_UPDATED"})
    assert record["changes"]["reason"] == {"from": "Theft of company property.", "to": "Threatened staff."}
    cleared = await admin.patch(f"{URL}/{entry['id']}", json={"clear_expiry": True})
    assert cleared.json()["expires_at"] is None


@pytest.mark.parametrize("body", [{}, {"expires_at": "2020-01-01T00:00:00Z"},
                                  {"clear_expiry": True, "expires_at": "2099-01-01T00:00:00Z"},
                                  {"identity": {"type": "CNIC", "number": "35201-7654321-2"}}])
async def test_invalid_edits_are_refused(admin, body):
    entry = (await add(admin)).json()
    assert (await admin.patch(f"{URL}/{entry['id']}", json=body)).status_code == 422


async def test_expire_now_lifts_the_block_once(harness, admin, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    entry = (await add(admin)).json()
    first = await admin.post(f"{URL}/{entry['id']}/expire")
    second = await admin.post(f"{URL}/{entry['id']}/expire")
    assert first.json()["status"] == "EXPIRED" and second.json()["status"] == "EXPIRED"
    assert await harness.db.audit_logs.count_documents({"action": "WATCHLIST_EXPIRED"}) == 1
    assert (await check_in(guard, visitor["id"], directory)).status_code == 201


async def test_disable_needs_a_note_lifts_the_block_and_freezes_the_entry(harness, admin, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    entry = (await add(admin)).json()
    assert (await admin.post(f"{URL}/{entry['id']}/disable", json={})).status_code == 422
    r = await admin.post(f"{URL}/{entry['id']}/disable", json={"note": "Cleared by the HR inquiry."})
    body = r.json()
    assert body["status"] == "DISABLED" and body["disabled_reason"] == "Cleared by the HR inquiry."
    assert body["disabled_by"]["name"] == "Admin" and body["disabled_at"]
    assert await harness.db.audit_logs.count_documents({"action": "WATCHLIST_DISABLED"}) == 1
    assert (await check_in(guard, visitor["id"], directory)).status_code == 201
    edit = await admin.patch(f"{URL}/{entry['id']}", json={"reason": "Changed my mind."})
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "entry_disabled"


async def test_a_person_can_be_listed_again_after_an_entry_ends(harness, admin):
    old = (await add(admin)).json()
    await admin.post(f"{URL}/{old['id']}/expire")
    new = await add(admin, reason="Second incident.")
    assert new.status_code == 201
    retired = (await admin.get(f"{URL}/{old['id']}")).json()
    assert retired["status"] == "DISABLED" and retired["disabled_reason"] == "Replaced by a new entry."
    assert (await harness.db.audit_logs.find_one({"action": "WATCHLIST_ADDED", "resource.id": ObjectId(
        new.json()["id"])}))["metadata"]["replaces"] == ObjectId(old["id"])


async def test_unknown_entries_are_404(admin):
    for path in (f"{URL}/nope", f"{URL}/{'0' * 24}"):
        assert (await admin.get(path)).status_code == 404
        assert (await admin.post(f"{path}/expire")).status_code == 404


# ---------------------------------------------------------------- list
async def test_search_filter_and_pages(admin):
    ids = {}
    for i, (number, name) in enumerate([("35201-0000001-1", "Bilal Shah"), ("35201-0000002-1", "Bina Rafiq"),
                                        ("35201-0000003-1", "Omar Farooq")]):
        ids[name] = (await add(admin, number=number, name=name, reason=f"Incident {i + 1}.")).json()["id"]
    await admin.post(f"{URL}/{ids['Omar Farooq']}/disable", json={"note": "Resolved."})

    async def names(**params):
        r = await admin.get(URL, params=params)
        assert r.status_code == 200, r.text
        return [e["name"] for e in r.json()["items"]]

    assert await names() == ["Omar Farooq", "Bina Rafiq", "Bilal Shah"]                 # newest first
    assert await names(q="bi") == ["Bina Rafiq", "Bilal Shah"]
    assert await names(q="3520100000011") == ["Bilal Shah"]                             # ID in any format
    assert await names(status="ACTIVE") == ["Bina Rafiq", "Bilal Shah"]
    assert await names(status="DISABLED") == ["Omar Farooq"]
    assert await names(status="EXPIRED") == []
    assert (await admin.get(URL, params={"status": "GONE"})).status_code == 422


async def test_list_pages_without_repeats(admin, monkeypatch):
    from app.services import watchlist as svc
    monkeypatch.setattr(svc, "PAGE_SIZE", 2)
    for i in range(5):
        await add(admin, number=f"35201-000000{i}-1")
    seen, cursor = [], None
    while True:
        page = (await admin.get(URL, params={"cursor": cursor} if cursor else {})).json()
        seen += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 == len(set(seen))


# ---------------------------------------------------------------- access
async def test_guards_cannot_manage_the_watchlist(harness, admin, guard):
    entry = (await add(admin)).json()
    for method, path, body in (("GET", URL, None), ("POST", URL, {"identity": {"type": "CNIC", "number": CNIC},
                                                                   "reason": "x" * 5}),
                               ("GET", f"{URL}/{entry['id']}", None),
                               ("PATCH", f"{URL}/{entry['id']}", {"reason": "abc"}),
                               ("POST", f"{URL}/{entry['id']}/expire", None),
                               ("POST", f"{URL}/{entry['id']}/disable", {"note": "abc"})):
        r = await guard.request(method, path, json=body)
        assert r.status_code == 403, (method, path)
    assert await harness.db.audit_logs.count_documents({"action": "ACCESS_DENIED",
                                                         "metadata.permission": "watchlist:manage"}) == 6


async def test_anonymous_and_forged_requests_are_refused(harness, admin):
    anonymous = harness.client()
    assert (await anonymous.get(URL)).status_code == 401
    assert (await anonymous.post(URL, json={})).status_code == 401
    forged = await admin.post_without_csrf(URL, json={"identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft."})
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "csrf_failed"
