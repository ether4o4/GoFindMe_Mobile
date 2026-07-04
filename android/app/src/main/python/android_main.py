"""Android entry point.

Called from MainActivity with the app's private data dir. Sets the runtime
config via environment (so app.config picks it up at import), then runs the
GoFindMe FastAPI server with uvicorn on a background event loop.
"""
from __future__ import annotations

import os
import threading


def start(data_dir: str) -> None:
    os.environ.setdefault("GOFINDME_DB", os.path.join(data_dir, "gofindme.db"))
    os.environ.setdefault("GOFINDME_UPLOADS_DIR", os.path.join(data_dir, "uploads"))
    os.environ.setdefault("GOFINDME_BIND", "127.0.0.1")
    os.environ.setdefault("GOFINDME_VAULT_MODE", "encrypted")
    # No package managers on the phone — disable tool install/update.
    os.environ.setdefault("GOFINDME_ALLOW_TOOL_MGMT", "0")

    threading.Thread(target=_serve, name="gofindme-server", daemon=True).start()


def _serve() -> None:
    import asyncio

    import uvicorn
    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning",
                            loop="asyncio", lifespan="on")
    server = uvicorn.Server(config)
    # Signal handlers can't be installed off the main thread.
    server.install_signal_handlers = lambda: None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())
