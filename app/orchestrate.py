"""Detection + Search-All fan-out.

Search-All turns one target into: a child tool job per available auto-runnable
tool (executed by the subprocess queue, streaming output) and a concurrent
provider lookup per configured/keyless provider (network coroutines that write
findings). A parent job groups them so the UI can poll one id.
"""
from __future__ import annotations

import asyncio

from . import db, jobs, providers as prov, tools
from .util import audit, jdumps, now_iso
from .vault import vault
from .validators import ValidationError, detect_types, validate

RAW_CAP = prov.RAW_CAP


def detect(raw: str) -> dict:
    return {"target": (raw or "").strip(), "candidate_types": detect_types(raw)}


def _write_finding(job_id: str | None, kind: str, name: str, target: str, ttype: str,
                   summary: dict, raw, case_id: int | None = None) -> None:
    db.execute(
        "INSERT INTO findings (job_id, source_kind, source_name, target, target_type, "
        "summary, raw, case_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (job_id, kind, name, target, ttype, jdumps(summary), jdumps(raw, RAW_CAP),
         case_id, now_iso()),
    )


async def run_provider(provider: prov.Provider, target: str, ttype: str,
                       parent: str | None = None, case_id: int | None = None) -> dict:
    """Run one provider lookup, persist a job row + finding, return the result."""
    key = None
    if provider.requires_key or provider.vault_key:
        try:
            key = vault.get_key(provider.vault_key) if provider.vault_key else None
        except ValueError:
            if provider.requires_key:
                return prov.ProviderResult(provider.name, False, target, {},
                                           error="vault_locked").to_dict()
    if provider.requires_key and not key:
        return prov.ProviderResult(provider.name, False, target, {},
                                   error="no_key_configured").to_dict()

    async with prov.make_client() as client:
        try:
            res = await provider.lookup(client, key, target, ttype)
        except Exception as exc:  # pragma: no cover - defensive
            res = provider.fail(target, f"error: {type(exc).__name__}")

    status = "done" if res.ok else "error"
    short = res.error or ("found" if res.summary.get("found") else "no result")
    job_id = jobs.get_queue().record_provider_job(provider.name, target, ttype, status, short, parent)
    # Persist the failure reason inside the finding so reports can explain a blank
    # result ("crt.sh timed out") instead of silently showing nothing.
    finding_summary = dict(res.summary or {})
    if not res.ok:
        finding_summary.setdefault("found", False)
        finding_summary["error"] = res.error or "lookup_failed"
    _write_finding(job_id, "provider", provider.name, target, ttype, finding_summary, res.raw, case_id)
    audit("info", "provider", "lookup", provider=provider.name, target_type=ttype, ok=res.ok)
    d = res.to_dict()
    d["job_id"] = job_id
    return d


async def _providers_bg(target: str, ttype: str, provs: list[prov.Provider], parent: str,
                        case_id: int | None = None) -> None:
    await asyncio.gather(*[run_provider(p, target, ttype, parent, case_id) for p in provs],
                         return_exceptions=True)


def search_all(target: str, ttype: str | None, case_id: int | None = None) -> dict:
    target = (target or "").strip()
    if not ttype:
        cands = detect_types(target)
        if not cands:
            raise ValidationError("Could not detect a target type")
        ttype = cands[0]
    validate(target, ttype)

    q = jobs.get_queue()
    parent = q.new_parent(target, ttype)

    # Tools: available + auto-runnable + accepts this type.
    tool_jobs = []
    skipped = []
    for spec in tools.registry().values():
        if ttype not in spec.accepts or spec.interactive or not spec.auto_runnable:
            continue
        if tools.resolve_bin(spec.bin) is None:
            skipped.append(spec.name)
            continue
        tool_jobs.append({"name": spec.name, "job_id": q.enqueue_tool(spec, target, ttype, parent)})

    # Providers: configured or keyless for this type.
    configured = set(vault.configured_providers())
    selected = [p for p in prov.providers_for_type(ttype)
                if (not p.requires_key) or (p.vault_key in configured)]
    provider_names = [p.name for p in selected]
    prov_task = q.track(_providers_bg(target, ttype, selected, parent, case_id)) if selected else None
    # Finalize the parent once children + providers complete (so it doesn't sit
    # 'queued' forever and any parent SSE stream closes).
    q.track(q.finalize_parent(parent, [tj["job_id"] for tj in tool_jobs], prov_task))

    if case_id:
        try:
            from . import cases
            cases.touch(case_id)
        except Exception:
            pass
    audit("audit", "tool", "search-all", target_type=ttype, tools=len(tool_jobs),
          providers=len(provider_names), case_id=case_id)
    return {
        "parent_job_id": parent,
        "target": target,
        "type": ttype,
        "case_id": case_id,
        "tool_jobs": tool_jobs,
        "tools_skipped": skipped,
        "providers": provider_names,
    }


def findings_for(target: str, ttype: str | None = None) -> list[dict]:
    import json
    if ttype:
        rows = db.query("SELECT * FROM findings WHERE target=? AND target_type=? "
                        "ORDER BY created_at DESC", (target, ttype))
    else:
        rows = db.query("SELECT * FROM findings WHERE target=? ORDER BY created_at DESC", (target,))
    out = []
    for r in rows:
        d = dict(r)
        for f in ("summary", "raw"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        out.append(d)
    return out
