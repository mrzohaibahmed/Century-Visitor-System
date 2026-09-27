"""The signed-in user's own notifications (the bell). No user id is ever taken from the request."""
from fastapi import APIRouter, Depends

from app.api.deps import get_database, require
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.notifications import MarkedAllRead, NotificationOut, NotificationPage
from app.services import notifications as svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/notifications", tags=["notifications"])
read = require(Permission.NOTIFICATION_READ)


@router.get("", response_model=NotificationPage)
async def list_notifications(unread_only: bool = False, cursor: str | None = None, ctx: AuthContext = Depends(read),
                             database: Database = Depends(get_database)) -> NotificationPage:
    docs, next_cursor, unread = await svc.list_for_user(database.db, ctx, unread_only=unread_only, cursor=cursor)
    return NotificationPage(items=[NotificationOut.from_doc(d) for d in docs], next_cursor=next_cursor,
                            unread_count=unread)


@router.post("/read-all", response_model=MarkedAllRead)
async def mark_all_read(ctx: AuthContext = Depends(read), database: Database = Depends(get_database)) -> MarkedAllRead:
    marked = await svc.mark_all_read(database.db, ctx)
    return MarkedAllRead(marked=marked, unread_count=0)


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: str, ctx: AuthContext = Depends(read),
                    database: Database = Depends(get_database)) -> NotificationOut:
    return NotificationOut.from_doc(await svc.mark_read(database.db, ctx, notification_id))
