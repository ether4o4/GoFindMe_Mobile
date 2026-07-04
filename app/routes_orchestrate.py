"""Detection, Search-All fan-out, and findings read endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import cases, orchestrate, security
from .validators import ValidationError, detect_types

router = APIRouter(prefix="/api", tags=["orchestrate"])


class Target(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    type: str | None = None


class Investigate(Target):
    examiner: str | None = None


@router.post("/detect")
async def detect(body: Target, _t: str = security.Auth) -> dict:
    return orchestrate.detect(body.target)


@router.post("/search-all")
async def search_all(body: Target, _t: str = security.Auth) -> dict:
    try:
        return orchestrate.search_all(body.target, body.type)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))


@router.post("/investigate")
async def investigate(body: Investigate, _t: str = security.Auth) -> dict:
    """One-click investigation: open (or reuse) a Case for this subject, then run
    the full scoped Search-All so every investigation is captured as evidence."""
    target = body.target.strip()
    ttype = body.type or (detect_types(target)[0] if detect_types(target) else None)
    if not ttype:
        raise HTTPException(422, "Could not detect a target type; pick one explicitly.")
    case = cases.find_or_create_for_subject(target, ttype, examiner=body.examiner)
    try:
        res = orchestrate.search_all(target, ttype, case_id=case["id"])
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    res["case"] = case
    return res


@router.get("/findings")
async def findings(target: str, type: str | None = None, _t: str = security.Auth) -> list[dict]:
    return orchestrate.findings_for(target, type)
