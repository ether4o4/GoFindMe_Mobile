"""Tamper-evident audit-trail endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from . import audit_chain, security

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def recent(limit: int = 200, _t: str = security.Auth) -> dict:
    return {"entries": audit_chain.recent(limit), "integrity": audit_chain.verify()}


@router.get("/verify")
async def verify(_t: str = security.Auth) -> dict:
    return audit_chain.verify()
