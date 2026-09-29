"""E-mail (SMTP) settings, administrators only: Admin → Settings → Email configuration.

Generic SMTP for any provider. The password can be set here but is never returned. Viewing the
settings never connects to a mail server; only the test e-mail does.
"""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.email_settings import EmailSettingsIn, EmailSettingsOut, EmailTestIn, EmailTestOut
from app.services import email as email_svc
from app.services import email_settings as svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/settings/email", tags=["settings"])
manage = require(Permission.SETTINGS_MANAGE)


def _out(doc: dict | None, settings: Settings) -> EmailSettingsOut:
    return EmailSettingsOut.build(doc, svc.source(doc, settings), settings.email_enabled,
                                  svc.password_status(doc, settings) if doc else "NOT_SET")


@router.get("", response_model=EmailSettingsOut)
async def get_email_settings(ctx: AuthContext = Depends(manage), database: Database = Depends(get_database),
                             settings: Settings = Depends(get_settings)) -> EmailSettingsOut:
    return _out(await svc.saved(database.db), settings)


@router.put("", response_model=EmailSettingsOut)
async def save_email_settings(body: EmailSettingsIn, request: Request, ctx: AuthContext = Depends(manage),
                              database: Database = Depends(get_database),
                              settings: Settings = Depends(get_settings)) -> EmailSettingsOut:
    doc = await svc.save(database.db, settings, ctx, request_meta(request), body.model_dump(exclude={"password"}),
                         body.password)
    return _out(doc, settings)


@router.delete("", status_code=204)
async def remove_email_settings(request: Request, ctx: AuthContext = Depends(manage),
                                database: Database = Depends(get_database)) -> Response:
    """Deletes the saved settings and password: the server environment (CG_SMTP_*) applies again."""
    await svc.remove(database.db, ctx, request_meta(request))
    return Response(status_code=204)


@router.post("/test", response_model=EmailTestOut)
async def send_test_email(body: EmailTestIn, request: Request, ctx: AuthContext = Depends(manage),
                          database: Database = Depends(get_database),
                          settings: Settings = Depends(get_settings)) -> EmailTestOut:
    """Sends one test e-mail with the settings in use. A failure is a result, with a safe reason."""
    sent, reason, where = await svc.send_test(database.db, settings, ctx, request_meta(request), body.to)
    return EmailTestOut(status="SENT" if sent else "FAILED", code=reason,
                        message=email_svc.REASON_MESSAGES.get(reason) if reason else None, source=where)
