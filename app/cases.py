"""Investigations / case management.

A Case is the investigator's workspace: a named investigation with a subject,
examiner, legal authority and status, to which findings, notes and timeline
events are scoped. The Investigate flow quietly opens/updates a case per subject
so every search is captured as evidence — the depth is there without the user
having to manage it.
"""
from __future__ import annotations

from . import db, files
from .util import audit, now_iso

STATUSES = ("open", "active", "closed", "archived")
PRIORITIES = ("low", "normal", "high", "urgent")
_SCOPED_TABLES = ("findings", "notes", "timeline_events", "accounts",
                  "identity_items", "graph_nodes")


def _counts(cid: int) -> dict:
    def sc(sql: str) -> int:
        row = db.query_one(sql, (cid,))
        return int(list(row)[0]) if row else 0
    return {
        "findings": sc("SELECT COUNT(*) FROM findings WHERE case_id=?"),
        "hits": sc("SELECT COUNT(*) FROM findings WHERE case_id=? AND summary LIKE '%\"found\": true%'"),
        "notes": sc("SELECT COUNT(*) FROM notes WHERE case_id=?"),
        "timeline": sc("SELECT COUNT(*) FROM timeline_events WHERE case_id=?"),
        "files": sc("SELECT COUNT(*) FROM case_files WHERE case_id=?"),
    }


def list_cases(status: str | None = None) -> list[dict]:
    if status:
        rows = db.query("SELECT * FROM cases WHERE status=? ORDER BY updated_at DESC, id DESC",
                        (status,))
    else:
        rows = db.query("SELECT * FROM cases ORDER BY (status='archived') ASC, "
                        "updated_at DESC, id DESC")
    out = []
    for r in rows:
        d = dict(r)
        d["counts"] = _counts(d["id"])
        out.append(d)
    return out


def get_case(cid: int) -> dict | None:
    r = db.query_one("SELECT * FROM cases WHERE id=?", (cid,))
    if not r:
        return None
    d = dict(r)
    d["counts"] = _counts(cid)
    return d


def create_case(title: str | None = None, subject: str | None = None,
                subject_type: str | None = None, examiner: str | None = None,
                authority: str | None = None, priority: str = "normal") -> dict:
    ts = now_iso()
    title = (title or "").strip() or (subject or "Untitled investigation")
    priority = priority if priority in PRIORITIES else "normal"
    cid = db.execute(
        "INSERT INTO cases (title, subject, subject_type, status, priority, examiner, "
        "authority, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (title, subject, subject_type, "open", priority, examiner, authority, ts, ts),
    )
    ref = f"GFM-{ts[:4]}-{cid:04d}"
    db.execute("UPDATE cases SET ref=? WHERE id=?", (ref, cid))
    audit("audit", "case", "case opened", case_id=cid, ref=ref, subject=subject or "")
    return get_case(cid)  # type: ignore[return-value]


def update_case(cid: int, **fields) -> dict | None:
    allowed = {"title", "subject", "subject_type", "status", "priority",
               "examiner", "authority", "summary"}
    data = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "status" in data and data["status"] not in STATUSES:
        data.pop("status")
    if not data:
        return get_case(cid)
    sets = ",".join(f"{k}=?" for k in data)
    vals = list(data.values()) + [now_iso(), cid]
    n = db.write(f"UPDATE cases SET {sets}, updated_at=? WHERE id=?", vals)
    if not n:
        return None
    if "status" in data:
        audit("audit", "case", f"case {data['status']}", case_id=cid)
    return get_case(cid)


def delete_case(cid: int) -> int:
    # Unlink scoped evidence rather than destroy it, then remove the case shell.
    for t in _SCOPED_TABLES:
        try:
            db.write(f"UPDATE {t} SET case_id=NULL WHERE case_id=?", (cid,))
        except Exception:
            pass
    # Attached files belong to the case: remove them from disk (rows cascade).
    try:
        files.purge_case(cid)
    except Exception:
        pass
    n = db.write("DELETE FROM cases WHERE id=?", (cid,))
    if n:
        audit("audit", "case", "case deleted", case_id=cid)
    return n


def touch(cid: int) -> None:
    db.write("UPDATE cases SET updated_at=? WHERE id=?", (now_iso(), cid))


def find_or_create_for_subject(subject: str, subject_type: str,
                               examiner: str | None = None) -> dict:
    """Reuse an open/active case for this subject, else open a new one."""
    subject = (subject or "").strip()
    r = db.query_one(
        "SELECT id FROM cases WHERE subject=? AND subject_type=? "
        "AND status IN ('open','active') ORDER BY id DESC LIMIT 1",
        (subject, subject_type),
    )
    if r:
        return get_case(r["id"])  # type: ignore[return-value]
    return create_case(title=subject, subject=subject, subject_type=subject_type,
                       examiner=examiner)
