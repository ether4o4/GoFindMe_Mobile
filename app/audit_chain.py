"""Tamper-evident audit trail — an append-only SHA-256 hash chain.

Every security-relevant event (login, vault unlock, tool/provider execution,
case changes, exports) is appended as a row whose hash binds the previous row's
hash. Editing or deleting any historical row breaks the chain from that point
on, which ``verify()`` detects and pinpoints. This gives a court/procurement
grade, self-auditing evidence trail without a second datastore.

The chain never stores secrets — only who/what/when metadata.
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from . import db
from .util import now_iso

GENESIS = "0" * 64

# Appends must be serialized: each one reads the current tip hash, then inserts a
# row binding it. The app is single-process, so a lock is sufficient and correct.
_lock = threading.Lock()


def _row_hash(prev_hash: str, ts: str, actor: str, action: str,
              category: str, detail: str) -> str:
    canonical = "|".join([prev_hash, ts, actor, action, category, detail])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record(action: str, *, actor: str = "system", category: str = "",
           **detail: Any) -> None:
    """Append one event to the tamper-evident chain. Never pass secrets."""
    try:
        det = json.dumps(detail, default=str, sort_keys=True) if detail else ""
        ts = now_iso()
        with _lock:
            tip = db.query_one("SELECT hash FROM audit_chain ORDER BY id DESC LIMIT 1")
            prev = tip["hash"] if tip else GENESIS
            h = _row_hash(prev, ts, actor, action, category, det)
            db.execute(
                "INSERT INTO audit_chain (ts, actor, action, category, detail, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts, actor, action, category, det, prev, h),
            )
    except Exception:
        # The audit path must never break a request.
        pass


def verify() -> dict:
    """Recompute the whole chain and report integrity.

    Returns {ok, count, broken_at, tip}. ``broken_at`` is the id of the first row
    whose stored hash or prev-link disagrees with the recomputation (None if intact).
    """
    rows = db.query(
        "SELECT id, ts, actor, action, category, detail, prev_hash, hash "
        "FROM audit_chain ORDER BY id ASC"
    )
    prev = GENESIS
    for r in rows:
        expect = _row_hash(prev, r["ts"], r["actor"] or "", r["action"] or "",
                           r["category"] or "", r["detail"] or "")
        if r["prev_hash"] != prev or r["hash"] != expect:
            return {"ok": False, "count": len(rows), "broken_at": r["id"], "tip": prev}
        prev = r["hash"]
    return {"ok": True, "count": len(rows), "broken_at": None, "tip": prev}


def recent(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 2000))
    rows = db.query(
        "SELECT id, ts, actor, action, category, detail, hash FROM audit_chain "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        d = dict(r)
        if d.get("detail"):
            try:
                d["detail"] = json.loads(d["detail"])
            except Exception:
                pass
        d["hash_short"] = (d.get("hash") or "")[:12]
        out.append(d)
    return out


def tip_hash() -> str:
    row = db.query_one("SELECT hash FROM audit_chain ORDER BY id DESC LIMIT 1")
    return row["hash"] if row else GENESIS
