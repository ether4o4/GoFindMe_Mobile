"""Test fixtures. Env is set BEFORE importing app.* because config binds env at
import time. Each test session gets an isolated temp DB.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gofindme-test-")
os.environ.setdefault("GOFINDME_DB", os.path.join(_TMP, "test.db"))
os.environ.setdefault("GOFINDME_UPLOADS_DIR", os.path.join(_TMP, "uploads"))
os.environ.setdefault("GOFINDME_VAULT_MODE", "encrypted")
os.environ.setdefault("GOFINDME_MAX_CONCURRENCY", "2")
os.environ.setdefault("GOFINDME_TOKEN_TTL_DAYS", "1")

import pathlib  # noqa: E402

import pytest  # noqa: E402
import httpx  # noqa: E402

from app import db, jobs  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.vault import vault  # noqa: E402


def _wipe_db():
    base = settings().db_path
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(base) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture
async def client():
    _wipe_db()
    vault.lock()
    db.init_db()
    await jobs.start_queue()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await jobs.stop_queue()


@pytest.fixture
async def auth_client(client):
    """A client that has completed setup and is logged in."""
    await client.post("/api/auth/setup", json={"username": "owner", "password": "passw0rd!"})
    # setup auto-logs in and returns a token; capture it from the response.
    r = await client.post("/api/auth/login", json={"username": "owner", "password": "passw0rd!"})
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
