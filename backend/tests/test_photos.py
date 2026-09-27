"""Visitor photos: upload validation, private storage, check-in link and who may see which photo."""
import asyncio

import pytest
from bson import ObjectId

from tests.test_images import image_bytes
from tests.test_visitors import new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio


async def upload(client, visitor_id, data=None, content_type="image/jpeg"):
    return await client.post(f"/api/v1/visitors/{visitor_id}/photo", content=image_bytes() if data is None else data,
                             headers={"Content-Type": content_type})


# ---------------------------------------------------------------- capture
async def test_guard_captures_a_photo(harness, settings, guard):
    visitor = await new_visitor(guard)
    r = await upload(guard, visitor["id"])
    assert r.status_code == 201, r.text
    photo = r.json()
    assert set(photo) == {"id", "captured_at", "width", "height"}          # no file name, path or location
    doc = await harness.db.photos.find_one({"_id": ObjectId(photo["id"])})
    assert doc["visitor_id"] == ObjectId(visitor["id"]) and doc["content_type"] == "image/jpeg"
    stored = list(settings.photo_dir.rglob("*.jpg"))
    assert [p.stem for p in stored] == [doc["storage_key"]]                 # random name, not the CNIC
    assert "35201" not in str(stored[0]) and stored[0].read_bytes().startswith(b"\xff\xd8\xff")
    assert doc["storage_key"] not in r.text and str(settings.photo_dir) not in r.text

    lookup = (await guard.get(f"/api/v1/visitors/{visitor['id']}")).json()
    assert lookup["visitor"]["photo_id"] == photo["id"]
    record = await harness.db.audit_logs.find_one({"action": "PHOTO_CAPTURED"})
    assert record["resource"]["id"] == ObjectId(visitor["id"])
    assert record["metadata"]["photo_id"] == ObjectId(photo["id"])


@pytest.mark.parametrize("data,content_type,status,code", [
    (b"not an image at all", "image/jpeg", 422, "invalid_photo"),
    (image_bytes(size=(100, 80)), "image/jpeg", 422, "invalid_photo"),
    (image_bytes(), "text/plain", 415, "unsupported_media_type"),
    (image_bytes(), "image/svg+xml", 415, "unsupported_media_type"),
    (b"\xff\xd8\xff" + b"0" * (3 * 1024 * 1024), "image/jpeg", 413, "photo_too_large"),
], ids=["not-an-image", "too-small", "text-plain", "svg", "too-large"])
async def test_bad_uploads_are_refused_and_nothing_is_stored(harness, settings, guard, data, content_type, status,
                                                             code):
    visitor = await new_visitor(guard)
    r = await upload(guard, visitor["id"], data=data, content_type=content_type)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert await harness.db.photos.count_documents({}) == 0
    assert not settings.photo_dir.exists() or not any(settings.photo_dir.rglob("*.*"))


async def test_photo_for_an_unknown_visitor_is_404(guard):
    assert (await upload(guard, "0" * 24)).status_code == 404


async def test_anonymous_and_forged_uploads_are_refused(harness, guard):
    visitor = await new_visitor(guard)
    assert (await upload(harness.client(), visitor["id"])).status_code == 401
    forged = await guard.post_without_csrf(f"/api/v1/visitors/{visitor['id']}/photo", content=image_bytes(),
                                           headers={"Content-Type": "image/jpeg"})
    assert forged.status_code == 403


# ---------------------------------------------------------------- viewing
async def test_the_current_photo_can_be_viewed_at_the_gate(guard):
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    r = await guard.get(f"/api/v1/photos/{photo['id']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8\xff") and "no-store" in r.headers["cache-control"]
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_guards_cannot_browse_earlier_photos_but_admins_can(harness, admin, guard):
    visitor = await new_visitor(guard)
    old = (await upload(guard, visitor["id"])).json()
    await upload(guard, visitor["id"], data=image_bytes(color=(10, 200, 10)))
    r = await guard.get(f"/api/v1/photos/{old['id']}")
    assert r.status_code == 403
    denied = await harness.db.audit_logs.find_one({"action": "ACCESS_DENIED", "resource.type": "photo"})
    assert denied["metadata"]["reason"] == "photo_not_needed_at_gate"
    assert (await admin.get(f"/api/v1/photos/{old['id']}")).status_code == 200


async def test_guards_can_see_the_photo_of_a_visitor_who_is_inside(admin, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    await check_in(guard, visitor["id"], directory, photo_id=photo["id"])
    await upload(guard, visitor["id"], data=image_bytes(color=(1, 2, 3)))    # a newer photo becomes current
    assert (await guard.get(f"/api/v1/photos/{photo['id']}")).status_code == 200   # still needed at check-out


async def test_anonymous_viewing_is_refused(harness, guard):
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    r = await harness.client().get(f"/api/v1/photos/{photo['id']}")
    assert r.status_code == 401 and r.content[:3] != b"\xff\xd8\xff"


async def test_unknown_or_missing_photos_are_404(harness, settings, admin, guard):
    for photo_id in ("nope", "0" * 24):
        assert (await admin.get(f"/api/v1/photos/{photo_id}")).status_code == 404
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    for path in settings.photo_dir.rglob("*.jpg"):
        path.unlink()
    r = await admin.get(f"/api/v1/photos/{photo['id']}")
    assert r.status_code == 404 and str(settings.photo_dir) not in r.text


# ---------------------------------------------------------------- check-in link and lists
async def test_check_in_records_the_photo(harness, guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    visit = (await check_in(guard, visitor["id"], directory, photo_id=photo["id"])).json()
    assert visit["photo_id"] == photo["id"]
    doc = await harness.db.photos.find_one({"_id": ObjectId(photo["id"])})
    assert doc["visit_id"] == ObjectId(visit["id"])


async def test_check_in_refuses_another_visitors_photo(guard, directory):  # noqa: F811
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    photo_of_b = (await upload(guard, b["id"])).json()
    r = await check_in(guard, a["id"], directory, photo_id=photo_of_b["id"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_photo"


async def test_check_in_without_a_photo_still_works(guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    r = await check_in(guard, visitor["id"], directory)
    assert r.status_code == 201 and r.json()["photo_id"] is None


async def test_lists_carry_photo_ids_never_images(guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    photo = (await upload(guard, visitor["id"])).json()
    await check_in(guard, visitor["id"], directory, photo_id=photo["id"])
    for path in ("/api/v1/visitors?q=ali", "/api/v1/visits", "/api/v1/visits/active"):
        r = await guard.get(path)
        assert r.status_code == 200 and photo["id"] in r.text
        assert len(r.content) < 5000 and "base64" not in r.text


async def test_concurrent_captures_keep_one_current_photo(harness, guard):
    visitor = await new_visitor(guard)
    results = await asyncio.gather(*(upload(guard, visitor["id"], data=image_bytes(color=(i, i, i)))
                                     for i in range(4)))
    assert [r.status_code for r in results] == [201] * 4
    current = (await harness.db.visitors.find_one({"_id": ObjectId(visitor["id"])}))["current_photo_id"]
    assert str(current) in {r.json()["id"] for r in results}
