"""The client-IP trust boundary, end to end: browser socket -> production web server -> FastAPI.

The production web server (frontend/server.mjs) drops every forwarding header a browser sends and
sets X-Forwarded-For to the socket address (frontend/server/forwarding.mjs). These tests run that
REAL module in Node for each simulated browser connection, then send the headers it produced to the
API from a loopback peer, exactly as Next.js's /api/* rewrite does, and check what the API records:
the rate-limit key, the audit record and the session. A browser's own X-Forwarded-For never counts.
"""
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app.core.permissions import Role
from app.db.migrate import apply_schema
from app.main import create_app
from app.services.users import create_user
from tests.conftest import GUARD_PASSWORD, make_settings

NODE = shutil.which("node")
FORWARDING = Path(__file__).resolve().parents[2] / "frontend" / "server" / "forwarding.mjs"
LOGIN = "/api/v1/auth/login"
NEXT_JS_PEER = ("127.0.0.1", 41000)          # the web server's own connection to the API (loopback)

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is needed to run the production web server module")

_SCRIPT = """
import { setClientIdentity } from %s;
const cases = JSON.parse(process.argv[1]);
const out = cases.map(([remoteAddress, rawHeaders]) => {
  const headers = {};
  for (let i = 0; i < rawHeaders.length; i += 2) {
    const name = rawHeaders[i].toLowerCase();
    headers[name] = name in headers ? `${headers[name]}, ${rawHeaders[i + 1]}` : rawHeaders[i + 1];
  }
  const req = { socket: { remoteAddress }, headers, rawHeaders: [...rawHeaders] };
  setClientIdentity(req);
  return req.headers;
});
process.stdout.write(JSON.stringify(out));
"""


def through_web_server(*connections: tuple[str | None, list[str]]) -> list[dict[str, str]]:
    """The headers the production web server passes on, for each (socket address, raw browser headers)."""
    script = _SCRIPT % json.dumps(FORWARDING.as_uri())
    result = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(connections)],  # noqa: S603
                            capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def test_the_web_server_replaces_spoofed_addresses():
    spoofed, none, chain, casing, mapped, gone = through_web_server(
        ("192.168.1.50", ["X-Forwarded-For", "10.10.10.10"]),
        ("192.168.1.50", []),
        ("192.168.1.50", ["X-Forwarded-For", "10.0.0.1, 172.16.0.5, 8.8.8.8"]),
        ("192.168.1.50", ["x-FORWARDED-for", "10.0.0.1", "X-Forwarded-For", "10.0.0.2", "X-Real-IP", "10.0.0.3"]),
        ("::ffff:192.168.1.50", ["X-Forwarded-For", "10.10.10.10"]),
        (None, ["X-Forwarded-For", "10.10.10.10"]),
    )
    for headers in (spoofed, none, chain, casing, mapped):
        assert headers["x-forwarded-for"] == "192.168.1.50"
        assert "x-real-ip" not in headers
    assert "x-forwarded-for" not in gone


@pytest.fixture
async def api(settings):
    """The API as the web server reaches it: every request arrives from the loopback peer."""
    app = create_app(make_settings(mongo_db=settings.mongo_db, login_ip_limit=3))
    async with app.router.lifespan_context(app):
        db = app.state.database.db
        await apply_schema(db)
        await create_user(db, actor=None, meta=None, username="guard1", display_name="Guard", role=Role.GUARD,
                          password=GUARD_PASSWORD, must_change_password=False)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=NEXT_JS_PEER)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, db


async def _login(client, headers, password=GUARD_PASSWORD):
    return await client.post(LOGIN, json={"username": "guard1", "password": password}, headers=headers)


@pytest.mark.anyio
async def test_a_spoofed_address_cannot_forge_the_audit_record_or_session(api):
    client, db = api
    wrong, right = through_web_server(
        ("192.168.1.50", ["X-Forwarded-For", "10.10.10.10"]),
        ("192.168.1.50", ["X-FORWARDED-FOR", "10.0.0.1, 172.16.0.5, 8.8.8.8"]),
    )
    assert (await _login(client, wrong, "Wrong-Password-1")).status_code == 401
    assert (await _login(client, right)).status_code == 200
    failed = await db.audit_logs.find_one({"action": "LOGIN_FAILED"})
    login = await db.audit_logs.find_one({"action": "LOGIN"})
    session = await db.sessions.find_one({})
    assert failed["ip"] == login["ip"] == session["ip"] == "192.168.1.50"
    assert not await db.audit_logs.find_one({"ip": {"$in": ["10.10.10.10", "8.8.8.8", "10.0.0.1"]}})


@pytest.mark.anyio
async def test_rate_limit_identity_is_the_socket_address(api):
    client, db = api
    # Gate PC A (.20) claims to be gate PC B (.21) on every attempt.
    a_as_b, b = through_web_server(
        ("192.168.1.20", ["X-Forwarded-For", "192.168.1.21"]),
        ("192.168.1.21", []),
    )
    for _ in range(3):
        await _login(client, a_as_b, "Wrong-Password-1")
    assert (await _login(client, a_as_b)).status_code == 429               # A's own limit (3) is used up
    assert (await _login(client, b)).status_code == 200                    # B was never charged
    keys = {doc["_id"].rsplit(":", 1)[0]: doc["count"] async for doc in db.rate_limits.find({})}
    assert keys == {"login-ip:192.168.1.20": 4, "login-ip:192.168.1.21": 1}


@pytest.mark.anyio
async def test_without_an_address_the_api_falls_back_to_its_peer(api):
    client, db = api
    (gone,) = through_web_server((None, ["X-Forwarded-For", "10.10.10.10"]))
    assert (await _login(client, gone)).status_code == 200
    assert (await db.sessions.find_one({}))["ip"] == "127.0.0.1"
