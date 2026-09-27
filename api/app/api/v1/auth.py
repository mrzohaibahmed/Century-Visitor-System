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
from app.schemas.users import ChangePasswordRequest, GateSelectRequest, LoginRequest, MeResponse
from app.services import auth as auth_service
from app.services.auth import AuthContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse, dependencies=[Depends(public)])
async def login(body: LoginRequest, request: Request, response: Response,
                database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> MeResponse:
    reject_cross_site(request)
    new = await auth_service.login(database.db, settings, body.username, body.password, request_meta(request))
    set_session_cookies(response, settings, new)
    return await _me(database, new.user, new.session, settings)


@router.post("/logout", status_code=204)
async def logout(request: Request, ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
                 database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Response:
    await auth_service.logout(database.db, ctx, request_meta(request))
    response = Response(status_code=204)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=MeResponse)
async def me(ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
             database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> MeResponse:
    return await _me(database, ctx.user, ctx.session, settings)


@router.put("/session/gate", response_model=MeResponse)
async def select_gate(body: GateSelectRequest, request: Request,
                      ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
                      database: Database = Depends(get_database),
                      settings: Settings = Depends(get_settings)) -> MeResponse:
    """The gate this workstation is at (recorded on every check-in / check-out of this session)."""
    await auth_service.select_gate(database.db, ctx, body.gate_id, request_meta(request))
    return await _me(database, ctx.user, ctx.session, settings)


async def _me(database: Database, user: dict, session: dict, settings: Settings) -> MeResponse:
    gate, required = await auth_service.session_gate(database.db, session)
    return MeResponse.build(user, session, settings.session_idle_minutes, gate, required)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordRequest, request: Request,
                          ctx: AuthContext = Depends(require(Permission.ACCOUNT_SELF)),
                          database: Database = Depends(get_database),
                          settings: Settings = Depends(get_settings)) -> Response:
    await auth_service.change_own_password(database.db, settings, ctx, body.current_password, body.new_password,
                                           request_meta(request))
    return Response(status_code=204)
