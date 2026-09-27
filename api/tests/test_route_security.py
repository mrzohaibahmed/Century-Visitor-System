"""Every route must declare its access rule; protected routes fail closed."""
import pytest
from fastapi import Depends
from fastapi.routing import APIRoute

from app.api.deps import public, require
from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission
from app.main import create_app


def api_routes(app):
    """(methods, path, dependant) for every endpoint, including those in included routers.

    FastAPI 0.14x keeps included routers as wrapper objects instead of flattening them into
    app.routes; their effective routes (with the router-level dependencies merged in) are
    reached through effective_route_contexts().
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield sorted(route.methods), route.path, route.dependant
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                yield sorted(getattr(ctx.original_route, "methods", ())), ctx.path, ctx.dependant


def _dependency_calls(dependant):
    stack, found = list(dependant.dependencies), []
    while stack:
        dep = stack.pop()
        found.append(dep.call)
        stack.extend(dep.dependencies)
    return found


def test_route_discovery_finds_the_endpoints(settings):
    """Guards the next test against passing vacuously (it once did, after a FastAPI change)."""
    paths = {path for _, path, _ in api_routes(create_app(settings))}
    assert {"/api/v1/health/live", "/api/v1/health/ready"} <= paths


def test_every_route_declares_public_or_a_permission(settings):
    missing = []
    for methods, path, dependant in api_routes(create_app(settings)):
        calls = _dependency_calls(dependant)
        is_public = public in calls
        permissions = [c for c in calls if hasattr(c, "required_permission")]
        if is_public == bool(permissions):          # neither, or both (ambiguous)
            missing.append(f"{methods} {path}")
    assert missing == [], f"Routes without exactly one access rule: {missing}"


def test_public_routes_are_exactly_the_allow_list(settings):
    """Adding a public endpoint must be a deliberate change to this list."""
    public_paths = sorted(path for _, path, dependant in api_routes(create_app(settings))
                          if public in _dependency_calls(dependant))
    assert public_paths == ["/api/v1/auth/login", "/api/v1/health/live", "/api/v1/health/ready"]


@pytest.mark.anyio
async def test_protected_routes_reject_requests_without_a_session(settings, client_for):
    app = create_app(settings)

    @app.get("/api/v1/_test/admin-only", dependencies=[Depends(require(Permission.USERS_MANAGE))])
    async def admin_only():
        return {"secret": "data"}

    async for client in client_for(app):
        r = await client.get("/api/v1/_test/admin-only")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated" and "secret" not in r.text


def test_admin_holds_every_permission():
    assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Permission)


@pytest.mark.parametrize("permission", [
    Permission.WATCHLIST_MANAGE, Permission.REPORTS_EXPORT, Permission.USERS_MANAGE, Permission.AUDIT_READ,
    Permission.SETTINGS_MANAGE, Permission.DIRECTORY_MANAGE, Permission.VISITOR_EDIT,
])
def test_guard_lacks_admin_permissions(permission):
    assert has_permission(Role.GUARD, permission) is False


@pytest.mark.parametrize("permission", [
    Permission.DASHBOARD_VIEW, Permission.VISIT_CHECK_IN, Permission.VISIT_CHECK_OUT,
    Permission.VISITOR_CREATE, Permission.DIRECTORY_READ, Permission.ACCOUNT_SELF,
])
def test_guard_has_gate_permissions(permission):
    assert has_permission(Role.GUARD, permission) is True


@pytest.mark.parametrize("role", [None, "", "admin", "SUPERUSER"])
def test_unknown_roles_have_no_permissions(role):
    assert has_permission(role, Permission.DASHBOARD_VIEW) is False
