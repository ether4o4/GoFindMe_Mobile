"""Vault endpoints: status, unlock/lock, key set/delete."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import security
from .vault import vault

router = APIRouter(prefix="/api/vault", tags=["vault"])


class Passphrase(BaseModel):
    passphrase: str = Field(min_length=1, max_length=512)


class KeyValue(BaseModel):
    value: str = Field(min_length=1, max_length=4096)


@router.get("/status")
async def status(_t: str = security.Auth) -> dict:
    return vault.status()


@router.post("/unlock")
async def unlock(body: Passphrase, _t: str = security.Auth) -> dict:
    try:
        vault.unlock(body.passphrase)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    return vault.status()


@router.post("/lock")
async def lock(_t: str = security.Auth) -> dict:
    vault.lock()
    return vault.status()


@router.put("/keys/{provider}")
async def set_key(provider: str, body: KeyValue, _t: str = security.Auth) -> dict:
    try:
        vault.set_key(provider, body.value)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "provider": provider}


@router.delete("/keys/{provider}")
async def delete_key(provider: str, _t: str = security.Auth) -> dict:
    vault.delete_key(provider)
    return {"ok": True, "provider": provider}
