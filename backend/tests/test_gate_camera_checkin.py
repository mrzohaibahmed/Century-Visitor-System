"""Check-in capture from the session's gate camera (guards), with fake Hikvision cameras on 127.0.0.1.

The camera is chosen by the server from the session's gate, never by the browser. The picture is a
preview: nothing is stored until it is uploaded through the normal visitor photo endpoint.
"""
import threading

import pytest
from bson import ObjectId

from app.core.secrets import generate_key
from tests.conftest import make_settings
from tests.test_gate_camera import PASSWORD, USER, FakeCamera, jpeg
from tests.test_visitors import new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio

SNAPSHOT = "/ISAPI/Streaming/channels/101/picture"
XML_ERROR = b"<ResponseStatus/>"


@pytest.fixture
def settings():
    return make_settings(secrets_key=generate_key())


def _start() -> FakeCamera:
    server = FakeCamera()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def cameras():
    started = [_start(), _start()]
    started[0].routes[SNAPSHOT] = (200, "image/jpeg", jpeg((1280, 720)))       # gate A: 16:9
    started[1].routes[SNAPSHOT] = (200, "image/jpeg", jpeg((800, 800)))        # gate B: square
    yield started
    for s in started:
        s.shutdown()
        s.server_close()


async def configure(admin, gate_id: str, camera: FakeCamera, **change):
    body = {"enabled": True, "host": "127.0.0.1", "protocol": "http", "port": camera.port, "channel": 101,
            "username": USER, "password": PASSWORD, "timeout_seconds": 2} | change
    r = await admin.put(f"/api/v1/gate-cameras/{gate_id}", json=body)
    assert r.status_code == 200, r.text


async def one_gate_with_camera(admin, camera: FakeCamera, **change) -> str:
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()["id"]
    await configure(admin, gate, camera, **change)
    return gate


async def picture_size(r) -> tuple[int, int]:
    import io

    from PIL import Image
    with Image.open(io.BytesIO(r.content)) as img:
        return img.size


# ---------------------------------------------------------------- availability (never contacts the camera)
async def test_available_only_with_an_enabled_camera_and_a_usable_password(harness, admin, guard, cameras):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()["id"]
    assert (await guard.get("/api/v1/gate-camera")).json() == {"available": False}          # no camera set up
    await configure(admin, gate, cameras[0])
    assert (await guard.get("/api/v1/gate-camera")).json() == {"available": True}
    await configure(admin, gate, cameras[0], enabled=False, password=None)
    assert (await guard.get("/api/v1/gate-camera")).json() == {"available": False}          # switched off
    await configure(admin, gate, cameras[0], password=None)
    harness.app.state.settings = make_settings(secrets_key=generate_key())                 # key changed
    assert (await guard.get("/api/v1/gate-camera")).json() == {"available": False}          # unreadable
    assert cameras[0].requests == []                                                       # never asked the camera


async def test_not_available_before_the_guard_has_chosen_a_gate(admin, guard, cameras):
    a = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()["id"]
    await admin.post("/api/v1/gates", json={"name": "East Gate"})
    await configure(admin, a, cameras[0])
    assert (await guard.get("/api/v1/gate-camera")).json() == {"available": False}
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert r.status_code == 404 and r.json()["error"]["code"] == "gate_camera_unavailable"
    assert cameras[0].requests == []


async def test_availability_says_nothing_about_the_camera(admin, guard, cameras):
    await one_gate_with_camera(admin, cameras[0])
    r = await guard.get("/api/v1/gate-camera")
    assert r.json() == {"available": True}
    for secret in (PASSWORD, USER, "127.0.0.1", str(cameras[0].port)):
        assert secret not in r.text


# ---------------------------------------------------------------- snapshot: a preview, never stored
async def test_snapshot_is_a_preview_and_stores_nothing(harness, settings, admin, guard, cameras):
    await one_gate_with_camera(admin, cameras[0])
    visitor = await new_visitor(guard)
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "no-store" in r.headers["cache-control"]
    assert await picture_size(r) == (1024, 576)                        # checked and scaled like a visitor photo
    assert await harness.db.photos.count_documents({}) == 0
    assert (await harness.db.visitors.find_one({"_id": ObjectId(visitor["id"])})).get("current_photo_id") is None
    assert not settings.photo_dir.exists() or not any(settings.photo_dir.rglob("*.jpg"))
    assert await harness.db.audit_logs.count_documents({"action": "PHOTO_CAPTURED"}) == 0
    for secret in (PASSWORD, USER, "127.0.0.1"):
        assert secret not in r.headers.values() and secret.encode() not in r.content


async def test_use_this_photo_goes_through_the_normal_visitor_photo_upload(harness, admin, guard, cameras,
                                                                          directory):  # noqa: F811 - fixture
    await configure(admin, directory["gate"]["id"], cameras[0])
    visitor = await new_visitor(guard)
    preview = await guard.post("/api/v1/gate-camera/snapshot")
    uploaded = await guard.post(f"/api/v1/visitors/{visitor['id']}/photo", content=preview.content,
                                headers={"Content-Type": "image/jpeg"})
    assert uploaded.status_code == 201, uploaded.text
    photo = uploaded.json()
    assert (photo["width"], photo["height"]) == (1024, 576)
    assert await harness.db.photos.count_documents({}) == 1
    assert (await harness.db.visitors.find_one({"_id": ObjectId(visitor["id"])}))["current_photo_id"] == \
        ObjectId(photo["id"])
    assert await harness.db.audit_logs.count_documents({"action": "PHOTO_CAPTURED"}) == 1
    visit = await check_in(guard, visitor["id"], directory, photo_id=photo["id"])
    assert visit.status_code == 201 and visit.json()["photo_id"] == photo["id"]


# ---------------------------------------------------------------- the browser cannot choose the camera
async def test_the_camera_is_the_one_of_the_sessions_gate_whatever_the_request_says(admin, guard, cameras):
    a = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()["id"]
    b = (await admin.post("/api/v1/gates", json={"name": "East Gate"})).json()["id"]
    await configure(admin, a, cameras[0])
    await configure(admin, b, cameras[1])
    assert (await guard.put("/api/v1/auth/session/gate", json={"gate_id": a})).status_code == 200

    for attempt in (
        guard.post("/api/v1/gate-camera/snapshot"),
        guard.post(f"/api/v1/gate-camera/snapshot?gate_id={b}&host=127.0.0.1&port={cameras[1].port}&channel=101"),
        guard.post("/api/v1/gate-camera/snapshot", json={"gate_id": b, "host": "127.0.0.1", "port": cameras[1].port}),
    ):
        r = await attempt
        assert r.status_code == 200 and await picture_size(r) == (1024, 576)          # gate A's camera
    assert cameras[1].requests == []                                                   # gate B's never asked
    assert (await guard.post(f"/api/v1/gate-cameras/{b}/test-photo")).status_code == 403   # admin route: refused

    # Only choosing another gate for the session (audited, as before) changes the camera.
    assert (await guard.put("/api/v1/auth/session/gate", json={"gate_id": b})).status_code == 200
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert await picture_size(r) == (800, 800) and cameras[1].requests              # gate B, never upscaled


async def test_signed_out_requests_are_refused(harness, admin, cameras):
    await one_gate_with_camera(admin, cameras[0])
    anonymous = harness.client()
    assert (await anonymous.get("/api/v1/gate-camera")).status_code == 401
    assert (await anonymous.post("/api/v1/gate-camera/snapshot")).status_code in (401, 403)
    assert cameras[0].requests == []


# ---------------------------------------------------------------- failures: safe messages, nothing stored
@pytest.mark.parametrize("setup, code", [
    (lambda cam: setattr(cam, "delay", 3), "camera_timeout"),
    (lambda cam: cam.routes.pop(SNAPSHOT), "camera_not_found"),
    (lambda cam: cam.routes.update({SNAPSHOT: (200, "application/xml", XML_ERROR)}), "camera_invalid_response"),
    (lambda cam: cam.routes.update({SNAPSHOT: (200, "image/jpeg", jpeg()[:2000])}), "camera_invalid_image"),
    (lambda cam: cam.routes.update({SNAPSHOT: (200, "image/jpeg", jpeg((4100, 3000)))}), "camera_image_unusable"),
])
async def test_camera_failures_are_safe_errors(harness, admin, guard, cameras, setup, code):
    await one_gate_with_camera(admin, cameras[0])
    setup(cameras[0])
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert r.status_code == 502 and r.json()["error"]["code"] == code
    for secret in (PASSWORD, USER, "127.0.0.1", "Traceback"):
        assert secret not in r.text
    assert await harness.db.photos.count_documents({}) == 0


async def test_wrong_password_is_a_safe_error(admin, guard, cameras):
    await one_gate_with_camera(admin, cameras[0], password="Wrong-Pass-9")
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert r.status_code == 502 and r.json()["error"]["code"] == "camera_authentication_failed"
    assert "Wrong-Pass-9" not in r.text


async def test_an_unreachable_camera_is_a_safe_error(admin, guard, cameras):
    await one_gate_with_camera(admin, cameras[0])
    cameras[0].shutdown()
    cameras[0].server_close()
    r = await guard.post("/api/v1/gate-camera/snapshot")
    # Windows retries a refused connection for about 2 s, so the 2 s timeout may come first: both are right.
    assert r.status_code == 502 and r.json()["error"]["code"] in ("camera_unavailable", "camera_timeout")


async def test_a_disabled_camera_is_not_used(admin, guard, cameras):
    await one_gate_with_camera(admin, cameras[0], enabled=False)
    r = await guard.post("/api/v1/gate-camera/snapshot")
    assert r.status_code == 404 and r.json()["error"]["code"] == "gate_camera_unavailable"
    assert cameras[0].requests == []
