"""Backup/restore checks: verify-data and restore-check (app/ops.py)."""
import pytest
from bson import ObjectId

from app.ops import restore_check, verify_data
from tests.conftest import make_settings
from tests.test_images import image_bytes
from tests.test_visitors import new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio


async def upload(client, visitor_id, color=(90, 120, 150)):
    r = await client.post(f"/api/v1/visitors/{visitor_id}/photo", content=image_bytes(color=color),
                          headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def data(guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    old = await upload(guard, visitor["id"])
    current = await upload(guard, visitor["id"], color=(1, 2, 3))
    visit = (await check_in(guard, visitor["id"], directory, photo_id=current["id"])).json()
    await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    return {"visitor": visitor, "old": old, "current": current, "visit": visit}


async def test_intact_data_passes(harness, settings, data):
    report = await verify_data(harness.db, settings)
    assert report["ok"] is True and report["photo_files_checked"] == 2 and report["problems"] == {}
    assert report["counts"]["visits"] == 1 and report["counts"]["photos"] == 2
    assert "Ali Khan" not in str(report) and "35201" not in str(report) and str(settings.photo_dir) not in str(report)


async def test_missing_and_changed_photo_files_are_found(harness, settings, data):
    files = sorted(settings.photo_dir.rglob("*.jpg"))
    files[0].unlink()
    files[1].write_bytes(files[1].read_bytes() + b"x")
    report = await verify_data(harness.db, settings)
    assert report["ok"] is False
    assert report["problems"]["photo_file_missing"]["count"] == 1
    assert report["problems"]["photo_file_changed"]["count"] == 1


async def test_broken_photo_links_are_found(harness, settings, data):
    await harness.db.photos.delete_one({"_id": ObjectId(data["current"]["id"])})
    report = await verify_data(harness.db, settings)
    assert report["problems"]["visit_photo_missing"]["examples"] == [data["visit"]["id"]]
    assert report["problems"]["visitor_photo_missing"]["examples"] == [data["visitor"]["id"]]


async def test_restore_check_proves_the_access_rules_on_a_copy(harness, settings, data):
    report = await restore_check(settings)
    assert report["ok"] is True, report
    assert report["photo_checks_ran"] is True
    assert report["access"] == {
        "login_admin": True, "login_guard": True, "users_readable": True, "guard_refused_admin_pages": True,
        "visits_readable": True, "watchlist_readable_by_admin": True, "watchlist_refused_to_guard": True,
        "admin_sees_photo": True, "guard_sees_current_photo": True, "anonymous_refused_photo": True,
        "visit_links_to_photo": True, "guard_refused_older_photo": True}


async def test_restore_check_refuses_production():
    with pytest.raises(RuntimeError, match="never against production"):
        await restore_check(make_settings(environment="production"))
