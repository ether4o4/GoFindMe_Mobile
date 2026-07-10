import asyncio

import pytest


async def test_health_and_auth_gate(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["setup_complete"] is False
    # Protected route without auth → 401.
    assert (await client.get("/api/tools")).status_code == 401


async def test_setup_login_me(client):
    r = await client.post("/api/auth/setup", json={"username": "owner", "password": "passw0rd!"})
    assert r.status_code == 200 and "token" in r.json()
    # Setup is one-time.
    assert (await client.post("/api/auth/setup",
                              json={"username": "x", "password": "yyyyyyyy"})).status_code == 409
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    me = await client.get("/api/me")
    assert me.json()["username"] == "owner"


async def test_tools_unavailable_and_run(auth_client):
    tools = (await auth_client.get("/api/tools")).json()
    names = {t["name"] for t in tools}
    assert "sherlock" in names
    assert all(t["available"] is False for t in tools)  # none installed in CI

    run = await auth_client.post("/api/tools/sherlock/run", json={"target": "johndoe"})
    assert run.status_code == 200
    jid = run.json()["job_id"]

    for _ in range(50):
        job = (await auth_client.get(f"/api/jobs/{jid}")).json()
        if job["status"] in ("error", "done", "timeout", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert job["status"] == "error"
    assert job["error"] == "tool_not_installed"


async def test_run_rejects_bad_target(auth_client):
    r = await auth_client.post("/api/tools/sherlock/run", json={"target": "a b; rm"})
    assert r.status_code == 422


async def test_vault_roundtrip(auth_client):
    st = (await auth_client.get("/api/vault/status")).json()
    assert st["mode"] == "encrypted" and st["unlocked"] is False
    assert (await auth_client.post("/api/vault/unlock",
                                   json={"passphrase": "openme"})).status_code == 200
    await auth_client.put("/api/vault/keys/shodan", json={"value": "secret-key"})
    st2 = (await auth_client.get("/api/vault/status")).json()
    assert "shodan" in st2["configured_providers"]
    provs = (await auth_client.get("/api/providers")).json()
    assert any(p["name"] == "shodan" and p["configured"] for p in provs)


async def test_identity_crud(auth_client):
    created = (await auth_client.post("/api/identity",
                                      json={"kind": "email", "value": "me@example.com"})).json()
    assert created["id"]
    listing = (await auth_client.get("/api/identity")).json()
    assert any(i["value"] == "me@example.com" for i in listing)
    assert (await auth_client.delete(f"/api/identity/{created['id']}")).status_code == 200


async def test_detect_and_search_all(auth_client):
    d = (await auth_client.post("/api/detect", json={"target": "me@example.com"})).json()
    assert d["candidate_types"][0] == "email"
    s = (await auth_client.post("/api/search-all", json={"target": "johndoe"})).json()
    assert "parent_job_id" in s
    assert s["type"] == "username"
    assert isinstance(s["tool_jobs"], list)


async def test_custom_tool_lifecycle(auth_client):
    body = {"name": "mytool", "bin": "true", "accepts": ["username"],
            "run_template": "{bin} -u {target}", "install_method": "none"}
    r = await auth_client.post("/api/tools/custom", json=body)
    assert r.status_code == 200
    assert any(t["name"] == "mytool" for t in (await auth_client.get("/api/tools")).json())
    assert (await auth_client.delete("/api/tools/custom/mytool")).status_code == 200


async def test_reports_export(auth_client):
    await auth_client.post("/api/identity", json={"kind": "username", "value": "johndoe"})
    md = await auth_client.get("/api/reports/export?target=johndoe&format=md")
    assert md.status_code == 200 and "GoFindMe Report" in md.text
