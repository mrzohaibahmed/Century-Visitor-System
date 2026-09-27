"""Watchlist management. Administrators only (watchlist:manage); screening at check-in is in visits."""
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_database, request_meta, require
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.common import Page
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistCreated,
    WatchlistDisable,
    WatchlistOut,
    WatchlistStatus,
    WatchlistUpdate,
)
from app.services import watchlist as svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
manage = require(Permission.WATCHLIST_MANAGE)


@router.get("", response_model=Page[WatchlistOut])
async def list_entries(q: str | None = Query(default=None, max_length=100), status: WatchlistStatus | None = None,
                       cursor: str | None = None, ctx: AuthContext = Depends(manage),
                       database: Database = Depends(get_database)) -> Page[WatchlistOut]:
    docs, next_cursor = await svc.list_entries(database.db, q=q, status=status, cursor=cursor)
    return Page[WatchlistOut](items=[WatchlistOut.from_doc(d) for d in docs], next_cursor=next_cursor)


@router.post("", response_model=WatchlistCreated, status_code=201)
async def add_entry(body: WatchlistCreate, request: Request, ctx: AuthContext = Depends(manage),
                    database: Database = Depends(get_database)) -> WatchlistCreated:
    doc, inside = await svc.create(database.db, ctx, request_meta(request), identity=body.identity.model_dump(
        mode="json"), name=body.name, reason=body.reason, expires_at=body.expires_at)
    return WatchlistCreated(**WatchlistOut.from_doc(doc).model_dump(), inside_visit_number=inside)


@router.get("/{entry_id}", response_model=WatchlistOut)
async def get_entry(entry_id: str, ctx: AuthContext = Depends(manage),
                    database: Database = Depends(get_database)) -> WatchlistOut:
    return WatchlistOut.from_doc(await svc.get(database.db, entry_id))


@router.patch("/{entry_id}", response_model=WatchlistOut)
async def update_entry(entry_id: str, body: WatchlistUpdate, request: Request, ctx: AuthContext = Depends(manage),
                       database: Database = Depends(get_database)) -> WatchlistOut:
    doc = await svc.update(database.db, ctx, request_meta(request), entry_id, name=body.name, reason=body.reason,
                           expires_at=body.expires_at, clear_expiry=body.clear_expiry)
    return WatchlistOut.from_doc(doc)


@router.post("/{entry_id}/expire", response_model=WatchlistOut)
async def expire_entry(entry_id: str, request: Request, ctx: AuthContext = Depends(manage),
                       database: Database = Depends(get_database)) -> WatchlistOut:
    return WatchlistOut.from_doc(await svc.expire(database.db, ctx, request_meta(request), entry_id))


@router.post("/{entry_id}/disable", response_model=WatchlistOut)
async def disable_entry(entry_id: str, body: WatchlistDisable, request: Request, ctx: AuthContext = Depends(manage),
                        database: Database = Depends(get_database)) -> WatchlistOut:
    return WatchlistOut.from_doc(await svc.disable(database.db, ctx, request_meta(request), entry_id, body.note))
