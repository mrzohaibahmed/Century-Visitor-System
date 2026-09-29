"""Gate camera settings API (administrators), with a fake Hikvision camera on 127.0.0.1.

The camera password is encrypted in the `settings` collection and never leaves the server: not in
responses, audit entries, logs or error messages. Tests never store a photo.
"""
import asyncio
import logging
import threading

import bson
import pytest
from bson import ObjectId

from app.core.secrets import generate_key
from app.services import camera_settings as svc
from tests.conftest import make_settings
from tests.test_gate_camera import PASSWORD, USER, FakeCamera, jpeg

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings():
    return make_settings(secrets_key=generate_key())


@pytest.fixture
def fake_camera():
    server = FakeCamera()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def body(camera: FakeCamera, **change) -> dict:
    return {"enabled": True, "host": "127.0.0.1", "protocol": "http", "port": camera.port, "channel": 101,
            "username": USER, "password": PASSWORD, "timeout_seconds": 2} | change


async def new_gate(admin, name="Main Gate") -> str:
    return (await admin.post("/api/v1/gates", json={"name": name})).json()["id"]


async def everything_stored(harness) -> bytes:
    """The raw BSON of every settings document and audit entry."""
    docs = await harness.db.settings.find({}).to_list(None) + await harness.db.audit_logs.find({}).to_list(None)
    return b"".join(bson.encode(d) for d in docs)


# ---------------------------------------------------------------- access
async def test_guards_cannot_see_or_use_camera_settings(admin, guard):
    gate = await new_gate(admin)
    for method, path in [("GET", "/api/v1/gate-cameras"), ("PUT", f"/api/v1/gate-cameras/{gate}"),
                         ("DELETE", f"/api/v1/gate-cameras/{gate}"), ("POST", f"/api/v1/gate-cameras/{gate}/test"),
                         ("POST", f"/api/v1/gate-cameras/{gate}/test-photo")]:
        r = await guard.request(method, path, json={} if method == "PUT" else None)
        assert r.status_code == 403, (method, path)


async def test_every_gate_is_listed_with_or_without_a_camera(admin):
    await new_gate(admin, "Main Gate")
    await new_gate(admin, "East Gate")
    listed = (await admin.get("/api/v1/gate-cameras")).json()
    assert [(g["gate_name"], g["configured"], g["password_status"]) for g in listed] == \
        [("East Gate", False, "NOT_SET"), ("Main Gate", False, "NOT_SET")]


# ---------------------------------------------------------------- saving; the password stays on the server
async def test_the_password_is_encrypted_and_never_returned(harness, admin, fake_camera):
    gate = await new_gate(admin)
    r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    assert r.status_code == 200
    saved = r.json()
    assert saved["password_status"] == "SAVED" and saved["configured"] and saved["port"] == fake_camera.port
    assert "password" not in saved and PASSWORD not in r.text
    assert PASSWORD not in (await admin.get("/api/v1/gate-cameras")).text

    doc = await harness.db.settings.find_one({"_id": f"gate_camera:{gate}"})
    assert set(doc["password"]) == {"v", "kid", "nonce", "ct"}
    assert PASSWORD.encode() not in await everything_stored(harness)           # nowhere in plain text
    entry = await harness.db.audit_logs.find_one({"action": "GATE_CAMERA_UPDATED"})
    assert entry["changes"]["password"] == "changed" and entry["changes"]["host"]["to"] == "127.0.0.1"


async def test_the_first_save_needs_a_password(admin, fake_camera):
    gate = await new_gate(admin)
    r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, password=None))
    assert r.status_code == 422 and r.json()["error"]["code"] == "camera_password_required"


async def test_the_password_is_kept_unless_it_would_go_somewhere_else(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    sealed = (await harness.db.settings.find_one({"_id": f"gate_camera:{gate}"}))["password"]

    # Channel, timeout, on/off: the saved password stays.
    r = await admin.put(f"/api/v1/gate-cameras/{gate}",
                        json=body(fake_camera, password=None, channel=201, timeout_seconds=4, enabled=False))
    assert r.status_code == 200 and r.json()["channel"] == 201 and r.json()["password_status"] == "SAVED"
    assert (await harness.db.settings.find_one({"_id": f"gate_camera:{gate}"}))["password"] == sealed

    # Address, connection, port or user name: the password must be entered again.
    for change in ({"host": "192.0.2.50"}, {"protocol": "https"}, {"port": 8080}, {"username": "other"}):
        r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, password=None, **change))
        assert r.status_code == 422 and r.json()["error"]["code"] == "camera_password_required", change
    r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, host="192.0.2.50"))
    assert r.status_code == 200 and r.json()["host"] == "192.0.2.50"


async def test_invalid_settings_are_refused_without_echoing_them(admin, fake_camera):
    gate = await new_gate(admin)
    for change, code in [({"host": "http://192.0.2.1"}, "invalid_camera_settings"),
                         ({"host": "admin:pw@192.0.2.1"}, "invalid_camera_settings"),
                         ({"port": 0}, "validation_error"), ({"protocol": "rtsp"}, "validation_error"),
                         ({"timeout_seconds": 60}, "validation_error"), ({"password": " "}, "validation_error"),
                         ({"password": "x" * 129}, "validation_error"), ({"extra": 1}, "validation_error")]:
        r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, **change))
        assert r.status_code == 422 and r.json()["error"]["code"] == code, change
        assert PASSWORD not in r.text and "x" * 129 not in r.text


async def test_an_unknown_gate_is_not_found(admin, fake_camera):
    r = await admin.put(f"/api/v1/gate-cameras/{ObjectId()}", json=body(fake_camera))
    assert r.status_code == 404


async def test_without_a_server_key_passwords_cannot_be_saved(harness, admin, fake_camera):
    harness.app.state.settings = make_settings(secrets_key=None)
    gate = await new_gate(admin)
    r = await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    assert r.status_code == 503 and r.json()["error"]["code"] == "secrets_key_missing"
    assert await harness.db.settings.find_one({"_id": f"gate_camera:{gate}"}) is None


async def test_a_changed_server_key_makes_the_password_unreadable_not_wrong(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    harness.app.state.settings = make_settings(secrets_key=generate_key())       # key replaced on the server
    assert (await admin.get("/api/v1/gate-cameras")).json()[0]["password_status"] == "UNREADABLE"
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test")
    assert r.status_code == 409 and r.json()["error"]["code"] == "camera_password_unreadable"
    assert fake_camera.requests == []                                              # nothing sent to the camera


async def test_a_password_copied_to_another_gate_does_not_decrypt(harness, admin, fake_camera):
    a, b = await new_gate(admin, "Main Gate"), await new_gate(admin, "East Gate")
    await admin.put(f"/api/v1/gate-cameras/{a}", json=body(fake_camera))
    await admin.put(f"/api/v1/gate-cameras/{b}", json=body(fake_camera, password="Other-Pass-2"))
    sealed = (await harness.db.settings.find_one({"_id": f"gate_camera:{a}"}))["password"]
    await harness.db.settings.update_one({"_id": f"gate_camera:{b}"}, {"$set": {"password": sealed}})
    r = await admin.post(f"/api/v1/gate-cameras/{b}/test")
    assert r.status_code == 409 and r.json()["error"]["code"] == "camera_password_unreadable"


async def test_removing_deletes_the_settings_and_the_password(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    assert (await admin.delete(f"/api/v1/gate-cameras/{gate}")).status_code == 204
    assert await harness.db.settings.find_one({"_id": f"gate_camera:{gate}"}) is None
    assert (await admin.get("/api/v1/gate-cameras")).json()[0]["configured"] is False
    assert (await admin.delete(f"/api/v1/gate-cameras/{gate}")).status_code == 404
    assert await harness.db.audit_logs.count_documents({"action": "GATE_CAMERA_REMOVED"}) == 1


# ---------------------------------------------------------------- connection test
async def test_connection_test_reports_the_camera_and_is_remembered(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test")
    assert r.status_code == 200
    result = r.json()
    assert (result["status"], result["model"], result["firmware"]) == ("CONNECTED", "DS-2CD2143G2-I", "V5.7.15")
    last = (await admin.get("/api/v1/gate-cameras")).json()[0]["last_test"]
    assert last["ok"] is True and last["model"] == "DS-2CD2143G2-I"
    entry = await harness.db.audit_logs.find_one({"action": "GATE_CAMERA_TESTED"})
    assert entry["result"] == "SUCCESS" and entry["metadata"] == {"test": "connection", "code": None}

    # Changing the connection makes the earlier result meaningless.
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, channel=102))
    assert (await admin.get("/api/v1/gate-cameras")).json()[0]["last_test"] is None


async def test_a_failed_test_is_a_result_with_a_safe_message(harness, admin, fake_camera, caplog):
    caplog.set_level(logging.DEBUG)
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, password="Wrong-Pass-9"))
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["code"]) == ("FAILED", "CAMERA_AUTHENTICATION_FAILED")
    assert r.json()["message"] == "The camera refused the user name or password."
    entry = await harness.db.audit_logs.find_one({"action": "GATE_CAMERA_TESTED"})
    assert entry["result"] == "FAILURE" and entry["metadata"]["code"] == "CAMERA_AUTHENTICATION_FAILED"
    assert "Wrong-Pass-9" not in caplog.text and b"Wrong-Pass-9" not in await everything_stored(harness)


async def test_an_unreachable_camera_fails_the_test(admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    fake_camera.shutdown()
    fake_camera.server_close()
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test")
    # Windows retries a refused connection for about 2 s, so the 2 s timeout may come first: both are right.
    assert r.json()["status"] == "FAILED" and r.json()["code"] in ("CAMERA_UNAVAILABLE", "CAMERA_TIMEOUT")


async def test_one_test_per_camera_at_a_time(admin, fake_camera):
    # Hikvision locks accounts after repeated failed logins: never run tests of one camera in parallel.
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    fake_camera.delay = 0.5
    first, second = await asyncio.gather(admin.post(f"/api/v1/gate-cameras/{gate}/test"),
                                         admin.post(f"/api/v1/gate-cameras/{gate}/test"))
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409]
    assert "camera_test_running" in (first.text + second.text)


async def test_an_unconfigured_gate_cannot_be_tested(admin):
    gate = await new_gate(admin)
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test")
    assert r.status_code == 404 and r.json()["error"]["code"] == "camera_not_configured"


# ---------------------------------------------------------------- test photo: checked, returned, never stored
async def test_the_test_photo_is_returned_as_the_vms_would_keep_it_and_not_stored(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    fake_camera.routes["/ISAPI/Streaming/channels/101/picture"] = (200, "image/jpeg", jpeg((2560, 1440)))
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test-photo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8\xff") and "no-store" in r.headers["cache-control"]
    assert (r.headers["x-camera-width"], r.headers["x-camera-height"]) == ("2560", "1440")
    assert (r.headers["x-photo-width"], r.headers["x-photo-height"]) == ("1024", "576")    # the stored size
    assert await harness.db.photos.count_documents({}) == 0
    assert await harness.db.visitors.count_documents({}) == 0
    photo_dir = harness.app.state.settings.photo_dir
    assert not photo_dir.exists() or not any(photo_dir.rglob("*.jpg"))
    entry = await harness.db.audit_logs.find_one({"action": "GATE_CAMERA_TESTED"})
    assert entry["metadata"] == {"test": "photo", "code": None}


async def test_a_picture_too_large_for_the_vms_is_reported(admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    fake_camera.routes["/ISAPI/Streaming/channels/101/picture"] = (200, "image/jpeg", jpeg((4100, 3000)))
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test-photo")
    assert r.status_code == 422 and r.json()["error"]["code"] == "camera_image_unusable"
    assert "too large" in r.json()["error"]["message"]


async def test_a_failed_test_photo_is_an_error_with_a_safe_message(admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera, channel=7))
    r = await admin.post(f"/api/v1/gate-cameras/{gate}/test-photo")
    assert r.status_code == 502 and r.json()["error"]["code"] == "camera_not_found"
    assert r.json()["error"]["message"] == "The camera has no picture on this channel. Check the channel number."
    assert PASSWORD not in r.text


# ---------------------------------------------------------------- the decrypted password stays in memory
async def test_client_for_decrypts_only_in_memory(harness, admin, fake_camera):
    gate = await new_gate(admin)
    await admin.put(f"/api/v1/gate-cameras/{gate}", json=body(fake_camera))
    client = await svc.client_for(harness.db, harness.app.state.settings, ObjectId(gate))
    assert client._config.password.get_secret_value() == PASSWORD
    assert PASSWORD not in repr(client) and PASSWORD not in repr(client._config)
