"""Tool endpoints: list, run, and management (version/install/update + custom)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import jobs, security, tools
from .config import settings
from .validators import ValidationError, validate

router = APIRouter(prefix="/api/tools", tags=["tools"])


class RunBody(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    type: str | None = None


class CustomTool(BaseModel):
    name: str
    bin: str
    run_template: str
    accepts: list[str] = []
    categories: list[str] = []
    install_method: str = "none"
    install_ref: str | None = None
    version_cmd: str | None = None
    timeout_s: int = 180
    auto_runnable: bool = True
    interactive: bool = False
    notes: str | None = None


def _model_dict(m) -> dict:
    """pydantic v2/v1 compatible dump (the Android build pins pydantic v1)."""
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()


def _require_mgmt() -> None:
    if not settings().allow_tool_mgmt:
        raise HTTPException(403, "Tool management is disabled (GOFINDME_ALLOW_TOOL_MGMT=0)")


@router.get("")
async def list_all(_t: str = security.Auth) -> list[dict]:
    return tools.list_tools()


@router.get("/managers")
async def managers(_t: str = security.Auth) -> dict:
    return {
        "allowed": settings().allow_tool_mgmt,
        "available": {m: tools.manager_available(m) for m in ("pip", "pipx", "go", "git", "npm")},
    }


@router.post("/custom")
async def upsert_custom(body: CustomTool, _t: str = security.Auth) -> dict:
    try:
        spec = tools.upsert_custom_tool(_model_dict(body))
    except tools.ManageError as exc:
        raise HTTPException(400, str(exc))
    except ValidationError as exc:
        raise HTTPException(400, str(exc))
    return tools.tool_view(spec)


@router.delete("/custom/{name}")
async def delete_custom(name: str, _t: str = security.Auth) -> dict:
    if not tools.delete_custom_tool(name):
        raise HTTPException(404, "No such custom tool")
    return {"ok": True}


@router.post("/update-all")
async def update_all(_t: str = security.Auth) -> dict:
    _require_mgmt()
    started = []
    for spec in tools.registry().values():
        if spec.install_method == "none" or not tools.manager_available(spec.install_method):
            continue
        if tools.resolve_bin(spec.bin) is None:
            continue  # only update what's installed
        started.append({"name": spec.name, "job_id": jobs.get_queue().enqueue_manage("update", spec)})
    return {"started": started}


@router.post("/{name}/run")
async def run(name: str, body: RunBody, _t: str = security.Auth) -> dict:
    spec = tools.get_spec(name)
    if not spec:
        raise HTTPException(404, "Unknown tool")
    if spec.interactive or not spec.auto_runnable:
        raise HTTPException(400, f"{name} is interactive/GUI and cannot be auto-run")
    if "image" in spec.accepts and len(spec.accepts) == 1:
        raise HTTPException(501, "File/metadata tools need an uploaded file (planned)")
    ttype = body.type or next((t for t in spec.accepts if _ok(body.target, t)), None)
    if not ttype:
        raise HTTPException(422, f"{body.target!r} is not valid input for {name}")
    try:
        validate(body.target, ttype)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    return {"job_id": jobs.get_queue().enqueue_tool(spec, body.target, ttype)}


@router.post("/{name}/version")
async def version(name: str, _t: str = security.Auth) -> dict:
    spec = tools.get_spec(name)
    if not spec:
        raise HTTPException(404, "Unknown tool")
    return {"job_id": jobs.get_queue().enqueue_manage("version", spec)}


@router.post("/{name}/install")
async def install(name: str, _t: str = security.Auth) -> dict:
    _require_mgmt()
    return _manage(name, "install")


@router.post("/{name}/update")
async def update(name: str, _t: str = security.Auth) -> dict:
    _require_mgmt()
    return _manage(name, "update")


def _manage(name: str, action: str) -> dict:
    spec = tools.get_spec(name)
    if not spec:
        raise HTTPException(404, "Unknown tool")
    if spec.install_method == "none":
        raise HTTPException(400, f"{name} has no automated installer; install it manually.")
    if not tools.manager_available(spec.install_method):
        raise HTTPException(400, f"{spec.install_method} is not available on this host")
    return {"job_id": jobs.get_queue().enqueue_manage(action, spec)}


def _ok(target: str, ttype: str) -> bool:
    try:
        validate(target, ttype)
        return True
    except ValidationError:
        return False
