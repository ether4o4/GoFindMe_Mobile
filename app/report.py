"""Court / procurement-grade investigation report (self-contained HTML → PDF).

Renders a standalone, print-optimized HTML document for a case: letterhead,
case metadata (examiner, legal authority, dates), executive summary, subject
identifiers, findings with source provenance, timeline, methodology (tools &
providers used), an audit excerpt, and a chain-of-custody integrity block
(tamper-evident audit tip hash + a SHA-256 of the report body). The browser's
Print-to-PDF turns it into a filable document. All dynamic values are HTML-escaped.
"""
from __future__ import annotations

import hashlib
import html
import json
import re

from . import __version__, audit_chain, db
from .util import now_iso


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


# Maps a leading subdomain label to the kind of service it usually fronts. Used to
# infer, from naming alone, what a domain's infrastructure is used for. Honest and
# clearly labelled as inferred — never presented as confirmed fact.
_SERVICE_MAP = [
    ("Email & messaging", {"mail", "smtp", "imap", "pop", "mx", "mx1", "mx2", "webmail",
                            "exchange", "autodiscover", "email", "zimbra", "owa", "mta"}),
    ("Web application", {"www", "web", "app", "apps", "home", "portal", "my"}),
    ("API services", {"api", "apis", "gateway", "gql", "graphql", "rest", "ws"}),
    ("Authentication & SSO", {"auth", "sso", "login", "idp", "oauth", "accounts", "account",
                              "id", "identity", "adfs", "signin"}),
    ("Content delivery & static assets", {"cdn", "static", "assets", "media", "img", "images",
                                          "files", "content", "cache"}),
    ("Remote access / VPN", {"vpn", "remote", "gw", "sslvpn", "access", "connect", "citrix", "rdp"}),
    ("Administration", {"admin", "manage", "console", "dashboard", "cpanel", "whm", "panel", "control"}),
    ("Developer & CI/CD", {"git", "gitlab", "jenkins", "ci", "cd", "build", "jira", "confluence",
                           "nexus", "artifactory", "sonar", "registry", "docker", "harbor"}),
    ("Non-production / staging", {"dev", "develop", "staging", "stg", "stage", "test", "testing",
                                  "qa", "uat", "sandbox", "sbx", "demo", "preprod", "beta", "int"}),
    ("Data & observability", {"db", "sql", "mysql", "postgres", "pg", "redis", "mongo", "elastic",
                              "kibana", "grafana", "prometheus", "metrics", "logs", "splunk"}),
    ("File transfer & storage", {"ftp", "sftp", "share", "nas", "drive", "storage", "s3", "backup"}),
    ("Commerce & billing", {"shop", "store", "pay", "payment", "payments", "checkout", "billing",
                            "invoice", "order", "orders", "cart"}),
    ("Corporate / internal", {"corp", "internal", "intranet", "intra", "office", "hr", "erp",
                              "crm", "sharepoint", "wiki"}),
    ("Monitoring & status", {"status", "health", "monitor", "monitoring", "uptime", "stats"}),
    ("Mail security / DNS", {"dns", "ns", "ns1", "ns2", "spf", "dkim", "dmarc", "_dmarc"}),
]


def _collect_related(findings: list[dict]) -> tuple[list[str], str]:
    """Related hosts/subdomains aggregated across all provider findings, plus the
    registrable base domain if any provider reported one."""
    names: set[str] = set()
    base = ""
    for f in findings:
        s = _loads(f.get("summary")) or {}
        if isinstance(s, dict):
            if s.get("base_domain") and not base:
                base = str(s["base_domain"])
            subs = s.get("subdomains")
            if isinstance(subs, list):
                for x in subs:
                    if isinstance(x, str) and x.strip():
                        names.add(x.strip().lower())
    return sorted(names), base


def _service_indicators(domains: list[str]) -> list[tuple[str, list[str]]]:
    """Infer likely service categories from the leading labels of related hosts."""
    labels: set[str] = set()
    for d in domains:
        parts = d.split(".")
        for p in (parts[:-2] if len(parts) > 2 else []):
            labels.add(p)
            labels.add(re.sub(r"\d+$", "", p))  # api2 -> api
    out = []
    for cat, keys in _SERVICE_MAP:
        matched = sorted(labels & keys)
        if matched:
            out.append((cat, matched[:6]))
    return out


def _auto_conclusion(case: dict, findings: list[dict], sources: list[str], hits: int,
                     related: list[str], base: str,
                     indicators: list[tuple[str, list[str]]], errored: list[str]) -> str:
    """A narrative analyst conclusion built from real data (dynamic values escaped)."""
    subj = case.get("subject") or case.get("title") or "the subject"
    stype = case.get("subject_type") or "identifier"
    src_list = ", ".join(sources) if sources else "no data sources"
    s = [f"This investigation examined the {_esc(stype)} <b>{_esc(subj)}</b>. "
         f"GoFindMe queried {len(sources)} source(s) ({_esc(src_list)}) and recorded "
         f"{len(findings)} finding(s), including {hits} positive hit(s)."]
    if related:
        base_txt = f" for the registrable domain <b>{_esc(base)}</b>" if base else ""
        s.append(f"Certificate-transparency and passive data{base_txt} surfaced "
                 f"<b>{len(related)}</b> related host(s)/subdomain(s), enumerated below.")
    if indicators:
        cats = ", ".join(c for c, _ in indicators)
        s.append(f"Subdomain naming indicates the domain is likely used for: <b>{_esc(cats)}</b> "
                 f"(inferred from host names, not confirmed).")
    if errored:
        s.append(f"<b>Note:</b> {_esc(', '.join(errored))} did not return data on this run "
                 f"&mdash; re-run the search if results look incomplete (crt.sh in particular is "
                 f"often slow for large domains).")
    if len(sources) <= 1:
        s.append("Only keyless sources were used. Configure provider API keys in the Vault "
                 "(breach, reputation and infrastructure data) to substantially enrich this profile.")
    return " ".join(s)


def _loads(v):
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def _summary_cell(summary) -> str:
    s = _loads(summary) or {}
    if not isinstance(s, dict):
        return _esc(str(s))
    parts = []
    for k, v in s.items():
        if k == "found":
            continue
        if k == "error":
            parts.append(f"<span class='err'>lookup error: {_esc(v)}</span>")
            continue
        if isinstance(v, list):
            v = f"{len(v)} item(s): " + ", ".join(map(str, v[:6])) + ("…" if len(v) > 6 else "")
        parts.append(f"<b>{_esc(k)}</b>: {_esc(v)}")
    return "<br>".join(parts) or "&mdash;"


def _finding_result(summary) -> tuple[str, str]:
    s = _loads(summary) or {}
    if not isinstance(s, dict):
        return "info", "info"
    if s.get("error"):
        return "error", "error"
    found = s.get("found")
    if found is True:
        return "HIT", "hit"
    if found is False:
        return "clear", "clear"
    return "info", "info"


def render_case_html(cid: int) -> str | None:
    case = db.query_one("SELECT * FROM cases WHERE id=?", (cid,))
    if not case:
        return None
    case = dict(case)
    findings = [dict(r) for r in db.query(
        "SELECT * FROM findings WHERE case_id=? ORDER BY created_at", (cid,))]
    timeline = [dict(r) for r in db.query(
        "SELECT * FROM timeline_events WHERE case_id=? ORDER BY occurred_at", (cid,))]
    notes = [dict(r) for r in db.query(
        "SELECT * FROM notes WHERE case_id=? ORDER BY created_at", (cid,))]
    accounts = [dict(r) for r in db.query(
        "SELECT * FROM accounts WHERE case_id=? ORDER BY service", (cid,))]
    audit_rows = audit_chain.recent(40)
    integrity = audit_chain.verify()

    sources = sorted({f["source_name"] for f in findings})
    hits = sum(1 for f in findings if (_loads(f["summary"]) or {}).get("found") is True)
    errored = sorted({f["source_name"] for f in findings
                      if (_loads(f["summary"]) or {}).get("error")})
    related, base_domain = _collect_related(findings)
    indicators = _service_indicators(related)
    generated = now_iso()

    # --- findings table rows ---
    frows = []
    for f in findings:
        label, cls = _finding_result(f["summary"])
        frows.append(
            f"<tr><td>{_esc(f['source_name'])}</td>"
            f"<td>{_esc(f['source_kind'])}</td>"
            f"<td>{_esc(f['target'])}<br><span class='dim'>{_esc(f['target_type'])}</span></td>"
            f"<td><span class='pill {cls}'>{_esc(label)}</span></td>"
            f"<td>{_summary_cell(f['summary'])}</td>"
            f"<td class='dim'>{_esc((f['created_at'] or '').replace('T',' '))}</td></tr>"
        )
    findings_tbl = ("".join(frows) or
                    "<tr><td colspan='6' class='dim'>No findings recorded for this case.</td></tr>")

    trows = "".join(
        f"<tr><td>{_esc(e.get('occurred_at') or '—')}</td><td>{_esc(e.get('event_type'))}</td>"
        f"<td>{_esc(e.get('title'))}<br><span class='dim'>{_esc(e.get('detail') or '')}</span></td></tr>"
        for e in timeline) or "<tr><td colspan='3' class='dim'>No timeline events.</td></tr>"

    arows = "".join(
        f"<tr><td>{_esc(a.get('service'))}</td><td>{_esc(a.get('status') or 'unknown')}</td>"
        f"<td>{'Yes' if a.get('has_2fa') else 'No/Unknown'}</td>"
        f"<td>{_esc(a.get('recovery_status') or '—')}</td></tr>"
        for a in accounts)
    accounts_block = (f"""
      <h2>Tracked Accounts <span class="count">{len(accounts)}</span></h2>
      <table><thead><tr><th>Service</th><th>Status</th><th>2FA</th><th>Recovery</th></tr></thead>
      <tbody>{arows}</tbody></table>""" if accounts else "")

    notes_block = ""
    if notes:
        items = "".join(f"<li>{_esc(n['body'])} <span class='dim'>"
                        f"({_esc((n['created_at'] or '').replace('T',' '))})</span></li>" for n in notes)
        notes_block = f"<h2>Investigator Notes <span class='count'>{len(notes)}</span></h2><ul class='notes'>{items}</ul>"

    audit_rows_html = "".join(
        f"<tr><td class='dim'>{_esc((r['ts'] or '').replace('T',' '))}</td>"
        f"<td>{_esc(r.get('actor'))}</td><td>{_esc(r.get('category'))}</td>"
        f"<td>{_esc(r.get('action'))}</td><td class='mono dim'>{_esc(r.get('hash_short'))}</td></tr>"
        for r in audit_rows) or "<tr><td colspan='5' class='dim'>No audit events.</td></tr>"

    methodology = ", ".join(_esc(s) for s in sources) or "—"

    # Executive summary: the examiner's own text if present, otherwise an
    # auto-generated analyst conclusion (never a bland "nothing recorded").
    if case.get("summary"):
        exec_html = _esc(case["summary"])
    else:
        exec_html = _auto_conclusion(case, findings, sources, hits, related,
                                     base_domain, indicators, errored)

    # Related Domains & Infrastructure + inferred usage.
    related_block = ""
    if related:
        shown = related[:300]
        items = "".join(f"<li>{_esc(x)}</li>" for x in shown)
        more = (f"<p class='dim'>… and {len(related) - len(shown)} more (see full JSON export).</p>"
                if len(related) > len(shown) else "")
        ind_block = ""
        if indicators:
            irows = "".join(
                f"<tr><td>{_esc(cat)}</td><td class='dim'>{_esc(', '.join(ex))}</td></tr>"
                for cat, ex in indicators)
            ind_block = ("<h3 class='sub'>What it's likely used for &middot; guessed from the host names</h3>"
                         "<table><thead><tr><th>Likely use</th><th>Matching hosts</th></tr></thead>"
                         f"<tbody>{irows}</tbody></table>")
        base_txt = f" under <b>{_esc(base_domain)}</b>" if base_domain else ""
        related_block = (
            f"<h2>Related Domains <span class='count'>{len(related)}</span></h2>"
            f"<p class='prose'>Other sites and subdomains linked to the subject{base_txt}, "
            f"pulled together from certificate transparency and passive data sources.</p>"
            f"<ul class='domains'>{items}</ul>{more}{ind_block}")

    body = f"""
  <header class="rpt-head">
    <div class="mark">&#9678;</div>
    <div>
      <div class="org">GoFindMe Investigations Console</div>
      <div class="doc">Investigation Report</div>
    </div>
    <div class="ref">
      <div class="reflabel">Case reference</div>
      <div class="refno">{_esc(case.get('ref') or ('#' + str(case['id'])))}</div>
    </div>
  </header>

  <section class="meta">
    <div><span class="k">Title</span><span class="v">{_esc(case.get('title'))}</span></div>
    <div><span class="k">Subject</span><span class="v">{_esc(case.get('subject') or '—')} <span class="dim">({_esc(case.get('subject_type') or 'n/a')})</span></span></div>
    <div><span class="k">Status</span><span class="v">{_esc((case.get('status') or '').upper())} &middot; priority {_esc(case.get('priority'))}</span></div>
    <div><span class="k">Investigator</span><span class="v">{_esc(case.get('examiner') or '—')}</span></div>
    <div><span class="k">Authorization</span><span class="v">{_esc(case.get('authority') or '—')}</span></div>
    <div><span class="k">Opened</span><span class="v">{_esc((case.get('created_at') or '').replace('T',' '))}</span></div>
    <div><span class="k">Report made</span><span class="v">{_esc(generated.replace('T',' '))} UTC</span></div>
    <div><span class="k">Made with</span><span class="v">GoFindMe v{_esc(__version__)}</span></div>
  </section>

  <section class="stats">
    <div class="stat"><div class="n">{len(findings)}</div><div class="l">Findings</div></div>
    <div class="stat"><div class="n">{hits}</div><div class="l">Hits</div></div>
    <div class="stat"><div class="n">{len(sources)}</div><div class="l">Sources checked</div></div>
    <div class="stat"><div class="n">{len(timeline)}</div><div class="l">Timeline events</div></div>
  </section>

  <h2>Summary</h2>
  <p class="prose">{exec_html}</p>

  <h2>Findings <span class="count">{len(findings)}</span></h2>
  <table class="findings">
    <thead><tr><th>Source</th><th>Type</th><th>Target</th><th>Result</th><th>Detail</th><th>Recorded (UTC)</th></tr></thead>
    <tbody>{findings_tbl}</tbody>
  </table>

  {related_block}

  {accounts_block}

  <h2>Timeline <span class="count">{len(timeline)}</span></h2>
  <table><thead><tr><th>When</th><th>Type</th><th>Event</th></tr></thead><tbody>{trows}</tbody></table>

  {notes_block}

  <h2>How this was gathered</h2>
  <p class="prose">GoFindMe ran a set of OSINT tools and data sources against the subject and
  collected what they returned. Everything runs safely on the server — no data leaves your machine
  except the lookups themselves. Sources used in this investigation: <b>{methodology}</b>.</p>

  <h2>Integrity &amp; Activity Log</h2>
  <div class="coc {'ok' if integrity['ok'] else 'bad'}">
    <div><span class="k">Integrity check</span><span class="v">{'Passed — nothing was altered' if integrity['ok'] else 'FAILED at entry #' + str(integrity['broken_at'])}</span></div>
    <div><span class="k">Log entries</span><span class="v">{integrity['count']}</span></div>
    <div><span class="k">Verification hash</span><span class="v mono">{_esc(integrity['tip'])}</span></div>
  </div>
  <table class="audit"><thead><tr><th>Time (UTC)</th><th>Who</th><th>Area</th><th>Action</th><th>Hash</th></tr></thead>
  <tbody>{audit_rows_html}</tbody></table>

  <footer class="rpt-foot">
    <div>GoFindMe &middot; Case {_esc(case.get('ref') or case['id'])} &middot; Made {_esc(generated.replace('T',' '))} UTC</div>
    <div class="dim">Built from the data saved in this GoFindMe case. The integrity check above and the
    fingerprint below let anyone confirm this report hasn't been changed since it was made.</div>
    <div class="fp">Report fingerprint (SHA-256): <span class="mono" id="__fp__">%%FINGERPRINT%%</span></div>
  </footer>
"""

    doc = _PAGE.replace("%%TITLE%%", _esc(case.get('ref') or 'GoFindMe Report')).replace("%%BODY%%", body)
    # Fingerprint the rendered body (minus the placeholder) for a stable content hash.
    fp = hashlib.sha256(body.replace("%%FINGERPRINT%%", "").encode("utf-8")).hexdigest()
    return doc.replace("%%FINGERPRINT%%", fp)


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%% — GoFindMe Report</title>
<style>
  :root{--ink:#12151c;--dim:#6b7280;--line:#e4e7ec;--brand:#0f766e;--bad:#b42318;--ok:#067647;}
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color:var(--ink);margin:0;background:#f3f4f6;line-height:1.5}
  .sheet{max-width:960px;margin:24px auto;background:#fff;padding:44px 52px 60px;
    box-shadow:0 1px 3px rgba(0,0,0,.12);border-radius:6px}
  .rpt-head{display:flex;align-items:center;gap:16px;border-bottom:3px solid var(--brand);padding-bottom:16px}
  .rpt-head .mark{font-size:40px;color:var(--brand);line-height:1}
  .rpt-head .org{font-weight:800;font-size:18px;letter-spacing:-.2px}
  .rpt-head .doc{color:var(--dim);font-size:13px;text-transform:uppercase;letter-spacing:1px}
  .rpt-head .ref{margin-left:auto;text-align:right}
  .rpt-head .reflabel{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim)}
  .rpt-head .refno{font-weight:800;font-size:18px;color:var(--brand)}
  .meta{display:grid;grid-template-columns:1fr 1fr;gap:8px 32px;margin:22px 0}
  .meta>div{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dotted var(--line);padding:5px 0;font-size:13.5px}
  .meta .k{color:var(--dim)}.meta .v{font-weight:600;text-align:right}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}
  .stat{border:1px solid var(--line);border-radius:8px;padding:12px 14px;text-align:center}
  .stat .n{font-size:26px;font-weight:800;color:var(--brand)}.stat .l{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
  h2{font-size:14px;text-transform:uppercase;letter-spacing:.6px;color:var(--ink);margin:30px 0 10px;
    padding-bottom:6px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}
  h2 .count{font-size:11px;color:#fff;background:var(--brand);border-radius:10px;padding:1px 8px;font-weight:700;letter-spacing:0}
  .prose{font-size:13.5px;margin:0 0 8px}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0 4px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--dim);background:#fafafa}
  .dim{color:var(--dim)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;word-break:break-all}
  .pill{font-size:10px;font-weight:800;padding:2px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:.4px}
  .pill.hit{background:#fef3f2;color:var(--bad)}.pill.clear{background:#ecfdf3;color:var(--ok)}.pill.info{background:#f2f4f7;color:var(--dim)}
  .pill.error{background:#fff4ed;color:#b54708}
  .err{color:var(--bad);font-weight:600}
  h3.sub{font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin:16px 0 6px}
  ul.domains{columns:3;column-gap:24px;font-size:11.5px;margin:8px 0 4px;padding-left:16px;list-style:square}
  ul.domains li{margin:2px 0;break-inside:avoid;word-break:break-all}
  @media print{ul.domains{columns:2}}
  @media(max-width:640px){ul.domains{columns:1}}
  ul.notes{font-size:13px;margin:6px 0;padding-left:20px}ul.notes li{margin:4px 0}
  .coc{border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}
  .coc.ok{border-left:4px solid var(--ok)}.coc.bad{border-left:4px solid var(--bad)}
  .coc>div{display:flex;justify-content:space-between;gap:12px;padding:3px 0;font-size:12.5px}
  .coc .k{color:var(--dim)}
  .rpt-foot{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);font-size:11px;color:var(--dim)}
  .rpt-foot .fp{margin-top:8px}
  .toolbar{max-width:960px;margin:14px auto -6px;display:flex;gap:10px;justify-content:flex-end}
  .toolbar button{font:inherit;font-size:13px;font-weight:600;padding:9px 16px;border-radius:8px;border:1px solid var(--brand);
    background:var(--brand);color:#fff;cursor:pointer}
  .toolbar button.ghost{background:#fff;color:var(--brand)}
  @media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;border-radius:0;padding:0}.toolbar{display:none}}
</style></head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Print / Save as PDF</button>
    <button class="ghost" onclick="window.close()">Close</button>
  </div>
  <div class="sheet">%%BODY%%</div>
</body></html>"""
