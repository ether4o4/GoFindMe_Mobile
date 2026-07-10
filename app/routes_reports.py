"""Dashboard overview metrics, report export, and honest import placeholders."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from . import db, security
from .util import now_iso

router = APIRouter(prefix="/api", tags=["reports"])


def _scalar(sql: str, params=()) -> int:
    row = db.query_one(sql, params)
    return int(list(row)[0]) if row else 0


@router.get("/overview")
async def overview(_t: str = security.Auth) -> dict:
    accounts_no_2fa = _scalar("SELECT COUNT(*) FROM accounts WHERE has_2fa IS NULL OR has_2fa=0")
    breached = db.query(
        "SELECT DISTINCT target FROM findings WHERE source_name='hibp' AND summary LIKE '%\"found\": true%'")
    return {
        "cases": _scalar("SELECT COUNT(*) FROM cases"),
        "cases_open": _scalar("SELECT COUNT(*) FROM cases WHERE status IN ('open','active')"),
        "identity_items": _scalar("SELECT COUNT(*) FROM identity_items"),
        "accounts": _scalar("SELECT COUNT(*) FROM accounts"),
        "accounts_without_2fa": accounts_no_2fa,
        "timeline_events": _scalar("SELECT COUNT(*) FROM timeline_events"),
        "findings": _scalar("SELECT COUNT(*) FROM findings"),
        "breached_emails": [r["target"] for r in breached],
        "jobs_total": _scalar("SELECT COUNT(*) FROM jobs"),
        "jobs_running": _scalar("SELECT COUNT(*) FROM jobs WHERE status='running'"),
    }


@router.get("/analytics")
async def analytics(_t: str = security.Auth) -> dict:
    """Real, computed metrics for the dashboard charts (no fabricated numbers)."""
    total_f = _scalar("SELECT COUNT(*) FROM findings")
    hits = _scalar("SELECT COUNT(*) FROM findings WHERE summary LIKE '%\"found\": true%'")
    by_source = [
        {"label": r["source_name"], "value": int(r["c"])}
        for r in db.query("SELECT source_name, COUNT(*) c FROM findings "
                          "GROUP BY source_name ORDER BY c DESC LIMIT 12")
    ]
    by_type = [
        {"label": r["target_type"], "value": int(r["c"])}
        for r in db.query("SELECT target_type, COUNT(*) c FROM findings "
                          "GROUP BY target_type ORDER BY c DESC")
    ]
    jobs_by_status = [
        {"label": r["status"], "value": int(r["c"])}
        for r in db.query("SELECT status, COUNT(*) c FROM jobs GROUP BY status ORDER BY c DESC")
    ]
    cases_by_status = [
        {"label": r["status"], "value": int(r["c"])}
        for r in db.query("SELECT status, COUNT(*) c FROM cases GROUP BY status ORDER BY c DESC")
    ]
    return {
        "findings_total": total_f,
        "findings_hits": hits,
        "hit_rate": round(hits / total_f, 3) if total_f else 0.0,
        "findings_by_source": by_source,
        "findings_by_type": by_type,
        "jobs_by_status": jobs_by_status,
        "cases_by_status": cases_by_status,
    }


def _gather(target: str, case_id: int | None = None) -> dict:
    """Collect report data. When a case_id is given, EVERYTHING is scoped to that
    case; otherwise only the findings for the exact target are returned. The
    account/timeline/identity tables are NEVER dumped un-scoped — doing so would
    leak every subject's data into any single export.
    """
    if case_id is not None:
        findings = db.query(
            "SELECT * FROM findings WHERE case_id=? ORDER BY created_at DESC", (case_id,))
        accounts = db.query("SELECT * FROM accounts WHERE case_id=? ORDER BY service", (case_id,))
        timeline = db.query("SELECT * FROM timeline_events WHERE case_id=? ORDER BY occurred_at",
                            (case_id,))
        identity = db.query("SELECT * FROM identity_items WHERE case_id=? ORDER BY kind, value",
                            (case_id,))
    else:
        findings = db.query("SELECT * FROM findings WHERE target=? ORDER BY created_at DESC",
                            (target,))
        accounts = timeline = identity = []
    return {
        "target": target,
        "case_id": case_id,
        "generated": now_iso(),
        "identity": [dict(r) for r in identity],
        "accounts": [dict(r) for r in accounts],
        "timeline": [dict(r) for r in timeline],
        "findings": [_finding(dict(r)) for r in findings],
    }


def _finding(d: dict) -> dict:
    if d.get("summary"):
        try:
            d["summary"] = json.loads(d["summary"])
        except Exception:
            pass
    d.pop("raw", None)
    return d


def _markdown(data: dict) -> str:
    lines = [f"# GoFindMe Report — {data['target'] or '(none)'}",
             "", f"_Generated: {data['generated']}_", ""]
    lines.append(f"## Identity ({len(data['identity'])})")
    for it in data["identity"]:
        lines.append(f"- **{it['kind']}**: {it['value']}" + (f" — {it['label']}" if it.get('label') else ""))
    lines += ["", f"## Accounts ({len(data['accounts'])})"]
    for a in data["accounts"]:
        twofa = "2FA" if a.get("has_2fa") else "no-2FA"
        lines.append(f"- **{a['service']}** ({a.get('status') or 'unknown'}, {twofa})"
                     + (f" — {a['url']}" if a.get('url') else ""))
    lines += ["", f"## Timeline ({len(data['timeline'])})"]
    for e in data["timeline"]:
        lines.append(f"- {e.get('occurred_at') or '?'} — {e['title']}")
    lines += ["", f"## Findings ({len(data['findings'])})"]
    for f in data["findings"]:
        s = f.get("summary") or {}
        lines.append(f"- **{f['source_name']}** [{f['target_type']}] → {json.dumps(s)}")
    return "\n".join(lines) + "\n"


@router.get("/reports/export")
async def export(target: str = "", case_id: int | None = None,
                 format: str = "json", _t: str = security.Auth):
    target = target.strip()
    # Sanitize what lands in the Content-Disposition filename (never trust raw input).
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", (target or f"case{case_id}" or "export"))[:64] or "export"
    data = _gather(target, case_id)
    if format == "md":
        return PlainTextResponse(_markdown(data), headers={
            "Content-Disposition": f'attachment; filename="gofindme-{safe}.md"'})
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="gofindme-{safe}.json"'})


# --- honest placeholders for v2 importers ---
@router.post("/import/{kind}")
async def import_stub(kind: str, _t: str = security.Auth):
    raise HTTPException(501, f"{kind} import is planned but not implemented yet")
