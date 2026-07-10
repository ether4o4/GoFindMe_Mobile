"""Personal-footprint data layer: generic CRUD over an allowlisted set of tables,
plus settings and logs. Table and column names come only from the server-defined
config below; all values are parameterized.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Body, HTTPException

from . import db, security
from .util import now_iso

router = APIRouter(prefix="/api", tags=["data"])


@dataclass
class Resource:
    path: str
    table: str
    fields: list[str]
    required: list[str]
    has_updated: bool = False


RESOURCES = [
    Resource("identity", "identity_items",
             ["kind", "value", "label", "notes", "is_primary", "case_id"], ["kind", "value"]),
    Resource("accounts", "accounts",
             ["service", "identity_item_id", "url", "status", "recovery_email",
              "recovery_phone", "has_2fa", "recovery_status", "last_verified", "notes", "case_id"],
             ["service"]),
    Resource("timeline", "timeline_events",
             ["event_type", "ref_table", "ref_id", "occurred_at", "title", "detail", "case_id"],
             ["event_type", "title"]),
    Resource("notes", "notes", ["ref_table", "ref_id", "body", "case_id"], ["body"], has_updated=True),
    Resource("graph/nodes", "graph_nodes",
             ["node_type", "label", "ref_table", "ref_id", "case_id"], ["node_type", "label"]),
    Resource("graph/edges", "graph_edges",
             ["src_id", "dst_id", "relation"], ["src_id", "dst_id", "relation"]),
]


def _list_filtered(table: str, case_id: int | None):
    if case_id is not None:
        return db.query(f"SELECT * FROM {table} WHERE case_id=? ORDER BY id DESC", (case_id,))
    return db.query(f"SELECT * FROM {table} ORDER BY id DESC")


def _clean(res: Resource, data: dict) -> dict:
    out = {k: data[k] for k in res.fields if k in data}
    missing = [k for k in res.required if not out.get(k) and out.get(k) != 0]
    if missing:
        raise HTTPException(422, f"Missing required: {', '.join(missing)}")
    return out


def _make_routes(res: Resource) -> None:
    base = f"/{res.path}"

    @router.get(base, name=f"list_{res.table}")
    async def _list(case_id: int | None = None, _t: str = security.Auth) -> list[dict]:
        return [dict(r) for r in _list_filtered(res.table, case_id)]

    @router.post(base, name=f"create_{res.table}")
    async def _create(payload: dict = Body(...), _t: str = security.Auth) -> dict:
        data = _clean(res, payload)
        cols = list(data.keys()) + ["created_at"]
        vals = list(data.values()) + [now_iso()]
        placeholders = ",".join("?" * len(cols))
        try:
            rid = db.execute(
                f"INSERT INTO {res.table} ({','.join(cols)}) VALUES ({placeholders})", vals)
        except Exception as exc:
            raise HTTPException(409, f"Insert failed: {exc}")
        return dict(db.query_one(f"SELECT * FROM {res.table} WHERE id=?", (rid,)))

    @router.get(base + "/{rid}", name=f"get_{res.table}")
    async def _get(rid: int, _t: str = security.Auth) -> dict:
        row = db.query_one(f"SELECT * FROM {res.table} WHERE id=?", (rid,))
        if not row:
            raise HTTPException(404, "Not found")
        return dict(row)

    @router.put(base + "/{rid}", name=f"update_{res.table}")
    async def _update(rid: int, payload: dict = Body(...), _t: str = security.Auth) -> dict:
        data = {k: payload[k] for k in res.fields if k in payload}
        if not data:
            raise HTTPException(422, "No updatable fields supplied")
        sets = [f"{k}=?" for k in data]
        vals = list(data.values())
        if res.has_updated:
            sets.append("updated_at=?")
            vals.append(now_iso())
        vals.append(rid)
        n = db.write(f"UPDATE {res.table} SET {','.join(sets)} WHERE id=?", vals)
        if not n:
            raise HTTPException(404, "Not found")
        return dict(db.query_one(f"SELECT * FROM {res.table} WHERE id=?", (rid,)))

    @router.delete(base + "/{rid}", name=f"delete_{res.table}")
    async def _delete(rid: int, _t: str = security.Auth) -> dict:
        n = db.write(f"DELETE FROM {res.table} WHERE id=?", (rid,))
        if not n:
            raise HTTPException(404, "Not found")
        return {"ok": True}


for _r in RESOURCES:
    _make_routes(_r)


# --- settings ---
@router.get("/settings", tags=["settings"])
async def get_settings(_t: str = security.Auth) -> dict:
    return {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings")}


@router.put("/settings/{key}", tags=["settings"])
async def put_setting(key: str, value: str = Body(..., embed=True),
                      _t: str = security.Auth) -> dict:
    db.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now_iso()))
    return {"ok": True, "key": key, "value": value}


# --- logs (read-only) ---
@router.get("/logs", tags=["logs"])
async def get_logs(level: str | None = None, category: str | None = None,
                   limit: int = 200, _t: str = security.Auth) -> list[dict]:
    sql = "SELECT * FROM logs"
    where, params = [], []
    if level:
        where.append("level=?")
        params.append(level)
    if category:
        where.append("category=?")
        params.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 1000))
    return [dict(r) for r in db.query(sql, params)]
