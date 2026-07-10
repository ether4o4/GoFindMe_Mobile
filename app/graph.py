"""Relationship graph derivation.

Builds a nodes+edges graph for a case (or a bare target) from the evidence
already captured: the subject, any tracked accounts, and provider/tool findings.
The frontend renders it as an interactive force-directed graph. This is
deterministic and derived from real data — nothing is fabricated.
"""
from __future__ import annotations

import json

from . import db

# Summary fields that carry lists of related identifiers worth exploding into
# their own child nodes (capped per source so the graph stays legible).
_LIST_FIELDS = {
    "subdomains": ("domain", "resolves"),
    "domains": ("domain", "linked"),
    "emails": ("email", "linked"),
    "usernames": ("username", "linked"),
    "profiles": ("account", "has-profile"),
    "accounts": ("account", "has-profile"),
    "sites": ("account", "found-on"),
    "breaches": ("breach", "exposed-in"),
    "phones": ("phone", "linked"),
    "names": ("person", "linked"),
}
_CHILD_CAP = 12


def _loads(v):
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def build_for_case(cid: int) -> dict:
    case = db.query_one("SELECT * FROM cases WHERE id=?", (cid,))
    if not case:
        return {"nodes": [], "edges": []}
    subject = (case["subject"] or case["title"] or "subject").strip()
    stype = case["subject_type"] or "person"
    findings = db.query("SELECT * FROM findings WHERE case_id=? ORDER BY id", (cid,))
    accounts = db.query("SELECT * FROM accounts WHERE case_id=? ORDER BY id", (cid,))
    files = db.query("SELECT * FROM case_files WHERE case_id=? ORDER BY id", (cid,))
    return _assemble(subject, stype, findings, accounts, files)


def build_for_target(target: str, ttype: str | None) -> dict:
    target = (target or "").strip()
    if ttype:
        findings = db.query("SELECT * FROM findings WHERE target=? AND target_type=? ORDER BY id",
                            (target, ttype))
    else:
        findings = db.query("SELECT * FROM findings WHERE target=? ORDER BY id", (target,))
    return _assemble(target, ttype or "person", findings, [])


def _assemble(subject: str, stype: str, findings, accounts, files=()) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid, label, ntype, group, **meta):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": str(label)[:64], "type": ntype,
                          "group": group, "meta": meta}
        return nid

    root = add_node("subject", subject, stype, "subject", role="subject")

    # Tracked accounts → account nodes (+ recovery identifiers).
    for a in accounts:
        aid = f"acct:{a['id']}"
        add_node(aid, a["service"], "account", "account",
                 status=a["status"], has_2fa=a["has_2fa"], url=a["url"])
        edges.append({"source": root, "target": aid, "relation": "uses"})
        if a["recovery_email"]:
            rid = add_node(f"em:{a['recovery_email']}", a["recovery_email"], "email", "identifier")
            edges.append({"source": aid, "target": rid, "relation": "recovers"})
        if a["recovery_phone"]:
            rid = add_node(f"ph:{a['recovery_phone']}", a["recovery_phone"], "phone", "identifier")
            edges.append({"source": aid, "target": rid, "relation": "recovers"})

    # Attached evidence files → file nodes linked to the subject.
    for fl in files:
        fid = f"file:{fl['id']}"
        add_node(fid, fl["label"] or fl["filename"], "file", "file",
                 file_id=fl["id"], filename=fl["filename"],
                 content_type=fl["content_type"], size=fl["size"], sha256=fl["sha256"])
        edges.append({"source": root, "target": fid, "relation": "attached"})

    # Findings → a source node per source that returned a hit, plus exploded list
    # identifiers from its normalized summary.
    for f in findings:
        summary = _loads(f["summary"]) or {}
        found = summary.get("found")
        sid = f"src:{f['source_name']}"
        hit = found is True or any(k in summary for k in _LIST_FIELDS)
        add_node(sid, f["source_name"], "source", "source",
                 kind=f["source_kind"], found=found)
        edges.append({"source": root, "target": sid,
                      "relation": "hit" if found is True else "queried"})
        if not isinstance(summary, dict):
            continue
        for field, (ntype, rel) in _LIST_FIELDS.items():
            vals = summary.get(field)
            if not isinstance(vals, list):
                continue
            for v in vals[:_CHILD_CAP]:
                if not v:
                    continue
                cid_ = f"{ntype}:{str(v)[:80]}"
                add_node(cid_, v, ntype, "identifier")
                edges.append({"source": sid, "target": cid_, "relation": rel})
        _ = hit  # legibility only

    # De-dup edges.
    seen, uniq = set(), []
    for e in edges:
        k = (e["source"], e["target"], e["relation"])
        if k in seen or e["source"] == e["target"]:
            continue
        seen.add(k)
        uniq.append(e)
    return {"nodes": list(nodes.values()), "edges": uniq,
            "stats": {"nodes": len(nodes), "edges": len(uniq)}}
