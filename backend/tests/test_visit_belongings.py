"""Updating belongings on an active visit (personal material returnable slip)."""
import pytest
from bson import ObjectId

from tests.test_visitors import new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio


@pytest.fixture
async def inside(guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    return (await check_in(guard, visitor["id"], directory)).json()


async def test_belongings_can_be_updated_while_inside(guard, inside):
    r = await guard.patch(f"/api/v1/visits/{inside['id']}/belongings",
                          json={"belongings": ["Laptop (01)", "Bag"], "vehicle_registration": "lea-1234"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["belongings"] == ["Laptop (01)", "Bag"]
    assert body["vehicle_registration"] == "LEA-1234"


async def test_belongings_cannot_be_updated_after_checkout(guard, inside):
    assert (await guard.post(f"/api/v1/visits/{inside['id']}/check-out")).status_code == 200
    r = await guard.patch(f"/api/v1/visits/{inside['id']}/belongings", json={"belongings": ["Laptop"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_checked_in"


async def test_belongings_update_is_audited(harness, guard, inside):
    await guard.patch(f"/api/v1/visits/{inside['id']}/belongings", json={"belongings": ["Bag"]})
    record = await harness.db.audit_logs.find_one({"action": "VISIT_BELONGINGS_UPDATED"})
    assert record is not None and record["resource"]["id"] == ObjectId(inside["id"])
    assert record["metadata"]["belongings_count"] == 1
