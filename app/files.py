"""Case file attachments (evidence uploads).

Investigators attach evidence files — screenshots, exports, documents — to a
case. Files are stored on disk under the uploads dir, one folder per case, with
a generated on-disk name so the client-supplied filename never touches the
filesystem path (no traversal, no collisions). Metadata lives in the
``case_files`` table; uploaded files also surface as nodes on the case
relationship graph (see ``graph.build_for_case``).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path

from . import db
from .config import settings
from .util import audit, now_iso

# Strip everything but a short alphanumeric extension (readability only).
_EXT_RE = re.compile(r"[^A-Za-z0-9]")
# Path separators and control chars can never appear in the stored display name.
_NAME_CTRL_RE = re.compile(r"[\x00-\x1f\x7f/\\]")


def _case_dir(cid: int) -> Path:
    d = settings().uploads_dir / f"case_{cid}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_ext(filename: str) -> str:
    ext = _EXT_RE.sub("", Path(filename or "").suffix.lstrip("."))[:12]
    return ("." + ext.lower()) if ext else ""


def _display_name(filename: str) -> str:
    name = _NAME_CTRL_RE.sub("_", (filename or "").strip()).strip()
    return (name or "file")[:200]


def save(cid: int, filename: str, content: bytes, content_type: str | None,
         label: str | None = None) -> dict:
    """Persist one uploaded file for a case and record its metadata."""
    stored = uuid.uuid4().hex + _safe_ext(filename)
    (_case_dir(cid) / stored).write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    display = _display_name(filename)
    fid = db.execute(
        "INSERT INTO case_files (case_id, filename, stored_name, content_type, size, "
        "sha256, label, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (cid, display, stored, (content_type or "")[:120], len(content), sha,
         (label or None), now_iso()),
    )
    audit("audit", "case", "file attached", case_id=cid, file_id=fid,
          filename=display, size=len(content), sha256=sha)
    return get(cid, fid)  # type: ignore[return-value]


def list_files(cid: int) -> list[dict]:
    rows = db.query(
        "SELECT id, case_id, filename, content_type, size, sha256, label, created_at "
        "FROM case_files WHERE case_id=? ORDER BY id DESC", (cid,))
    return [dict(r) for r in rows]


def get(cid: int, fid: int) -> dict | None:
    r = db.query_one("SELECT * FROM case_files WHERE id=? AND case_id=?", (fid, cid))
    return dict(r) if r else None


def path_for(cid: int, fid: int) -> Path | None:
    """Resolve a stored file to an on-disk path, guarding against traversal."""
    r = get(cid, fid)
    if not r:
        return None
    base = _case_dir(cid).resolve()
    p = (base / r["stored_name"]).resolve()
    if p.parent != base or not p.is_file():   # never escape the case folder
        return None
    return p


def delete(cid: int, fid: int) -> bool:
    r = get(cid, fid)
    if not r:
        return False
    try:
        (_case_dir(cid) / r["stored_name"]).unlink(missing_ok=True)
    except Exception:
        pass
    db.write("DELETE FROM case_files WHERE id=? AND case_id=?", (fid, cid))
    audit("audit", "case", "file removed", case_id=cid, file_id=fid, filename=r["filename"])
    return True


def purge_case(cid: int) -> None:
    """Remove every stored file + row for a case (used on case delete)."""
    shutil.rmtree(_case_dir(cid), ignore_errors=True)
    db.write("DELETE FROM case_files WHERE case_id=?", (cid,))
