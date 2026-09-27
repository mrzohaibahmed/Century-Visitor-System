"""
Role-based access control: which role holds which permission.

Mirrors the RBAC table approved in the architecture audit. The backend is the
only place these decisions are made; the frontend merely hides what a role
cannot use.
"""
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    GUARD = "GUARD"


class Permission(StrEnum):
    DASHBOARD_VIEW = "dashboard:view"
    VISIT_CHECK_IN = "visit:check_in"
    VISIT_CHECK_OUT = "visit:check_out"
    VISIT_READ = "visit:read"
    PASS_ISSUE = "pass:issue"                  # noqa: S105 - visitor pass, not a password
    VISITOR_READ = "visitor:read"
    VISITOR_CREATE = "visitor:create"
    VISITOR_EDIT = "visitor:edit"
    DIRECTORY_READ = "directory:read"          # gates, departments, hosts (pickers)
    DIRECTORY_MANAGE = "directory:manage"
    WATCHLIST_MANAGE = "watchlist:manage"
    REPORTS_EXPORT = "reports:export"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"
    SETTINGS_MANAGE = "settings:manage"
    ACCOUNT_SELF = "account:self"              # change own password, view own profile


_GUARD = frozenset({
    Permission.DASHBOARD_VIEW, Permission.VISIT_CHECK_IN, Permission.VISIT_CHECK_OUT, Permission.VISIT_READ,
    Permission.PASS_ISSUE, Permission.VISITOR_READ, Permission.VISITOR_CREATE, Permission.DIRECTORY_READ,
    Permission.ACCOUNT_SELF,
})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.GUARD: _GUARD,
    Role.ADMIN: frozenset(Permission),
}


def has_permission(role: Role | str | None, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except (ValueError, KeyError):
        return False
