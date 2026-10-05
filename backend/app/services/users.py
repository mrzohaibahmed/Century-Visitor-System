"""
User administration (Admin only; enforced by the routes' permission checks).

- Accounts are created, never overwritten (unique username, case-insensitive).
- New and reset accounts must change their password at first login.
- Role changes, enabling/disabling and password resets require the acting
  admin's own password.
- The last active admin cannot be demoted or disabled, including when two
  admins act at the same moment (see _claim_admin_guard).
- No hard delete: disabled accounts keep the audit history meaningful.
- Every change and its audit record are written in one transaction.
"""
import asyncio
from datetime import UTC, datetime

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.permissions import Role
from app.core.security import hash_password, password_policy_error
from app.db.transactions import run_in_transaction
from app.repositories import sessions as sessions_repo
from app.repositories import users as users_repo
from app.services import audit
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta, verify_actor_password

NOT_FOUND = AppError(404, "not_found", "User not found.")


def _check_password(password: str, username: str) -> None:
    problem = password_policy_error(password, username)
    if problem:
        raise AppError(422, "weak_password", problem)


async def get_user(db: AsyncDatabase, user_id: str) -> dict:
    oid = users_repo.parse_id(user_id)
    user = await users_repo.find_by_id(db, oid) if oid else None
    if user is None:
        raise NOT_FOUND
    return user


async def create_user(db: AsyncDatabase, *, actor: dict | None, meta: RequestMeta | None, username: str,
                      display_name: str, role: Role, password: str, must_change_password: bool = True,
                      enforce_policy: bool = True, source: str = "cli") -> dict:
    # enforce_policy=False only for the first-run account (app.cli first-admin): its
    # temporary password has to be replaced at the first login, so the policy is never skipped otherwise.
    if enforce_policy or not must_change_password:
        _check_password(password, username)
    password_hash = await asyncio.to_thread(hash_password, password)
    now = datetime.now(UTC)
    doc = {
        "username": username, "display_name": display_name, "role": str(role),
        "password_hash": password_hash, "is_active": True, "must_change_password": must_change_password,
        "failed_login_count": 0, "locked_until": None, "last_login_at": None,
        "password_changed_at": now, "created_at": now, "updated_at": now,
        "created_by": actor["_id"] if actor else None,
    }

    async def work(s: AsyncClientSession):
        doc["_id"] = await users_repo.insert(db, doc, session=s)
        await audit.record(db, AuditAction.USER_CREATED, actor=actor_from_user(actor), ip=meta.ip if meta else None,
                           resource_type="user", resource_id=doc["_id"],
                           changes={"username": username, "display_name": display_name, "role": str(role)},
                           metadata=None if actor else {"source": source}, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:
        raise AppError(409, "username_taken", f"An account named '{username}' already exists.") from None
    return doc


async def _claim_admin_guard(db: AsyncDatabase, s: AsyncClientSession) -> None:
    """Writes one shared document inside the transaction. Two concurrent transactions that
    both reduce the number of admins therefore conflict; the retry sees the other's change."""
    await db.counters.update_one({"_id": "admin_guard"}, {"$inc": {"seq": 1}}, upsert=True, session=s)


async def update_user(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta, user_id: str, *,
                      display_name: str | None, role: Role | None, is_active: bool | None,
                      confirm_password: str | None) -> dict:
    target = await get_user(db, user_id)
    role_change = role is not None and str(role) != target["role"]
    active_change = is_active is not None and is_active != target.get("is_active", False)
    name_change = display_name is not None and display_name != target.get("display_name")
    if not (role_change or active_change or name_change):
        return target

    is_self = target["_id"] == ctx.user["_id"]
    if is_self and (role_change or active_change):
        raise AppError(400, "cannot_modify_self", "You cannot change your own role or disable your own account.")
    if role_change or active_change:
        await verify_actor_password(db, settings, ctx, confirm_password, meta)

    removes_admin = target["role"] == "ADMIN" and target.get("is_active", False) and (
        (role_change and str(role) != "ADMIN") or (active_change and not is_active))
    actor = actor_from_user(ctx.user)

    async def work(s: AsyncClientSession):
        if removes_admin:
            await _claim_admin_guard(db, s)
            if await users_repo.count_active_admins(db, session=s) <= 1:
                raise AppError(409, "last_admin", "At least one active administrator must remain.")
        fields: dict = {}
        if name_change:
            fields["display_name"] = display_name
        if role_change:
            fields["role"] = str(role)
        if active_change:
            fields["is_active"] = is_active
        await users_repo.update_fields(db, target["_id"], fields, session=s)

        common = {"actor": actor, "ip": meta.ip, "resource_type": "user", "resource_id": target["_id"], "session": s}
        if name_change:
            await audit.record(db, AuditAction.USER_UPDATED, **common,
                               changes={"display_name": {"from": target.get("display_name"), "to": display_name}})
        if role_change:
            await audit.record(db, AuditAction.ROLE_CHANGED, **common,
                               changes={"role": {"from": target["role"], "to": str(role)}})
        if active_change:
            if not is_active:
                await sessions_repo.revoke_all_for_user(db, target["_id"], "user_disabled", session=s)
            await audit.record(db, AuditAction.USER_ENABLED if is_active else AuditAction.USER_DISABLED, **common)

    await run_in_transaction(db, work)
    return await get_user(db, user_id)


async def reset_password(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta, user_id: str,
                         new_password: str, confirm_password: str | None) -> None:
    target = await get_user(db, user_id)
    if target["_id"] == ctx.user["_id"]:
        raise AppError(400, "cannot_modify_self", "Use 'Change password' to change your own password.")
    await verify_actor_password(db, settings, ctx, confirm_password, meta)
    _check_password(new_password, target["username"])
    new_hash = await asyncio.to_thread(hash_password, new_password)

    async def work(s: AsyncClientSession):
        await users_repo.update_fields(db, target["_id"], {
            "password_hash": new_hash, "must_change_password": True, "password_changed_at": datetime.now(UTC),
            "failed_login_count": 0, "locked_until": None}, session=s)
        await sessions_repo.revoke_all_for_user(db, target["_id"], "password_reset", session=s)
        await audit.record(db, AuditAction.PASSWORD_RESET, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="user", resource_id=target["_id"], session=s)

    await run_in_transaction(db, work)


async def unlock_user(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, user_id: str) -> dict:
    target = await get_user(db, user_id)

    async def work(s: AsyncClientSession):
        await users_repo.update_fields(db, target["_id"], {"failed_login_count": 0, "locked_until": None}, session=s)
        await audit.record(db, AuditAction.USER_UNLOCKED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="user", resource_id=target["_id"], session=s)

    await run_in_transaction(db, work)
    return await get_user(db, user_id)


def is_locked(user: dict) -> bool:
    locked_until = user.get("locked_until")
    return bool(locked_until and locked_until > datetime.now(UTC))

