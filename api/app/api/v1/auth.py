"""Authentication endpoints: login, logout, current user, change own password."""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    clear_session_cookies,
    get_database,
    get_settings,
    public,
    reject_cross_site,
    request_meta,
    require,
    set_session_cookies,
)
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.users import ChangePasswordRequest, LoginRequest, MeResponse
from app.services import auth as auth_service
from app.services.auth import AuthContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse, dependencies=[Depends(public)])
async def login(body: LoginRequest, request: Request, response: Response,
                database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> MeResponse:
    reject_cross_site(request)
    new = await auth_service.login(database.db, settings, body.username, body.password, request_meta(request))
    set_session_cookies(response, settings, new)
    return MeResponse.build(new.user, new.session, settings.session_idle_minutes)


@router.post("/logout", status_code=204)
async def logout(request: Request, ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
                 database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Response:
    await auth_service.logout(database.db, ctx, request_meta(request))
    response = Response(status_code=204)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=MeResponse)
async def me(ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
             settings: Settings = Depends(get_settings)) -> MeResponse:
    return MeResponse.build(ctx.user, ctx.session, settings.session_idle_minutes)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordRequest, request: Request,
                          ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
                          database: Database = Depends(get_database),
                          settings: Settings = Depends(get_settings)) -> Response:
    await auth_service.change_own_password(database.db, settings, ctx, body.current_password, body.new_password,
                                           request_meta(request))
    return Response(status_code=204)
