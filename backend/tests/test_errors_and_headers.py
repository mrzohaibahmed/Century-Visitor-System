import logging

import pytest
from fastapi import Depends
from pydantic import BaseModel

from app.api.deps import public
from app.main import create_app

pytestmark = pytest.mark.anyio


class Body(BaseModel):
    password: str
    count: int


def app_with_test_routes(settings):
    app = create_app(settings)

    @app.get("/api/v1/_test/boom", dependencies=[Depends(public)])
    async def boom():
        raise RuntimeError("internal detail: mongodb://u:Secret-9@host")

    @app.post("/api/v1/_test/echo", dependencies=[Depends(public)])
    async def echo(body: Body):
        return {"ok": True}

    return app


async def test_security_headers_on_every_response(client):
    r = await client.get("/api/v1/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]


async def test_request_id_generated_and_returned(client):
    r = await client.get("/api/v1/health/live")
    assert len(r.headers["x-request-id"]) == 32


async def test_well_formed_incoming_request_id_is_reused(client):
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "gate1-abcdef123456"})
    assert r.headers["x-request-id"] == "gate1-abcdef123456"


async def test_malformed_incoming_request_id_is_replaced(client):
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline" and len(r.headers["x-request-id"]) == 32


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/api/v1/does-not-exist")
    body = r.json()
    assert r.status_code == 404
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == r.headers["x-request-id"]


async def test_unexpected_error_is_logged_but_not_revealed(settings, client_for, caplog):
    caplog.set_level(logging.ERROR)
    async for client in client_for(app_with_test_routes(settings)):
        r = await client.get("/api/v1/_test/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in r.text and "Traceback" not in r.text
    assert "internal detail" in caplog.text        # the log keeps the technical detail


async def test_validation_errors_never_echo_submitted_values(settings, client_for):
    async for client in client_for(app_with_test_routes(settings)):
        r = await client.post("/api/v1/_test/echo", json={"password": "Hunter2-Secret", "count": "many"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert {"field": "body.count", "message": body["error"]["details"][0]["message"]} in body["error"]["details"]
    assert "Hunter2-Secret" not in r.text and "many" not in r.text


async def test_access_log_has_path_but_not_query_string(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    await client.get("/api/v1/health/live?cnic=35201-1234567-1")
    record = next(r for r in caplog.records if r.name == "app.access")
    assert record.path == "/api/v1/health/live" and record.status == 200
    # Only the API's own records matter (the test client, httpx, logs the URL it requested).
    api_records = [r for r in caplog.records if r.name.startswith("app")]
    assert all("35201" not in r.getMessage() and "35201" not in str(r.__dict__) for r in api_records)
