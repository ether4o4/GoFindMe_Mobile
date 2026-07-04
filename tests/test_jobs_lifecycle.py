"""Regression tests for the job-engine fixes: parent lifecycle, cancellation,
and SSE streams that terminate (no hang) on finished jobs.
"""
import asyncio
import shutil

import pytest


async def _wait_status(client, jid, want, tries=100, delay=0.1):
    for _ in range(tries):
        j = (await client.get(f"/api/jobs/{jid}")).json()
        if j["status"] in want:
            return j
        await asyncio.sleep(delay)
    return (await client.get(f"/api/jobs/{jid}")).json()


async def test_search_all_parent_reaches_done(auth_client):
    # No OSINT tools installed and no keyed providers → parent should finalize fast.
    r = (await auth_client.post("/api/search-all", json={"target": "johndoe"})).json()
    parent = r["parent_job_id"]
    j = await _wait_status(auth_client, parent, {"done", "error"})
    assert j["status"] == "done", f"parent stuck at {j['status']}"


@pytest.mark.skipif(shutil.which("sleep") is None, reason="needs /bin/sleep")
async def test_cancel_kills_running_job(auth_client):
    # A custom tool that sleeps, so we can cancel a genuinely-running process.
    await auth_client.post("/api/tools/custom", json={
        "name": "sleeper", "bin": "sleep", "accepts": ["username"],
        "run_template": "{bin} {target}", "install_method": "none"})
    jid = (await auth_client.post("/api/tools/sleeper/run", json={"target": "9"})).json()["job_id"]
    await _wait_status(auth_client, jid, {"running"})
    assert (await auth_client.post(f"/api/jobs/{jid}/cancel")).json()["ok"] is True
    j = await _wait_status(auth_client, jid, {"cancelled", "done", "error"}, tries=40)
    assert j["status"] == "cancelled"


async def test_stream_of_finished_job_terminates(auth_client):
    # Run a not-installed tool (errors immediately), then stream it: the SSE
    # generator must replay + close, never hang.
    jid = (await auth_client.post("/api/tools/sherlock/run",
                                  json={"target": "johndoe"})).json()["job_id"]
    await _wait_status(auth_client, jid, {"error", "done", "timeout"})

    async def consume():
        events = []
        async with auth_client.stream("GET", f"/api/jobs/{jid}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    events.append(line)
        return events

    events = await asyncio.wait_for(consume(), timeout=5)
    assert any('"status"' in e for e in events)
