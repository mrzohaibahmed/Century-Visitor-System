"""Visitors: create, lookup, search, details, admin edit, privacy."""
from datetime import UTC, datetime

import pytest
from bson import ObjectId

pytestmark = pytest.mark.anyio

CNIC = "35201-1234567-1"


async def new_visitor(client, name="Ali Khan", number=CNIC, id_type="CNIC", phone="0300-1234567"):
    r = await client.post("/api/v1/visitors", json={"full_name": name, "identity": {"type": id_type, "number": number},
                                                    "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_normalises_identity_phone_and_name(guard):
    v = await new_visitor(guard, name="  ali   KHAN ", number="3520112345671", phone="0300-1234567")
    assert v["full_name"] == "ali KHAN" and v["identity"] == {"type": "CNIC", "number": CNIC}
    assert v["phone"] == "03001234567"


async def test_same_identity_in_another_format_is_the_same_person(guard):
    await new_visitor(guard, number=CNIC)
    r = await guard.post("/api/v1/visitors", json={"full_name": "Other Name",
                                                   "identity": {"type": "CNIC", "number": " 35201 1234567 1 "}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "visitor_exists"


async def test_invalid_input_gets_a_clear_field_message(guard):
    r = await guard.post("/api/v1/visitors",
                         json={"full_name": "Ali Khan", "identity": {"type": "CNIC", "number": "123"}})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["message"] == "A CNIC must have exactly 13 digits."


async def test_lookup_finds_by_any_format_and_is_audited_with_a_masked_id(harness, guard):
    v = await new_visitor(guard)
    r = await guard.get("/api/v1/visitors/lookup", params={"id_type": "CNIC", "id_number": "3520112345671"})
    assert r.status_code == 200
    body = r.json()
    assert body["visitor"]["id"] == v["id"] and body["screening"] == {"status": "CLEAR", "reason": None}
    assert body["visitor"]["active_visit"] is None
    missing = await guard.get("/api/v1/visitors/lookup", params={"id_type": "CNIC", "id_number": "11111-1111111-1"})
    assert missing.status_code == 404
    lookups = await harness.db.audit_logs.find({"action": "VISITOR_LOOKUP"}).sort("timestamp", 1).to_list(None)
    assert [e["metadata"]["found"] for e in lookups] == [True, False]
    assert "1234567" not in str(lookups) and "1111111" not in str(lookups)


async def test_lookup_reports_watchlist_matches(harness, guard):
    v = await new_visitor(guard)
    await harness.db.watchlist.insert_one({
        "identifier": f"CNIC:{CNIC}", "identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft.",
        "is_active": True, "expires_at": None, "created_by": ObjectId(), "created_at": datetime.now(UTC)})
    body = (await guard.get(f"/api/v1/visitors/{v['id']}")).json()
    assert body["screening"] == {"status": "BLOCKED", "reason": "Theft."}


async def test_search_by_id_phone_and_name(guard):
    await new_visitor(guard, name="Ali Khan", number=CNIC, phone="0300-1234567")
    await new_visitor(guard, name="Alia Noor", number="35201-7654321-2", phone="0311-7654321")
    await new_visitor(guard, name="علی خان", number="AB123456", id_type="PASSPORT", phone=None)

    async def names(q):
        r = await guard.get("/api/v1/visitors", params={"q": q})
        assert r.status_code == 200, r.text
        return sorted(i["full_name"] for i in r.json()["items"])

    assert await names("3520112345671") == ["Ali Khan"]          # CNIC without dashes
    assert await names("03117654321") == ["Alia Noor"]            # phone
    assert await names("ab123456") == ["علی خان"]                  # passport, lower case
    assert await names("ALI") == ["Ali Khan", "Alia Noor"]        # name prefix, any case
    assert await names("علی") == ["علی خان"]


async def test_search_pages_without_repeats(guard, monkeypatch):
    from app.services import visitors as svc
    monkeypatch.setattr(svc, "SEARCH_LIMIT", 2)
    for i in range(5):
        await new_visitor(guard, name=f"Zara {chr(65 + i)}", number=f"35201-000000{i}-1", phone=None)
    seen, cursor = [], None
    while True:
        params = {"q": "zara"} | ({"cursor": cursor} if cursor else {})
        page = (await guard.get("/api/v1/visitors", params=params)).json()
        seen += [i["full_name"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["Zara A", "Zara B", "Zara C", "Zara D", "Zara E"]


async def test_bad_cursor_and_short_queries(guard):
    assert (await guard.get("/api/v1/visitors", params={"q": "ali", "cursor": "garbage"})).status_code == 400
    assert (await guard.get("/api/v1/visitors", params={"q": "a"})).status_code == 422


async def test_opening_a_visitor_is_audited(harness, guard):
    v = await new_visitor(guard)
    await guard.get(f"/api/v1/visitors/{v['id']}")
    entry = await harness.db.audit_logs.find_one({"action": "VISITOR_VIEWED"})
    assert entry["actor"]["username"] == "guard1" and str(entry["resource"]["id"]) == v["id"]


@pytest.mark.parametrize("bad_id", ["nope", "0" * 24])
async def test_unknown_visitor_is_404(guard, bad_id):
    assert (await guard.get(f"/api/v1/visitors/{bad_id}")).status_code == 404


async def test_only_admins_edit_visitors_and_changes_are_audited_masked(harness, admin, guard):
    v = await new_visitor(guard)
    body = {"full_name": "Ali Raza Khan", "identity": {"type": "CNIC", "number": "35201-7777777-7"}}
    assert (await guard.patch(f"/api/v1/visitors/{v['id']}", json=body)).status_code == 403
    r = await admin.patch(f"/api/v1/visitors/{v['id']}", json=body)
    assert r.status_code == 200 and r.json()["full_name"] == "Ali Raza Khan"
    entry = await harness.db.audit_logs.find_one({"action": "VISITOR_UPDATED"})
    assert entry["changes"]["full_name"] == {"from": "Ali Khan", "to": "Ali Raza Khan"}
    assert "7777777" not in str(entry) and "1234567" not in str(entry)


async def test_visitor_creation_rejects_extra_fields(guard):
    r = await guard.post("/api/v1/visitors", json={"full_name": "Ali Khan",
                                                   "identity": {"type": "CNIC", "number": CNIC},
                                                   "created_by": "someone"})
    assert r.status_code == 422
