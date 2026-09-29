"""Hikvision ISAPI client (services/gate_camera.py) against a fake camera on 127.0.0.1.

The fake camera is a real HTTP server that checks Digest answers the way a camera does, so a wrong
computation fails the test. No physical camera, no database.
"""
import hashlib
import io
import logging
import os
import re
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image
from pydantic import SecretStr

from app.services.gate_camera import (
    DEVICE_INFO_PATH,
    CameraConfig,
    CameraError,
    CameraErrorCode,
    GateCameraClient,
)

USER, PASSWORD, REALM = "vms-snapshot", "S3cret-Cam-Pass!", "IP Camera(K1234)"

DEVICE_INFO = b"""<?xml version="1.0" encoding="UTF-8"?>
<DeviceInfo version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <deviceName>Main Gate Desk</deviceName>
  <deviceID>48-4a-11</deviceID>
  <model>DS-2CD2143G2-I</model>
  <serialNumber>DS-2CD2143G2-I20240101AAWRK12345678</serialNumber>
  <macAddress>44:47:cc:00:11:22</macAddress>
  <firmwareVersion>V5.7.15</firmwareVersion>
  <firmwareReleasedDate>build 240101</firmwareReleasedDate>
</DeviceInfo>"""


def jpeg(size=(1280, 720)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (90, 120, 150)).save(out, format="JPEG", quality=90)
    return out.getvalue()


def _h(algorithm: str, text: str) -> str:
    base = algorithm.upper().removesuffix("-SESS")
    return (hashlib.sha256 if base == "SHA-256" else hashlib.md5)(text.encode()).hexdigest()


class FakeCamera(ThreadingHTTPServer):
    """Answers like a Hikvision camera. Tests change the attributes to simulate faults."""

    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.algorithm = "MD5"
        self.qop: str | None = "auth"
        self.offer = "digest"                       # "digest", "basic" (Basic only) or "none" (no login)
        self.stale_first = False                    # reject the first correct answer as stale
        self.routes: dict[str, tuple[int, str, bytes]] = {
            DEVICE_INFO_PATH: (200, "application/xml", DEVICE_INFO),
            "/ISAPI/Streaming/channels/101/picture": (200, "image/jpeg", jpeg()),
        }
        self.delay = 0.0                            # seconds before answering
        self.drip = 0.0                             # seconds between body bytes
        self.short_body = False                     # announce more bytes than are sent
        self.requests: list[dict] = []
        self._nonces = 0

    @property
    def port(self) -> int:
        return self.server_address[1]

    def new_nonce(self) -> str:
        self._nonces += 1
        return f"nonce{self._nonces:04d}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeCamera

    def log_message(self, *args):                  # keep test output quiet
        pass

    def do_GET(self):  # noqa: N802
        cam = self.server
        auth = self.headers.get("Authorization")
        cam.requests.append({"path": self.path, "authorization": auth})
        if cam.delay:
            time.sleep(cam.delay)
        if cam.offer != "none":
            verdict = self._check(auth)
            if verdict != "ok":
                return self._challenge(stale=verdict == "stale")
        status, ctype, body = cam.routes.get(self.path, (404, "application/xml", b"<ResponseStatus/>"))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if status in (301, 302):
            self.send_header("Location", "http://example.invalid/")
        self.send_header("Content-Length", str(len(body) + (1000 if cam.short_body else 0)))
        self.end_headers()
        if cam.drip:
            for i in range(len(body)):
                self.wfile.write(body[i:i + 1])
                self.wfile.flush()
                time.sleep(cam.drip)
        else:
            self.wfile.write(body)

    def _challenge(self, stale=False):
        cam = self.server
        self.send_response(401)
        if cam.offer == "basic":
            self.send_header("WWW-Authenticate", f'Basic realm="{REALM}"')
        else:
            qop = f', qop="{cam.qop}"' if cam.qop else ""
            self.send_header("WWW-Authenticate",
                             f'Digest realm="{REALM}", nonce="{cam.new_nonce()}", algorithm={cam.algorithm}'
                             f'{qop}, opaque="op4que"{", stale=TRUE" if stale else ""}')
            self.send_header("WWW-Authenticate", f'Basic realm="{REALM}"')
        body = b'<?xml version="1.0"?><userCheck><statusValue>401</statusValue></userCheck>'
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check(self, auth: str | None) -> str:
        cam = self.server
        if not auth or not auth.startswith("Digest "):
            return "missing"
        p = dict(re.findall(r'(\w+)="?([^",]*)"?', auth[7:]))
        if p.get("username") != USER or p.get("realm") != REALM or p.get("uri") != self.path:
            return "wrong"
        if p.get("opaque") != "op4que" or p.get("algorithm") != cam.algorithm:
            return "wrong"
        ha1 = _h(cam.algorithm, f"{USER}:{REALM}:{PASSWORD}")
        if cam.algorithm.upper().endswith("-SESS"):
            ha1 = _h(cam.algorithm, f"{ha1}:{p['nonce']}:{p['cnonce']}")
        ha2 = _h(cam.algorithm, f"GET:{self.path}")
        if cam.qop:
            if p.get("qop") != "auth" or not p.get("nc") or not p.get("cnonce"):
                return "wrong"
            expected = _h(cam.algorithm, f"{ha1}:{p['nonce']}:{p['nc']}:{p['cnonce']}:auth:{ha2}")
        else:
            expected = _h(cam.algorithm, f"{ha1}:{p['nonce']}:{ha2}")
        if p.get("response") != expected:
            return "wrong"
        if cam.stale_first:
            cam.stale_first = False
            return "stale"
        return "ok"


@pytest.fixture
def camera():
    server = FakeCamera()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def client(camera: FakeCamera, *, password=PASSWORD, channel=101, timeout=2.0, protocol="http") -> GateCameraClient:
    return GateCameraClient(CameraConfig(host="127.0.0.1", port=camera.port, protocol=protocol, username=USER,
                                         password=SecretStr(password), channel=channel, timeout=timeout))


def failure(fn) -> CameraError:
    with pytest.raises(CameraError) as caught:
        fn()
    return caught.value


# ---------------------------------------------------------------- 1. device information
def test_device_info_returns_only_model_firmware_and_name(camera):
    info = client(camera).get_device_info()
    assert (info.model, info.firmware, info.device_name) == ("DS-2CD2143G2-I", "V5.7.15", "Main Gate Desk")
    assert not hasattr(info, "serial_number") and "44:47" not in repr(info)     # no serial or MAC address


def test_device_info_must_be_a_device_info_document(camera):
    error_xml = b"<ResponseStatus><statusCode>4</statusCode></ResponseStatus>"
    camera.routes[DEVICE_INFO_PATH] = (200, "application/xml", error_xml)
    assert failure(client(camera).get_device_info).code is CameraErrorCode.INVALID_RESPONSE
    camera.routes[DEVICE_INFO_PATH] = (200, "text/html", b"<html>login</html")
    assert failure(client(camera).get_device_info).code is CameraErrorCode.INVALID_RESPONSE


def test_device_info_with_entity_declarations_is_refused(camera):
    bomb = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><DeviceInfo><model>&a;</model></DeviceInfo>'
    camera.routes[DEVICE_INFO_PATH] = (200, "application/xml", bomb)
    assert failure(client(camera).get_device_info).code is CameraErrorCode.INVALID_RESPONSE


# ---------------------------------------------------------------- 2. snapshot
def test_snapshot_returns_the_camera_jpeg_unchanged(camera):
    shot = client(camera).capture_snapshot()
    assert shot.data == camera.routes["/ISAPI/Streaming/channels/101/picture"][2]           # not re-encoded
    assert (shot.width, shot.height, shot.content_type) == (1280, 720, "image/jpeg")
    assert "data" not in repr(shot)                                                         # bytes kept out of repr


# ---------------------------------------------------------------- 3. Digest authentication
@pytest.mark.parametrize("algorithm, qop", [("MD5", "auth"), ("MD5", None), ("MD5-sess", "auth"),
                                            ("SHA-256", "auth"), ("SHA-256", "auth,auth-int")])
def test_digest_login(camera, algorithm, qop):
    camera.algorithm, camera.qop = algorithm, qop
    client(camera).capture_snapshot()
    first, second = camera.requests
    assert first["authorization"] is None                                  # the password is never sent unasked
    assert second["authorization"].startswith("Digest ") and PASSWORD not in second["authorization"]


def test_a_stale_nonce_is_answered_once_more(camera):
    camera.stale_first = True
    client(camera).capture_snapshot()
    assert len(camera.requests) == 3


def test_a_camera_without_login_is_accepted(camera):
    camera.offer = "none"
    client(camera).capture_snapshot()
    assert len(camera.requests) == 1


# ---------------------------------------------------------------- 4. authentication failure
def test_a_wrong_password_costs_exactly_one_login_attempt(camera):
    # Hikvision locks the account after a few failures: never retry a refused password.
    error = failure(client(camera, password="wrong-password").capture_snapshot)
    assert (error.code, error.status) == (CameraErrorCode.AUTHENTICATION_FAILED, 401)
    assert len(camera.requests) == 2 and sum(r["authorization"] is not None for r in camera.requests) == 1


def test_basic_only_is_refused_without_sending_the_password(camera):
    camera.offer = "basic"
    assert failure(client(camera).capture_snapshot).code is CameraErrorCode.AUTHENTICATION_FAILED
    assert [r["authorization"] for r in camera.requests] == [None]


def test_an_unsupported_digest_algorithm_is_refused(camera):
    camera.algorithm = "SHA-512-256"
    assert failure(client(camera).capture_snapshot).code is CameraErrorCode.AUTHENTICATION_FAILED
    assert len(camera.requests) == 1


# ---------------------------------------------------------------- 5. connection failure
def test_nothing_listening_is_unavailable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]                   # closed again: nothing listens there
    cfg = CameraConfig(host="127.0.0.1", port=port, protocol="http", username=USER, password=SecretStr(PASSWORD))
    assert failure(GateCameraClient(cfg).get_device_info).code is CameraErrorCode.UNAVAILABLE


def test_https_to_a_plain_http_camera_fails_cleanly(camera):
    error = failure(client(camera, protocol="https").get_device_info)
    assert error.code is CameraErrorCode.UNAVAILABLE


def test_https_always_verifies_certificate_and_host_name(camera):
    conn = client(camera, protocol="https")._connection(1.0)
    assert conn._context.verify_mode == ssl.CERT_REQUIRED and conn._context.check_hostname


# ---------------------------------------------------------------- 6. timeout
def test_a_camera_that_does_not_answer_times_out(camera):
    camera.delay = 1.5
    started = time.monotonic()
    assert failure(client(camera, timeout=0.5).capture_snapshot).code is CameraErrorCode.TIMEOUT
    assert time.monotonic() - started < 1.2


def test_a_camera_answering_byte_by_byte_cannot_hold_the_request(camera):
    camera.offer = "none"
    camera.drip = 0.01                               # ~20 KB JPEG at 100 bytes/s: minutes without the deadline
    started = time.monotonic()
    assert failure(client(camera, timeout=0.5).capture_snapshot).code is CameraErrorCode.TIMEOUT
    assert time.monotonic() - started < 1.2


# ---------------------------------------------------------------- 7. HTTP errors
@pytest.mark.parametrize("status, code", [(500, CameraErrorCode.HTTP_ERROR), (403, CameraErrorCode.HTTP_ERROR),
                                          (503, CameraErrorCode.HTTP_ERROR), (302, CameraErrorCode.HTTP_ERROR),
                                          (404, CameraErrorCode.NOT_FOUND)])
def test_http_errors(camera, status, code):
    camera.routes["/ISAPI/Streaming/channels/101/picture"] = (status, "application/xml", b"<ResponseStatus/>")
    error = failure(client(camera).capture_snapshot)
    assert (error.code, error.status) == (code, status)
    assert all("example.invalid" not in r["path"] for r in camera.requests)       # redirects are not followed


# ---------------------------------------------------------------- 8. not an image
@pytest.mark.parametrize("ctype, body", [
    ("application/xml", b"<ResponseStatus><statusString>Device Busy</statusString></ResponseStatus>"),
    ("image/jpeg", b"<html><body>Error</body></html>"),              # says JPEG, is not
    ("", b"plain text"),
    ("image/png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64),
])
def test_a_200_answer_that_is_not_a_jpeg_is_refused(camera, ctype, body):
    camera.routes["/ISAPI/Streaming/channels/101/picture"] = (200, ctype, body)
    error = failure(client(camera).capture_snapshot)
    assert error.code is CameraErrorCode.INVALID_RESPONSE


# ---------------------------------------------------------------- 9. malformed JPEG
@pytest.mark.parametrize("body", [
    jpeg()[:3000],                                   # cut off
    b"\xff\xd8\xff\xe0" + b"\0" * 200,               # JPEG signature, garbage after
])
def test_a_jpeg_that_cannot_be_decoded_is_refused(camera, body):
    camera.routes["/ISAPI/Streaming/channels/101/picture"] = (200, "image/jpeg", body)
    assert failure(client(camera).capture_snapshot).code is CameraErrorCode.INVALID_IMAGE


def test_a_body_shorter_than_announced_is_a_failed_snapshot(camera):
    camera.short_body = True
    assert failure(client(camera).capture_snapshot).code is CameraErrorCode.SNAPSHOT_FAILED


def test_a_too_large_snapshot_is_refused(camera, monkeypatch):
    monkeypatch.setattr("app.services.gate_camera.MAX_SNAPSHOT_BYTES", 10_000)
    assert failure(client(camera).capture_snapshot).code is CameraErrorCode.SNAPSHOT_FAILED


# ---------------------------------------------------------------- 10. the configured channel
def test_the_configured_channel_is_requested(camera):
    camera.routes["/ISAPI/Streaming/channels/201/picture"] = (200, "image/jpeg", jpeg((640, 480)))
    shot = client(camera, channel=201).capture_snapshot()
    assert (shot.width, shot.height) == (640, 480)
    assert {r["path"] for r in camera.requests} == {"/ISAPI/Streaming/channels/201/picture"}


def test_a_channel_the_camera_does_not_have_is_not_found(camera):
    assert failure(client(camera, channel=1).capture_snapshot).code is CameraErrorCode.NOT_FOUND
    assert camera.requests[-1]["path"] == "/ISAPI/Streaming/channels/1/picture"


# ---------------------------------------------------------------- 11. secrets never leak
def test_the_password_and_authorization_never_appear_in_logs_errors_or_reprs(camera, caplog):
    caplog.set_level(logging.DEBUG)
    errors = []
    for setup, password in [(lambda: None, "wrong-" + PASSWORD), (lambda: setattr(camera, "delay", 1.0), PASSWORD),
                            (lambda: camera.routes.pop("/ISAPI/Streaming/channels/101/picture"), PASSWORD)]:
        camera.delay = 0
        setup()
        c = client(camera, password=password, timeout=0.5)
        errors.append(failure(c.capture_snapshot))
        assert PASSWORD not in repr(c) and PASSWORD not in repr(c._config) and PASSWORD not in str(c._config)
    for error in errors:
        text = " ".join([str(error), repr(error), error.message, repr(error.args)])
        assert PASSWORD not in text and "Digest" not in text and "127.0.0.1" not in text
        assert error.__cause__ is None                                          # no chained low-level exception
        assert error.__context__ is None or error.__suppress_context__
    logged = caplog.text
    assert "CAMERA_" in logged                                                  # failures are logged, as codes
    assert PASSWORD not in logged and "Authorization" not in logged and "response=" not in logged


# ---------------------------------------------------------------- 12. nothing written to disk
def test_a_snapshot_is_never_written_to_disk(camera):
    cam_client = client(camera)
    cam_client.capture_snapshot()                    # warm-up: lazy imports may write .pyc files
    writes, watching = [], [True]

    def hook(event, args):
        if event == "open" and watching[0]:
            path, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or \
                    (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND)):
                writes.append(path)

    sys.addaudithook(hook)                           # cannot be removed; switched off below
    try:
        shot = cam_client.capture_snapshot()
    finally:
        watching[0] = False
    assert shot.data and writes == []


# ---------------------------------------------------------------- configuration
@pytest.mark.parametrize("change", [
    {"host": "http://192.0.2.10"}, {"host": "192.0.2.10:80"}, {"host": "user:pw@192.0.2.10"}, {"host": ""},
    {"host": "cam/ISAPI"}, {"protocol": "rtsp"}, {"port": 0}, {"port": 70000}, {"channel": 0},
    {"timeout": 0}, {"timeout": 60}, {"username": ""}, {"username": 'a"b'},
])
def test_invalid_configuration_is_refused(change):
    values = {"host": "192.0.2.10", "username": USER, "password": SecretStr(PASSWORD)} | change
    with pytest.raises(ValueError):
        CameraConfig(**values)


def test_valid_hosts_and_default_ports():
    for host in ("192.0.2.10", "cam-gate1.century.local", "fe80::1"):
        CameraConfig(host=host, username=USER, password=SecretStr(PASSWORD))
    assert CameraConfig(host="cam", username=USER, password=SecretStr("x")).effective_port == 443
    assert CameraConfig(host="cam", username=USER, password=SecretStr("x"), protocol="http").effective_port == 80
