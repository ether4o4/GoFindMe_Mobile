"""Job endpoints: list, get, cancel, and SSE live-output stream."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from . import jobs, security

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(parent: str | None = None, status: str | None = None,
                    limit: int = 100, _t: str = security.Auth) -> list[dict]:
    return jobs.list_jobs(parent=parent, status=status, limit=min(limit, 500))


@router.get("/{job_id}")
async def get_job(job_id: str, _t: str = security.Auth) -> dict:
    d = jobs.job_dict(job_id)
    if not d:
        raise HTTPException(404, "No such job")
    return d


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, _t: str = security.Auth) -> dict:
    ok = jobs.get_queue().cancel(job_id)
    return {"ok": ok}


@router.get("/{job_id}/stream")
async def stream(job_id: str, _t: str = security.Auth) -> StreamingResponse:
    queue = jobs.get_queue()

    async def gen():
        async for event in queue.subscribe(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })
