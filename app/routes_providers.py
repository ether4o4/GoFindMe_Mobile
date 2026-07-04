"""Provider endpoints: list, test-connection, single lookup."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import orchestrate, providers as prov, security
from .validators import ValidationError, validate
from .vault import vault

router = APIRouter(prefix="/api/providers", tags=["providers"])


class LookupBody(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    type: str | None = None


@router.get("")
async def list_all(_t: str = security.Auth) -> list[dict]:
    return prov.list_providers(set(vault.configured_providers()))


@router.post("/{name}/test")
async def test(name: str, _t: str = security.Auth) -> dict:
    provider = prov.get_provider(name)
    if not provider:
        raise HTTPException(404, "Unknown provider")
    key = None
    if provider.vault_key:
        try:
            key = vault.get_key(provider.vault_key)
        except ValueError:
            raise HTTPException(409, "Vault is locked")
    if provider.requires_key and not key:
        raise HTTPException(400, "No key configured for this provider")
    async with prov.make_client() as client:
        res = await provider.test(client, key)
    return res.to_dict()


@router.post("/{name}/lookup")
async def lookup(name: str, body: LookupBody, _t: str = security.Auth) -> dict:
    provider = prov.get_provider(name)
    if not provider:
        raise HTTPException(404, "Unknown provider")
    ttype = body.type
    if not ttype:
        ttype = next((t for t in provider.input_types
                      if _ok(body.target, t)), None)
    if not ttype or ttype not in provider.input_types:
        raise HTTPException(422, f"{name} does not accept this target type")
    try:
        validate(body.target, ttype)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    return await orchestrate.run_provider(provider, body.target, ttype)


def _ok(target: str, ttype: str) -> bool:
    try:
        validate(target, ttype)
        return True
    except ValidationError:
        return False
