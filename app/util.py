"""Small shared helpers: timestamps, ANSI stripping, audit logging."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from . import db

# CSI / OSC / other escape sequences, plus stray control chars (keep \n and \t).
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def strip_ansi(text: str) -> str:
    """Remove terminal escape sequences and control chars so tool output can't
    corrupt logs or the browser."""
    if not text:
        return text
    return _CTRL_RE.sub("", _ANSI_RE.sub("", text))


def audit(level: str, category: str, message: str, **meta: Any) -> None:
    """Write a structured log row. Never include secrets in meta.

    Security-relevant levels (audit/warn/error) are also appended to the
    tamper-evident hash chain (app.audit_chain) for a court-grade evidence trail.
    """
    try:
        db.execute(
            "INSERT INTO logs (ts, level, category, message, meta) VALUES (?,?,?,?,?)",
            (now_iso(), level, category, message, json.dumps(meta) if meta else None),
        )
    except Exception:
        # Logging must never break the request path.
        pass
    if level in ("audit", "warn", "error"):
        try:
            from . import audit_chain  # lazy import avoids a circular dependency
            audit_chain.record(message, actor=str(meta.get("username", "system")),
                               category=category, **meta)
        except Exception:
            pass


def jdumps(obj: Any, cap: int | None = None) -> str | None:
    if obj is None:
        return None
    s = json.dumps(obj, default=str)
    if cap and len(s) > cap:
        s = s[:cap] + '..."[truncated]"'
    return s
