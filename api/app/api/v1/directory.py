"""Gates, departments and hosts. Anyone signed in may read (pickers); only admins change them."""
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_database, request_meta, require
from app.core.permissions import Permission, has_permission
from app.db.client import Database
from app.schemas.directory import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    GateCreate,
    GateOut,
    GateUpdate,
    HostCreate,
    HostOut,
    HostUpdate,
)
from app.services import directory as svc
from app.services.auth import AuthContext

read = require(Permission.DIRECTORY_READ)
manage = require(Permission.DIRECTORY_MANAGE)


def _include_inactive(ctx: AuthContext, requested: bool) -> bool:
    # Inactive entries are only listed for administrators (the management screens).
    return requested and has_permission(ctx.user.get("role"), Permission.DIRECTORY_MANAGE)


# ---------------------------------------------------------------- gates
gates = APIRouter(prefix="/gates", tags=["directory"])


@gates.get("", response_model=list[GateOut])
async def list_gates(include_inactive: bool = False, ctx: AuthContext = Depends(read),
                     database: Database = Depends(get_database)) -> list[GateOut]:
    docs = await svc.list_items(database.db, svc.GATE, include_inactive=_include_inactive(ctx, include_inactive))
    return [GateOut.from_doc(d) for d in docs]


@gates.post("", response_model=GateOut, status_code=201)
async def create_gate(body: GateCreate, request: Request, ctx: AuthContext = Depends(manage),
                      database: Database = Depends(get_database)) -> GateOut:
    return GateOut.from_doc(await svc.create(database.db, svc.GATE, ctx, request_meta(request), body.model_dump()))


@gates.patch("/{gate_id}", response_model=GateOut)
async def update_gate(gate_id: str, body: GateUpdate, request: Request, ctx: AuthContext = Depends(manage),
                      database: Database = Depends(get_database)) -> GateOut:
    doc = await svc.update(database.db, svc.GATE, ctx, request_meta(request), gate_id, body.model_dump())
    return GateOut.from_doc(doc)


# ---------------------------------------------------------------- departments
departments = APIRouter(prefix="/departments", tags=["directory"])


@departments.get("", response_model=list[DepartmentOut])
async def list_departments(include_inactive: bool = False, ctx: AuthContext = Depends(read),
                           database: Database = Depends(get_database)) -> list[DepartmentOut]:
    docs = await svc.list_items(database.db, svc.DEPARTMENT,
                                include_inactive=_include_inactive(ctx, include_inactive))
    return [DepartmentOut.from_doc(d) for d in docs]


@departments.post("", response_model=DepartmentOut, status_code=201)
async def create_department(body: DepartmentCreate, request: Request, ctx: AuthContext = Depends(manage),
                            database: Database = Depends(get_database)) -> DepartmentOut:
    doc = await svc.create(database.db, svc.DEPARTMENT, ctx, request_meta(request), body.model_dump())
    return DepartmentOut.from_doc(doc)


@departments.patch("/{department_id}", response_model=DepartmentOut)
async def update_department(department_id: str, body: DepartmentUpdate, request: Request,
                            ctx: AuthContext = Depends(manage),
                            database: Database = Depends(get_database)) -> DepartmentOut:
    doc = await svc.update(database.db, svc.DEPARTMENT, ctx, request_meta(request), department_id, body.model_dump())
    return DepartmentOut.from_doc(doc)


# ---------------------------------------------------------------- hosts
hosts = APIRouter(prefix="/hosts", tags=["directory"])


async def _hosts_out(database: Database, docs: list[dict]) -> list[HostOut]:
    names = await svc.department_names(database.db, {d["department_id"] for d in docs if d.get("department_id")})
    return [HostOut.from_doc(d, names.get(d.get("department_id"))) for d in docs]


@hosts.get("", response_model=list[HostOut])
async def list_hosts(q: str | None = Query(default=None, max_length=100), department_id: str | None = None,
                     include_inactive: bool = False, ctx: AuthContext = Depends(read),
                     database: Database = Depends(get_database)) -> list[HostOut]:
    docs = await svc.list_items(database.db, svc.HOST, include_inactive=_include_inactive(ctx, include_inactive),
                                q=q, department_id=department_id)
    return await _hosts_out(database, docs)


@hosts.post("", response_model=HostOut, status_code=201)
async def create_host(body: HostCreate, request: Request, ctx: AuthContext = Depends(manage),
                      database: Database = Depends(get_database)) -> HostOut:
    doc = await svc.create(database.db, svc.HOST, ctx, request_meta(request), body.model_dump())
    return (await _hosts_out(database, [doc]))[0]


@hosts.patch("/{host_id}", response_model=HostOut)
async def update_host(host_id: str, body: HostUpdate, request: Request, ctx: AuthContext = Depends(manage),
                      database: Database = Depends(get_database)) -> HostOut:
    doc = await svc.update(database.db, svc.HOST, ctx, request_meta(request), host_id, body.model_dump())
    return (await _hosts_out(database, [doc]))[0]
