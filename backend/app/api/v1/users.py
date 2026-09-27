"""User administration endpoints (Admin only: Permission.USERS_MANAGE)."""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.client import Database
from app.repositories import users as users_repo
from app.schemas.users import (
    PasswordResetRequest,
    UserCreateRequest,
    UserListResponse,
    UserOut,
    UserUpdateRequest,
)
from app.services import users as users_service
from app.services.auth import AuthContext

router = APIRouter(prefix="/users", tags=["users"])
admin_only = require(Permission.USERS_MANAGE)


@router.get("", response_model=UserListResponse)
async def list_users(ctx: AuthContext = Depends(admin_only),
                     database: Database = Depends(get_database)) -> UserListResponse:
    return UserListResponse(items=[UserOut.from_doc(u) for u in await users_repo.list_all(database.db)])


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateRequest, request: Request, ctx: AuthContext = Depends(admin_only),
                      database: Database = Depends(get_database)) -> UserOut:
    doc = await users_service.create_user(database.db, actor=ctx.user, meta=request_meta(request),
                                          username=body.username, display_name=body.display_name, role=body.role,
                                          password=body.password)
    return UserOut.from_doc(doc)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: str, ctx: AuthContext = Depends(admin_only),
                   database: Database = Depends(get_database)) -> UserOut:
    return UserOut.from_doc(await users_service.get_user(database.db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdateRequest, request: Request,
                      ctx: AuthContext = Depends(admin_only), database: Database = Depends(get_database),
                      settings: Settings = Depends(get_settings)) -> UserOut:
    doc = await users_service.update_user(database.db, settings, ctx, request_meta(request), user_id,
                                          display_name=body.display_name, role=body.role, is_active=body.is_active,
                                          confirm_password=body.confirm_password)
    return UserOut.from_doc(doc)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(user_id: str, body: PasswordResetRequest, request: Request,
                         ctx: AuthContext = Depends(admin_only), database: Database = Depends(get_database),
                         settings: Settings = Depends(get_settings)) -> Response:
    await users_service.reset_password(database.db, settings, ctx, request_meta(request), user_id,
                                       body.new_password, body.confirm_password)
    return Response(status_code=204)


@router.post("/{user_id}/unlock", response_model=UserOut)
async def unlock_user(user_id: str, request: Request, ctx: AuthContext = Depends(admin_only),
                      database: Database = Depends(get_database)) -> UserOut:
    return UserOut.from_doc(await users_service.unlock_user(database.db, ctx, request_meta(request), user_id))
