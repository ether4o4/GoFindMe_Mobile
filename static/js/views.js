import { api, streamJob } from "./api.js";
import { el, clear, toast, field, button, icon, statusDot, onDispose,
         confirmAction, modal, skeleton, emptyState } from "./ui.js";

let prefill = null;
export function setPrefill(t) { prefill = t; }
let _rerender = () => {};
export function setRerender(fn) { _rerender = fn; }
function rerender() { _rerender(); }

const TARGET_TYPES = ["username", "realname", "email", "phone", "domain", "ip", "hash", "bitcoin"];
const EXAMPLES = [["example.com", "domain"], ["8.8.8.8", "ip"], ["johndoe", "username"], ["test@example.com", "email"]];
const GROUP_COLORS = { subject: "#2dd4a7", source: "#5b8cff", identifier: "#f5b544", account: "#a98bff", file: "#ef7d9d" };

/* ----------------------------- shared bits ---------------------------- */
function crumbs(items) {
  const c = document.getElementById("crumbs"); if (!c) return; clear(c);
  items.forEach((it, i) => {
    if (i) c.append(el("span", { class: "faint", style: "margin:0 2px", text: "/" }));
    if (it.hash) c.append(el("a", { href: it.hash, text: it.text }));
    else c.append(el("h1", { id: "page-title", text: it.text }));
  });
}
function topActions(...els) {
  const a = document.getElementById("topbar-actions"); if (!a) return;
  clear(a); els.forEach(e => e && a.append(e));
}
function stat(n, l, ic, cls = "") {
  return el("div", { class: "stat" }, [el("div", { class: "ic" }, [icon(ic)]),
    el("div", { class: "n " + cls, text: String(n) }), el("div", { class: "l", text: l })]);
}
function svgEl(tag, attrs = {}) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  return e;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function pageHead(title, sub) {
  return [el("div", { class: "page-title", text: title }), sub ? el("div", { class: "page-sub", text: sub }) : null];
}

/* =============================== Investigate ============================ */
async function investigateView(root) {
  const input = el("input", { placeholder: "Enter a username, email, domain, IP, phone, hash, or name…",
    "aria-label": "Investigation target" });
  const detected = el("div", { class: "detected" });
  const goBtn = button("Investigate", { cls: "primary", icon: "investigate", onclick: go });
  root.append(el("div", { class: "hero" }, [
    el("h2", { text: "Start an investigation" }),
    el("p", { text: "Type in anything you want to look up — a username, email, domain, IP, phone, or name. GoFindMe opens a case, runs every tool and data source it can against it, and puts the results into one clean report you can save or share." }),
    el("div", { class: "searchbar" }, [
      el("div", { class: "inpwrap" }, [icon("search"), input]), goBtn]),
    detected,
    el("div", { class: "chips" }, EXAMPLES.map(([v]) =>
      el("button", { class: "chip", text: v, onclick: () => { input.value = v; go(); } }))),
  ]));

  input.addEventListener("input", debounce(updateDetect, 250));
  input.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  if (prefill) { input.value = prefill; prefill = null; }
  setTimeout(() => input.focus(), 40);

  async function updateDetect() {
    const t = input.value.trim(); clear(detected);
    if (!t) return;
    try {
      const d = await api.post("/api/detect", { target: t });
      if (!d.candidate_types.length) return;
      detected.append(document.createTextNode("Looks like: "));
      d.candidate_types.forEach((ty, i) => {
        if (i) detected.append(document.createTextNode(", "));
        detected.append(el("b", { text: ty }));
      });
    } catch {}
  }
  async function go() {
    const target = input.value.trim();
    if (!target) return toast("Enter a target to investigate", true);
    goBtn.disabled = true;
    try {
      const res = await api.post("/api/investigate", { target });
      location.hash = "#/case/" + res.case.id + "/findings";
    } catch (e) { goBtn.disabled = false; toast(e.message, true); }
  }

  root.append(el("div", { class: "h-sec" }, [icon("cases"), "Recent investigations"]));
  const host = el("div"); root.append(host); host.append(skeleton(3));
  try {
    const cs = await api.get("/api/cases");
    clear(host);
    if (!cs.length) host.append(emptyState("cases", "No investigations yet",
      "Enter a target above to open your first case."));
    else host.append(el("div", { class: "grid" }, cs.slice(0, 6).map(caseCard)));
  } catch { clear(host); host.append(el("div", { class: "empty", text: "Could not load cases." })); }
}

function caseCard(c) {
  const counts = c.counts || {};
  return el("div", { class: "card hov click", onclick: () => (location.hash = "#/case/" + c.id) }, [
    el("div", { class: "between" }, [
      el("div", { style: "min-width:0" }, [
        el("div", { class: "mono small", style: "color:var(--brand)", text: c.ref || ("#" + c.id) }),
        el("div", { style: "font-weight:680;font-size:15px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: c.title }),
      ]),
      el("span", { class: "pri " + (c.priority || "normal"), text: c.priority || "normal" }),
    ]),
    el("div", { class: "cd", text: (c.subject_type ? c.subject_type + " · " : "") + (c.subject || "—") }),
    el("div", { class: "row", style: "margin-top:13px;gap:16px" }, [
      miniStat(counts.findings || 0, "findings"), miniStat(counts.hits || 0, "hits"),
      miniStat(counts.timeline || 0, "events"), el("span", { class: "sp" }),
      el("span", { class: "tag " + (c.status === "closed" || c.status === "archived" ? "" : "ok"), text: c.status }),
    ]),
  ]);
}
function miniStat(n, l) {
  return el("span", { class: "small" }, [el("b", { text: String(n) }), el("span", { class: "muted", text: " " + l })]);
}

/* ================================= Cases =============================== */
async function casesView(root) {
  topActions(button("New case", { cls: "primary sm", icon: "plus", onclick: newCaseModal }));
  root.append(...pageHead("Investigations",
    "Each thing you look into is its own case — all its findings, notes, and a clean report kept together in one place."));
  const host = el("div"); root.append(host); host.append(skeleton(3));
  const cs = await api.get("/api/cases");
  clear(host);
  if (!cs.length)
    return host.append(emptyState("cases", "No cases yet",
      "Open one from Investigate, or create a blank case.",
      button("New case", { cls: "primary", icon: "plus", onclick: newCaseModal })));
  host.append(el("div", { class: "grid" }, cs.map(caseCard)));
}

function newCaseModal() {
  const f = {
    title: el("input", { placeholder: "Name this investigation" }),
    subject: el("input", { placeholder: "Who or what you're looking into (optional)" }),
    subject_type: el("select", {}, [el("option", { value: "", text: "auto-detect" }),
      ...TARGET_TYPES.map(t => el("option", { value: t, text: t }))]),
    examiner: el("input", { placeholder: "Your name (optional)" }),
    authority: el("input", { placeholder: "Authorization / case # (optional)" }),
    priority: el("select", {}, ["normal", "low", "high", "urgent"].map(p => el("option", { value: p, text: p }))),
  };
  const m = modal("New investigation", "Open a case to keep everything about it in one place.",
    [el("div", { class: "col" }, [field("Name", f.title), field("Subject", f.subject),
      field("Subject type", f.subject_type), field("Your name", f.examiner),
      field("Authorization", f.authority), field("Priority", f.priority)])],
    [button("Cancel", { cls: "ghost", onclick: () => m.close() }),
     button("Create case", { cls: "primary", onclick: async () => {
       try {
         const c = await api.post("/api/cases", {
           title: f.title.value, subject: f.subject.value, subject_type: f.subject_type.value || null,
           examiner: f.examiner.value, authority: f.authority.value, priority: f.priority.value });
         m.close(); toast("Case " + c.ref + " created"); location.hash = "#/case/" + c.id;
       } catch (e) { toast(e.message, true); }
     } })]);
}

/* ============================ Case workspace =========================== */
async function caseView(root, params) {
  const id = parseInt(params[0], 10);
  const tab = params[1] || "overview";
  if (!id) { location.hash = "#/cases"; return; }
  let c;
  try { c = await api.get("/api/cases/" + id); }
  catch { return root.append(emptyState("cases", "Case not found", "It may have been deleted.")); }

  crumbs([{ text: "Cases", hash: "#/cases" }, { text: c.ref || ("#" + id) }]);
  topActions(
    button("Open report", { cls: "sm", icon: "doc", onclick: () => window.open("/api/cases/" + id + "/report", "_blank") }),
    button("", { cls: "sm ghost", icon: "trash", label: "Delete case", onclick: () => delCase(c) }),
  );
  root.append(caseHeader(c));

  const TABS = [["overview", "Overview", "cases"], ["findings", "Findings", "search"],
    ["graph", "Graph", "graph"], ["files", "Files", "paperclip"],
    ["timeline", "Timeline", "clock"], ["report", "Report", "doc"]];
  root.append(el("div", { class: "subtabs" }, TABS.map(([k, label, ic]) =>
    el("button", { class: "subtab" + (k === tab ? " active" : ""),
      onclick: () => (location.hash = "#/case/" + id + "/" + k) }, [icon(ic, "sm"), el("span", { text: label })]))));

  const body = el("div"); root.append(body);
  if (tab === "findings") await caseFindings(body, c);
  else if (tab === "graph") await caseGraph(body, c);
  else if (tab === "files") await caseFiles(body, c);
  else if (tab === "timeline") await caseTimeline(body, c);
  else if (tab === "report") caseReportTab(body, c);
  else await caseOverview(body, c);
}

function caseHeader(c) {
  const counts = c.counts || {};
  const metaItem = (k, v) => el("div", {}, [el("div", { class: "k", text: k }), el("div", { class: "v", text: v || "—" })]);
  return el("div", { class: "case-hdr" }, [
    el("div", { class: "top" }, [
      el("div", { style: "flex:1;min-width:0" }, [
        el("div", { class: "ref", text: c.ref || ("#" + c.id) }),
        el("div", { class: "ttl", text: c.title }),
      ]),
      el("span", { class: "pri " + (c.priority || "normal"), text: (c.priority || "normal") }),
      el("span", { class: "tag " + (c.status === "closed" || c.status === "archived" ? "" : "ok"), text: c.status }),
    ]),
    el("div", { class: "meta" }, [
      metaItem("Subject", (c.subject || "—") + (c.subject_type ? " (" + c.subject_type + ")" : "")),
      metaItem("Investigator", c.examiner), metaItem("Authorization", c.authority),
      metaItem("Findings", String(counts.findings || 0) + " · " + (counts.hits || 0) + " hits"),
      metaItem("Opened", (c.created_at || "").replace("T", " ")),
    ]),
  ]);
}

async function delCase(c) {
  if (!confirmAction("Delete case " + (c.ref || c.id) + "? Evidence is unlinked, not destroyed.")) return;
  try { await api.del("/api/cases/" + c.id); toast("Case deleted"); location.hash = "#/cases"; }
  catch (e) { toast(e.message, true); }
}

async function caseOverview(root, c) {
  const counts = c.counts || {};
  root.append(el("div", { class: "stats" }, [
    stat(counts.findings || 0, "Findings", "search"),
    stat(counts.hits || 0, "Positive hits", "alert", counts.hits ? "badc" : ""),
    stat(counts.timeline || 0, "Timeline events", "clock"),
    stat(counts.files || 0, "Files", "paperclip"),
    stat(counts.notes || 0, "Notes", "doc"),
  ]));

  root.append(el("div", { class: "h-sec" }, [icon("investigate"), "Search this subject"]));
  const inp = el("input", { value: c.subject || "", placeholder: "target", style: "max-width:340px" });
  const tsel = el("select", { style: "max-width:150px" }, [el("option", { value: "", text: "auto" }),
    ...TARGET_TYPES.map(t => el("option", { value: t, text: t, selected: t === c.subject_type ? "selected" : null }))]);
  root.append(el("div", { class: "row" }, [inp, tsel,
    button("Search everything", { cls: "primary", icon: "search", onclick: async () => {
      const target = inp.value.trim(); if (!target) return toast("Enter something to search", true);
      try { await api.post("/api/cases/" + c.id + "/search", { target, type: tsel.value || null });
        toast("Search started"); location.hash = "#/case/" + c.id + "/findings"; }
      catch (e) { toast(e.message, true); }
    } })]));

  root.append(el("div", { class: "h-sec" }, [icon("settings"), "Case status"]));
  const statusSel = el("select", { style: "max-width:150px" },
    ["open", "active", "closed", "archived"].map(s => el("option", { value: s, text: s, selected: s === c.status ? "selected" : null })));
  const prioSel = el("select", { style: "max-width:150px" },
    ["low", "normal", "high", "urgent"].map(p => el("option", { value: p, text: p, selected: p === c.priority ? "selected" : null })));
  const exam = el("input", { value: c.examiner || "", placeholder: "Your name", style: "max-width:220px" });
  const auth = el("input", { value: c.authority || "", placeholder: "Authorization", style: "max-width:260px" });
  root.append(el("div", { class: "row" }, [statusSel, prioSel, exam, auth,
    button("Save", { cls: "sm primary", onclick: async () => {
      try { await api.put("/api/cases/" + c.id, { status: statusSel.value, priority: prioSel.value,
        examiner: exam.value, authority: auth.value }); toast("Saved"); rerender(); }
      catch (e) { toast(e.message, true); }
    } })]));

  root.append(el("div", { class: "h-sec" }, [icon("doc"), "Executive summary"]));
  const ta = el("textarea", { placeholder: "Write the investigation summary that appears on the report cover…" });
  ta.value = c.summary || "";
  root.append(ta, el("div", { class: "row mt" }, [button("Save summary", { cls: "sm primary", onclick: async () => {
    try { await api.put("/api/cases/" + c.id, { summary: ta.value }); toast("Summary saved"); }
    catch (e) { toast(e.message, true); } }})]));
}

async function caseFindings(root, c) {
  const status = el("div", { class: "callout brand" }, [icon("activity"),
    el("div", { html: "Collecting results… tools and data sources are running. New findings appear below automatically." })]);
  root.append(status);
  const grid = el("div", { class: "grid" }); root.append(grid);
  const seen = new Set();
  let stableRounds = 0, rounds = 0;

  async function tick() {
    let rows;
    try { rows = await api.get("/api/cases/" + c.id + "/findings"); } catch { return; }
    let added = 0;
    for (const f of rows) {
      const k = f.source_name + ":" + f.id;
      if (seen.has(k)) continue;
      seen.add(k); grid.append(findingCard(f)); added++;
    }
    rounds++;
    stableRounds = added ? 0 : stableRounds + 1;
    if (!grid.children.length && rounds > 1)
      grid.append(emptyState("search", "No findings yet",
        "Providers need API keys to return data — add them under Sources. Keyless sources (crt.sh) work immediately."));
    if (stableRounds >= 4 || rounds > 40) { clearInterval(timer); status.remove(); }
  }
  const timer = setInterval(tick, 2000); onDispose(() => clearInterval(timer));
  await tick();
}

function findingCard(f) {
  const s = f.summary || {};
  const found = s.found;
  const badge = found === true ? ["tag bad", "HIT"] : found === false ? ["tag ok", "CLEAR"] : ["tag", "INFO"];
  const head = el("div", { class: "ch" }, [
    el("span", { style: "display:flex;align-items:center;gap:8px" },
      [el("b", { text: f.source_name }), el("span", { class: "tag", text: f.target_type })]),
    el("span", { class: badge[0], text: badge[1] }),
  ]);
  const body = el("div", { class: "cd" });
  for (const [k, v] of Object.entries(s)) {
    if (k === "found") continue;
    body.append(el("div", { text: `${k}: ${Array.isArray(v) ? v.slice(0, 8).join(", ") : v}` }));
  }
  const card = el("div", { class: "card" }, [head, body]);
  if (f.raw)
    card.append(el("details", { style: "margin-top:10px" }, [el("summary", { text: "raw payload" }),
      el("div", { class: "body" }, [el("pre", { class: "out", text: JSON.stringify(f.raw, null, 2) })])]));
  return card;
}

async function caseGraph(root, c) {
  root.append(el("div", { class: "page-sub", style: "margin-bottom:14px",
    text: "Auto-derived link analysis: the subject, tracked accounts, and every source hit and identifier found. Drag nodes, scroll to zoom, click to inspect." }));
  const host = el("div"); root.append(host); host.append(skeleton(1, "skel-card"));
  let data;
  try { data = await api.get("/api/cases/" + c.id + "/graph"); } catch (e) { clear(host); return host.append(el("div", { class: "empty", text: e.message })); }
  clear(host);
  if (!data.nodes.length)
    return host.append(emptyState("graph", "Nothing to graph yet",
      "Run a search or add accounts to this case, then the relationship graph builds itself."));
  const wrap = el("div", { class: "graphwrap" });
  wrap.append(el("div", { class: "graph-legend" }, Object.entries(GROUP_COLORS).map(([g, col]) =>
    el("span", {}, [el("i", { style: "background:" + col }), g]))));
  host.append(wrap);
  forceGraph(wrap, data, c.id);
}

/* --------------------------- Case files (uploads) --------------------------- */
function humanSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(1) + " MB";
}

async function caseFiles(root, c) {
  root.append(el("div", { class: "page-sub", style: "margin-bottom:14px",
    text: "Attach evidence files to this investigation — screenshots, exports, documents. Each upload is fingerprinted (SHA-256) and also appears as a node on the case graph." }));

  const fileInput = el("input", { type: "file", multiple: "multiple", style: "display:none",
    "aria-label": "Choose files to attach" });
  const upBtn = button("Add files", { cls: "primary", icon: "upload", onclick: () => fileInput.click() });
  const drop = el("div", { class: "upload-drop", onclick: () => fileInput.click() }, [
    icon("paperclip", "lg"),
    el("div", { style: "font-weight:640", text: "Add files to this case" }),
    el("div", { class: "muted small", text: "Tap to choose files, or drop them here" }),
    upBtn,
  ]);
  const host = el("div", { class: "mt" });
  root.append(fileInput, drop, host);

  async function doUpload(fl) {
    if (!fl || !fl.length) return;
    upBtn.disabled = true;
    try {
      const r = await api.upload("/api/cases/" + c.id + "/files", fl);
      toast(((r.files && r.files.length) || 0) + " file(s) added");
      await load();
    } catch (e) { toast(e.message, true); }
    finally { upBtn.disabled = false; fileInput.value = ""; }
  }
  fileInput.addEventListener("change", () => doUpload(fileInput.files));
  ["dragover", "dragenter"].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", e => doUpload(e.dataTransfer && e.dataTransfer.files));

  function fileCard(f) {
    const dl = () => window.open("/api/cases/" + c.id + "/files/" + f.id + "/download", "_blank");
    return el("div", { class: "card" }, [
      el("div", { style: "min-width:0" }, [
        el("div", { style: "font-weight:660;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: f.filename }),
        el("div", { class: "cd", text: humanSize(f.size) + (f.content_type ? " · " + f.content_type : "") }),
      ]),
      el("div", { class: "mono", style: "font-size:10.5px;color:var(--faint);margin-top:8px;word-break:break-all",
        text: "sha256 " + (f.sha256 || "").slice(0, 32) + "…" }),
      el("div", { class: "row mt" }, [
        button("Download", { cls: "sm", icon: "download", onclick: dl }),
        button("", { cls: "sm ghost danger", icon: "trash", label: "Delete file", onclick: async () => {
          if (!confirmAction("Delete " + f.filename + "?")) return;
          try { await api.del("/api/cases/" + c.id + "/files/" + f.id); toast("File deleted"); await load(); }
          catch (e) { toast(e.message, true); }
        } }),
      ]),
    ]);
  }

  async function load() {
    clear(host); host.append(skeleton(2, "skel-card"));
    let rows;
    try { rows = await api.get("/api/cases/" + c.id + "/files"); }
    catch (e) { clear(host); host.append(el("div", { class: "empty", text: e.message })); return; }
    clear(host);
    if (!rows.length)
      return host.append(emptyState("paperclip", "No files yet",
        "Uploaded evidence files appear here and as nodes on the case graph."));
    host.append(el("div", { class: "h-sec" }, [icon("paperclip"), "Attached files (" + rows.length + ")"]));
    host.append(el("div", { class: "grid" }, rows.map(fileCard)));
  }

  await load();
}

function forceGraph(container, data, caseId) {
  // Portrait phones get a shorter canvas so the graph doesn't dominate the scroll.
  const narrow = window.matchMedia("(max-width:860px)").matches;
  const W = Math.max(320, container.clientWidth || 900), H = narrow ? 380 : 500;
  const nodes = data.nodes.map((n, i) => ({ ...n,
    x: W / 2 + Math.cos(i * 2.4) * (80 + i * 4), y: H / 2 + Math.sin(i * 2.4) * (80 + i * 4),
    vx: 0, vy: 0 }));
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const links = data.edges.map(e => ({ s: byId[e.source], t: byId[e.target], rel: e.relation }))
    .filter(l => l.s && l.t);
  nodes.forEach(n => (n.deg = 0));
  links.forEach(l => { l.s.deg++; l.t.deg++; });

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet", style: `height:${H}px` });
  const rootG = svgEl("g"); svg.append(rootG);
  const gE = svgEl("g"); const gN = svgEl("g"); rootG.append(gE, gN);
  const edgeEls = links.map(() => { const ln = svgEl("line", { class: "gedge" }); gE.append(ln); return ln; });

  let scale = 1, tx = 0, ty = 0;
  const applyT = () => rootG.setAttribute("transform", `translate(${tx},${ty}) scale(${scale})`);
  const toLocal = ev => { const r = svg.getBoundingClientRect();
    return { x: (ev.clientX - r.left) * (W / r.width) / scale - tx / scale,
             y: (ev.clientY - r.top) * (H / r.height) / scale - ty / scale }; };

  let panel = null;
  function inspect(n) {
    if (panel) panel.remove();
    panel = el("div", { class: "g-inspect" }, [
      el("div", { class: "between" }, [el("h4", { text: n.label }),
        button("", { cls: "sm ghost", icon: "x", onclick: () => { panel.remove(); panel = null; } })]),
      el("div", { class: "kv" }, [el("span", { class: "k", text: "type" }), el("span", { text: n.type })]),
      el("div", { class: "kv" }, [el("span", { class: "k", text: "group" }), el("span", { text: n.group })]),
      ...Object.entries(n.meta || {}).filter(([, v]) => v != null && v !== "").slice(0, 6)
        .map(([k, v]) => el("div", { class: "kv" }, [el("span", { class: "k", text: k }), el("span", { text: String(v) })])),
    ]);
    // File nodes get a direct download action.
    if (n.group === "file" && caseId && n.meta && n.meta.file_id != null)
      panel.append(el("div", { class: "mt" }, [button("Download file", { cls: "sm block", icon: "download",
        onclick: () => window.open("/api/cases/" + caseId + "/files/" + n.meta.file_id + "/download", "_blank") })]));
    container.append(panel);
  }

  const nodeEls = nodes.map(n => {
    const g = svgEl("g", { class: "gnode" });
    const r = n.group === "subject" ? 17 : 8 + Math.min(n.deg, 7);
    g.append(svgEl("circle", { r, fill: GROUP_COLORS[n.group] || "#8b93a7", stroke: "#0a0c10", "stroke-width": 2 }));
    const t = svgEl("text", { x: 0, y: r + 13, "text-anchor": "middle" });
    t.textContent = n.label.length > 20 ? n.label.slice(0, 19) + "…" : n.label;
    g.append(t); gN.append(g);
    let dragging = false;
    g.addEventListener("pointerdown", ev => { ev.stopPropagation(); dragging = true; n.fixed = true;
      g.setPointerCapture(ev.pointerId); inspect(n); });
    g.addEventListener("pointermove", ev => { if (!dragging) return; const p = toLocal(ev); n.x = p.x; n.y = p.y; n.vx = n.vy = 0; });
    g.addEventListener("pointerup", () => { dragging = false; n.fixed = false; });
    return { g, n };
  });

  svg.addEventListener("wheel", ev => { ev.preventDefault();
    scale = Math.max(0.35, Math.min(3, scale * (ev.deltaY < 0 ? 1.12 : 0.9))); applyT(); }, { passive: false });
  let panning = false, px = 0, py = 0;
  svg.addEventListener("pointerdown", ev => { panning = true; px = ev.clientX; py = ev.clientY; });
  svg.addEventListener("pointermove", ev => { if (!panning) return;
    tx += ev.clientX - px; ty += ev.clientY - py; px = ev.clientX; py = ev.clientY; applyT(); });
  window.addEventListener("pointerup", () => (panning = false));

  let alpha = 1, ticks = 0, raf = 0;
  function tick() {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy || 0.01, d = Math.sqrt(d2), rep = 2400 / d2;
      const fx = dx / d * rep, fy = dy / d * rep; a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const l of links) {
      let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const desired = l.s.group === "subject" || l.t.group === "subject" ? 115 : 74;
      const f = (d - desired) * 0.02, fx = dx / d * f, fy = dy / d * f;
      l.s.vx += fx; l.s.vy += fy; l.t.vx -= fx; l.t.vy -= fy;
    }
    for (const n of nodes) { n.vx += (W / 2 - n.x) * 0.008; n.vy += (H / 2 - n.y) * 0.008; }
    for (const n of nodes) { if (n.fixed) continue; n.vx *= 0.85; n.vy *= 0.85; n.x += n.vx * alpha; n.y += n.vy * alpha; }
    for (let i = 0; i < links.length; i++) {
      const l = links[i], e = edgeEls[i];
      e.setAttribute("x1", l.s.x); e.setAttribute("y1", l.s.y); e.setAttribute("x2", l.t.x); e.setAttribute("y2", l.t.y);
    }
    for (const ne of nodeEls) ne.g.setAttribute("transform", `translate(${ne.n.x},${ne.n.y})`);
    alpha *= 0.992; ticks++;
    if (ticks < 500 && alpha > 0.015) raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);
  onDispose(() => cancelAnimationFrame(raf));
  container.append(svg);
}

async function caseTimeline(root, c) {
  const form = el("div", { class: "card mb" }, []);
  const fType = el("select", {}, ["account_created", "device_added", "breach", "note"].map(t => el("option", { value: t, text: t })));
  const fWhen = el("input", { placeholder: "Year or date (e.g. 2021 or 2021-06)" });
  const fTitle = el("input", { placeholder: "Event title" });
  const fDetail = el("textarea", { placeholder: "Detail (optional)" });
  form.append(el("div", { class: "row" }, [field("Type", fType), field("When", fWhen)]),
    field("Title", fTitle), field("Detail", fDetail),
    el("div", { class: "row mt" }, [button("Add event", { cls: "primary sm", icon: "plus", onclick: add })]));
  root.append(el("div", { class: "h-sec" }, [icon("clock"), "Add timeline event"]), form);
  const host = el("div"); root.append(host);
  await load();

  async function add() {
    if (!fTitle.value.trim()) return toast("Title required", true);
    try {
      await api.post("/api/timeline", { event_type: fType.value, occurred_at: fWhen.value,
        title: fTitle.value, detail: fDetail.value, case_id: c.id });
      fTitle.value = fDetail.value = fWhen.value = ""; toast("Added"); await load();
    } catch (e) { toast(e.message, true); }
  }
  async function load() {
    clear(host);
    const rows = await api.get("/api/timeline?case_id=" + c.id);
    if (!rows.length) return host.append(emptyState("clock", "No timeline yet", "Add events to reconstruct the subject's history."));
    const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [el("th", { text: "When" }),
      el("th", { text: "Type" }), el("th", { text: "Event" }), el("th", { text: "" })])])]);
    const tb = el("tbody");
    for (const e of rows) tb.append(el("tr", {}, [el("td", { text: e.occurred_at || "—" }),
      el("td", {}, [el("span", { class: "tag", text: e.event_type })]),
      el("td", {}, [el("b", { text: e.title }), e.detail ? el("div", { class: "muted small", text: e.detail }) : null]),
      el("td", {}, [button("", { cls: "sm danger", icon: "trash", label: "Delete", onclick: async () => {
        await api.del("/api/timeline/" + e.id); await load(); } })])]));
    tbl.append(tb); host.append(el("div", { class: "tablewrap" }, [tbl]));
  }
}

async function caseReportTab(root, c) {
  root.append(el("div", { class: "card" }, [
    el("div", { class: "between" }, [
      el("div", {}, [el("div", { class: "ch", text: "Investigation report" }),
        el("div", { class: "cd", text: "A clean, printable report with everything from this case — the findings and where they came from, related domains, timeline, and a built-in integrity check. Open it, then Print → Save as PDF." })]),
      icon("doc", "lg"),
    ]),
    el("div", { class: "row", style: "margin-top:16px" }, [
      button("Open report", { cls: "primary", icon: "doc", onclick: () => window.open("/api/cases/" + c.id + "/report", "_blank") }),
      button("Download JSON", { cls: "ghost sm", icon: "database", onclick: () =>
        window.open("/api/reports/export?case_id=" + c.id + "&format=json", "_blank") }),
      button("Download Markdown", { cls: "ghost sm", icon: "doc", onclick: () =>
        window.open("/api/reports/export?case_id=" + c.id + "&format=md", "_blank") }),
    ]),
  ]));
  const box = el("div", { class: "mt" }); root.append(box);
  try {
    const v = await api.get("/api/audit/verify");
    box.append(el("div", { class: "callout " + (v.ok ? "brand" : "bad") }, [icon(v.ok ? "shield" : "alert"),
      el("div", { html: v.ok
        ? `<b>Integrity check passed.</b> All ${v.count} logged actions are intact and unaltered — the report shows this too.`
        : `<b>Integrity check failed</b> at entry #${v.broken_at}. The report will flag this.` })]));
  } catch {}
}

/* ================================ Sources ============================== */
async function sourcesView(root) {
  root.append(...pageHead("Sources & keys",
    "Add API keys to turn on more data sources. Free sources work right away; paid ones need a key. Your keys are encrypted and stored safely."));
  const st = await api.get("/api/vault/status");
  const provs = await api.get("/api/providers");
  const configured = provs.filter(p => p.configured || (!p.requires_key && !p.vault_key)).length;

  root.append(el("div", { class: "stats mb" }, [
    stat(configured + " / " + provs.length, "Sources ready", "key", "accent"),
    stat(provs.filter(p => !p.requires_key && !p.vault_key).length, "Keyless", "check"),
    stat(st.mode === "plaintext" ? "OFF" : (st.unlocked ? "UNLOCKED" : "LOCKED"), "Vault", st.unlocked || st.mode === "plaintext" ? "unlock" : "lock"),
  ]));

  if (st.mode === "encrypted") {
    const locked = !st.unlocked;
    const pass = el("input", { type: "password", placeholder: "vault passphrase", style: "max-width:240px" });
    const row = el("div", { class: "row" }, [pass]);
    if (locked) row.append(button("Unlock vault", { cls: "primary", icon: "unlock", onclick: async () => {
      try { await api.post("/api/vault/unlock", { passphrase: pass.value }); toast("Vault unlocked"); rerender(); }
      catch (e) { toast(e.message, true); } }}));
    else row.append(button("Lock vault", { cls: "ghost", icon: "lock", onclick: async () => {
      await api.post("/api/vault/lock"); toast("Vault locked"); rerender(); } }));
    root.append(el("div", { class: "callout" }, [icon(locked ? "lock" : "unlock"),
      el("div", {}, [el("div", { html: locked
        ? "The key vault is <b>locked</b>. Unlock it to add or edit provider keys."
        : "Vault <b>unlocked</b>. Keys are AES-256-GCM encrypted; the passphrase is never stored and auto-locks when idle." }),
        el("div", { class: "mt" }, [row])])]));
  }

  const editable = st.mode === "plaintext" || st.unlocked;
  const isFree = p => p.pricing === "free" || p.pricing === "freemium";
  const renderGroup = (title, sub, list) => {
    if (!list.length) return;
    root.append(el("div", { class: "h-sec" }, [icon("key"), title]));
    root.append(el("div", { class: "viewhint", text: sub }));
    const grid = el("div", { class: "grid" }); root.append(grid);
    for (const p of list) {
      if (!p.vault_key && !p.requires_key) grid.append(keylessCard(p));
      else grid.append(providerKeyCard(p, editable));
    }
  };
  renderGroup("Free & free-tier sources",
    "No cost to use. Keyless sources work immediately; free-tier sources just need a free API key — tap “Get API key”.",
    provs.filter(isFree));
  renderGroup("Paid subscription sources",
    "These require a paid subscription before their API key will return data. Pricing links are included.",
    provs.filter(p => !isFree(p)));
}

// free | freemium | paid  ->  [badge text, tag css]
function priceTag(pricing) {
  const m = { free: ["free", "ok"], freemium: ["free tier", "ok"], paid: ["paid", "warn"] };
  const [txt, cls] = m[pricing] || ["", ""];
  return txt ? el("span", { class: "tag " + cls, text: txt }) : null;
}

function keylessCard(p) {
  return el("div", { class: "card" }, [
    el("div", { class: "ch" }, [el("span", { style: "display:flex;gap:8px;align-items:center" },
      [el("b", { text: p.name }), el("span", { class: "tag ok", text: "no key needed" })]),
      button("Test", { cls: "sm ghost", icon: "check", onclick: () => testProvider(p.name) })]),
    el("div", { class: "cd", text: "works with: " + p.input_types.join(", ") }),
    p.signup_url ? el("div", { class: "row", style: "margin-top:10px" }, [
      el("a", { class: "btn sm ghost", href: p.signup_url, target: "_blank", rel: "noopener noreferrer" },
        [icon("external", "sm"), el("span", { text: "Open site" })])]) : null,
  ]);
}

function providerKeyCard(p, editable) {
  const inp = el("input", { type: "password", placeholder: p.needs_two_part ? "id:secret" : "API key", disabled: !editable ? "disabled" : null });
  const head = el("div", { class: "ch" }, [
    el("span", { style: "display:flex;gap:8px;align-items:center" }, [el("b", { text: p.name }),
      el("span", { class: "tag " + (p.configured ? "ok" : "warn"), text: p.configured ? "ready" : "add key" }),
      priceTag(p.pricing)]),
    el("span", { class: "tag", text: p.input_types.join(",") }),
  ]);
  // Direct link to the API-key page; second link to sign up / see pricing.
  const getKey = p.key_url ? el("a", { class: "btn sm ghost", href: p.key_url, target: "_blank", rel: "noopener noreferrer" },
    [icon("key", "sm"), el("span", { text: "Get API key" })]) : null;
  const signup = (p.signup_url && p.signup_url !== p.key_url)
    ? el("a", { class: "btn sm ghost", href: p.signup_url, target: "_blank", rel: "noopener noreferrer" },
        [icon("external", "sm"), el("span", { text: p.pricing === "paid" ? "See pricing" : "Sign up free" })]) : null;
  const actions = el("div", { class: "row", style: "margin-top:12px" }, [
    button("Save", { cls: "sm primary", onclick: async () => {
      if (!inp.value) return; try { await api.put("/api/vault/keys/" + p.vault_key, { value: inp.value });
        toast("Key saved"); inp.value = ""; rerender(); } catch (e) { toast(e.message, true); } } }),
    button("Test", { cls: "sm ghost", icon: "check", onclick: () => testProvider(p.name) }),
    getKey, signup,
    p.configured ? button("", { cls: "sm danger", icon: "trash", label: "Remove key", onclick: async () => {
      await api.del("/api/vault/keys/" + p.vault_key); toast("Removed"); rerender(); } }) : null,
  ]);
  return el("div", { class: "card" }, [head, field("Paste key here", inp), actions]);
}

async function testProvider(name) {
  toast("Testing " + name + "…");
  try { const r = await api.post("/api/providers/" + name + "/test");
    toast(name + (r.ok ? ": OK" : ": " + (r.error || "failed")), !r.ok); }
  catch (e) { toast(name + ": " + e.message, true); }
}

/* =============================== Analytics ============================= */
async function analyticsView(root) {
  root.append(...pageHead("Analytics", "Live metrics computed from your investigations — no fabricated numbers."));
  const host = el("div"); root.append(host); host.append(skeleton(3));
  const [o, a] = await Promise.all([api.get("/api/overview"), api.get("/api/analytics")]);
  clear(host);
  host.append(el("div", { class: "stats" }, [
    stat(o.cases, "Cases", "cases", "accent"), stat(o.cases_open, "Open", "cases"),
    stat(a.findings_total, "Findings", "search"), stat(a.findings_hits, "Positive hits", "alert", a.findings_hits ? "badc" : ""),
    stat(o.accounts_without_2fa, "Accounts w/o 2FA", "lock", o.accounts_without_2fa ? "warnc" : ""),
    stat(o.jobs_total, "Jobs run", "activity"),
  ]));
  host.append(el("div", { class: "grid two", style: "margin-top:18px" }, [
    chartCard("Hit rate", ringChart(a.hit_rate, (a.findings_hits) + " of " + a.findings_total + " findings")),
    chartCard("Findings by source", a.findings_by_source.length ? barChart(a.findings_by_source) : emptyMini()),
    chartCard("Findings by target type", a.findings_by_type.length ? barChart(a.findings_by_type) : emptyMini()),
    chartCard("Cases by status", a.cases_by_status.length ? barChart(a.cases_by_status) : emptyMini()),
  ]));
  if (o.breached_emails.length)
    host.append(el("div", { class: "callout bad", style: "margin-top:18px" }, [icon("alert"),
      el("div", { html: "<b>Emails seen in breaches:</b> " + o.breached_emails.map(e => escapeHtml(e)).join(", ") })]));
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function chartCard(title, content) {
  return el("div", { class: "card" }, [el("div", { class: "ch mb", text: title }), content]);
}
function emptyMini() { return el("div", { class: "muted small", text: "No data yet." }); }
function barChart(items) {
  const max = Math.max(1, ...items.map(i => i.value));
  return el("div", { class: "barchart" }, items.map(it => el("div", { class: "bar-row" }, [
    el("div", { class: "bar-lbl", text: it.label, title: it.label }),
    el("div", { class: "bar-track" }, [el("div", { class: "bar-fill", style: `width:${Math.round(it.value / max * 100)}%` })]),
    el("div", { class: "bar-val", text: String(it.value) }),
  ])));
}
function ringChart(pct, label) {
  const r = 34, C = 2 * Math.PI * r;
  const svg = svgEl("svg", { width: 88, height: 88, class: "ring", viewBox: "0 0 88 88" });
  svg.append(svgEl("circle", { class: "track", cx: 44, cy: 44, r, "stroke-width": 9 }));
  svg.append(svgEl("circle", { class: "val", cx: 44, cy: 44, r, "stroke-width": 9,
    "stroke-dasharray": C, "stroke-dashoffset": C * (1 - pct) }));
  return el("div", { style: "display:flex;align-items:center;gap:16px" }, [svg,
    el("div", {}, [el("div", { style: "font-size:26px;font-weight:800", text: Math.round(pct * 100) + "%" }),
      el("div", { class: "muted small", text: label })])]);
}

/* ============================== Audit trail =========================== */
async function auditView(root) {
  root.append(...pageHead("Audit trail",
    "A tamper-proof record of everything important that happens in the app. It's locked so it can't be changed after the fact — check it any time."));
  const banner = el("div"); root.append(banner);
  const host = el("div"); root.append(host); host.append(skeleton(3));
  async function load() {
    const data = await api.get("/api/audit?limit=250");
    clear(banner); clear(host);
    const v = data.integrity;
    banner.append(el("div", { class: "callout " + (v.ok ? "brand" : "bad"), style: "margin-bottom:16px" }, [
      icon(v.ok ? "shield" : "alert"),
      el("div", { style: "flex:1" }, [el("div", { html: v.ok
        ? `<b>All good.</b> ${v.count} entries logged, none altered.`
        : `<b>Tampering detected</b> at entry #${v.broken_at}. The record no longer checks out.` }),
        el("div", { class: "mono small muted", style: "margin-top:4px", text: "tip: " + (v.tip || "").slice(0, 32) + "…" })]),
      button("Verify now", { cls: "sm", icon: "refresh", onclick: async () => {
        const r = await api.get("/api/audit/verify"); toast(r.ok ? "Chain verified ✓" : "Chain broken at #" + r.broken_at, !r.ok); } }),
    ]));
    if (!data.entries.length) return host.append(emptyState("shield", "No audit entries yet", "Actions you take are recorded here."));
    const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [el("th", { text: "Time (UTC)" }),
      el("th", { text: "Actor" }), el("th", { text: "Category" }), el("th", { text: "Action" }), el("th", { text: "Hash" })])])]);
    const tb = el("tbody");
    for (const e of data.entries) tb.append(el("tr", {}, [
      el("td", { class: "small muted", text: (e.ts || "").replace("T", " ") }),
      el("td", { text: e.actor || "—" }), el("td", {}, [el("span", { class: "tag", text: e.category || "—" })]),
      el("td", { text: e.action }), el("td", { class: "mono small muted", text: e.hash_short })]));
    tbl.append(tb); host.append(el("div", { class: "tablewrap" }, [tbl]));
  }
  await load();
}

/* ============================== Activity/Jobs ========================= */
async function jobsView(root) {
  root.append(...pageHead("Activity", "Every tool run and provider lookup, with live status. Tap a row to view output."));
  const wrap = el("div"); root.append(wrap);
  async function load() {
    clear(wrap);
    const jobs = await api.get("/api/jobs?limit=80");
    if (!jobs.length) return wrap.append(emptyState("activity", "No activity yet", "Runs appear here when you investigate."));
    const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [el("th", { text: "" }), el("th", { text: "Kind" }),
      el("th", { text: "Name" }), el("th", { text: "Target" }), el("th", { text: "Status" }), el("th", { text: "When" })])])]);
    const tb = el("tbody");
    for (const j of jobs) {
      const tr = el("tr", { class: "click", onclick: () => showJob(j.id) }, [
        el("td", {}, [statusDot(j.status)]), el("td", {}, [el("span", { class: "tag", text: j.kind })]),
        el("td", { text: j.name }), el("td", { text: j.target }), el("td", { text: j.status }),
        el("td", { class: "small muted", text: (j.created_at || "").replace("T", " ") })]);
      tb.append(tr);
    }
    tbl.append(tb); wrap.append(el("div", { class: "tablewrap" }, [tbl]));
  }
  await load();
  const timer = setInterval(load, 4000); onDispose(() => clearInterval(timer));
}
async function showJob(id) {
  const j = await api.get("/api/jobs/" + id);
  modal(j.name + " · " + j.target, j.status + (j.error ? " — " + j.error : ""),
    [el("pre", { class: "out", text: j.output || j.error || "(no output)" })],
    [button("Close", { cls: "primary", onclick: function () { this.closest(".modal-back").remove(); } })]);
}

/* ================================ Tools =============================== */
async function toolsView(root) {
  topActions(button("Add custom", { cls: "sm primary", icon: "plus", onclick: () => addCustom() }));
  root.append(...pageHead("Tools", "OSINT command-line tools GoFindMe can run for you. Install/update the ones you need."));
  const mgr = await api.get("/api/tools/managers").catch(() => ({ allowed: false, available: {} }));
  root.append(el("div", { class: "callout" }, [icon("tool"), el("div", { text: mgr.allowed
    ? "Package managers detected: " + Object.entries(mgr.available).map(([m, ok]) => `${m} ${ok ? "✓" : "✗"}`).join("   ")
    : "In-app installs are disabled in this build. Install tools on the host and they'll be auto-detected here." })]));
  const grid = el("div", { class: "grid" }); root.append(grid); grid.append(skeleton(4));
  const tools = await api.get("/api/tools");
  clear(grid);
  for (const t of tools) grid.append(toolCard(t, mgr));
}
function toolCard(t, mgr) {
  const head = el("div", { class: "ch" }, [
    el("span", { style: "display:flex;gap:8px;align-items:center" }, [el("b", { text: t.name }),
      el("span", { class: "tag", text: t.interactive ? "GUI" : (t.source === "custom" ? "custom" : "cli") })]),
    el("span", { class: "tag " + (t.available ? "ok" : "warn"), text: t.available ? "installed" : "missing" }),
  ]);
  const meta = el("div", { class: "cd" }, [`accepts: ${(t.accepts || []).join(", ") || "—"}`,
    t.install_method !== "none" ? el("div", { text: `via ${t.install_method}` }) : null]);
  const actions = el("div", { class: "row", style: "margin-top:12px" });
  if (t.url) actions.append(el("a", { class: "btn sm ghost", href: t.url, target: "_blank", rel: "noopener noreferrer" },
    [icon("external", "sm"), el("span", { text: "Home" })]));
  if (t.key_url) actions.append(el("a", { class: "btn sm ghost", href: t.key_url, target: "_blank", rel: "noopener noreferrer" },
    [icon("key", "sm"), el("span", { text: "Get key" })]));
  if (t.available) actions.append(button("Version", { cls: "sm ghost", onclick: () => manage(t.name, "version") }));
  if (mgr.allowed && t.install_method !== "none" && mgr.available[t.install_method])
    actions.append(button(t.available ? "Update" : "Install", { cls: "sm", icon: "refresh",
      onclick: () => manage(t.name, t.available ? "update" : "install") }));
  if (t.interactive) actions.append(button("Copy command", { cls: "sm ghost", icon: "copy", onclick: () => {
    navigator.clipboard.writeText(t.run_template.replace("{bin}", t.bin)); toast("Copied"); } }));
  if (t.source === "custom") actions.append(button("", { cls: "sm danger", icon: "trash", label: "Delete", onclick: async () => {
    if (!confirmAction(`Delete custom tool ${t.name}?`)) return;
    await api.del("/api/tools/custom/" + t.name); toast("Deleted"); rerender(); } }));
  return el("div", { class: "card" }, [head, meta, actions]);
}
async function manage(name, action) {
  try { await api.post("/api/tools/" + name + "/" + action); toast(action + " started"); location.hash = "#/jobs"; }
  catch (e) { toast(e.message, true); }
}
function addCustom() {
  const f = { name: el("input", { placeholder: "mytool" }), bin: el("input", { placeholder: "executable on PATH" }),
    accepts: el("input", { placeholder: "username, domain (comma-separated)" }),
    run_template: el("input", { placeholder: "{bin} -u {target}" }),
    install_method: el("select", {}, ["none", "pip", "pipx", "go", "git", "npm"].map(m => el("option", { value: m, text: m }))),
    install_ref: el("input", { placeholder: "package / module@version / repo url" }) };
  const m = modal("Add custom tool", "Register any CLI tool that takes a target argument.",
    [el("div", { class: "col" }, [field("Name", f.name), field("Binary", f.bin), field("Accepts types", f.accepts),
      field("Run template (must include {target})", f.run_template), field("Install method", f.install_method),
      field("Install reference", f.install_ref)])],
    [button("Cancel", { cls: "ghost", onclick: () => m.close() }),
     button("Save", { cls: "primary", onclick: async () => {
       const accepts = f.accepts.value.split(",").map(s => s.trim()).filter(Boolean);
       try { await api.post("/api/tools/custom", { name: f.name.value.trim(), bin: f.bin.value.trim(), accepts,
         categories: accepts, run_template: f.run_template.value.trim(), install_method: f.install_method.value,
         install_ref: f.install_ref.value.trim() || null });
         m.close(); toast("Saved"); rerender(); } catch (e) { toast(e.message, true); }
     } })]);
}

/* ================================ Data ================================ */
async function dataView(root, params) {
  const sub = params[0] || "identity";
  root.append(...pageHead("Reference data", "Identities, accounts, and notes you maintain across investigations."));
  const TABS = [["identity", "Identities"], ["accounts", "Accounts"], ["notes", "Notes"]];
  root.append(el("div", { class: "subtabs" }, TABS.map(([k, label]) =>
    el("button", { class: "subtab" + (k === sub ? " active" : ""), onclick: () => (location.hash = "#/data/" + k) },
      [el("span", { text: label })]))));
  const body = el("div"); root.append(body);
  await DATA_CRUD[sub](body);
}

function crudView(opts) {
  return async function (root) {
    const formHost = el("div"); const listHost = el("div");
    root.append(formHost, listHost);
    renderForm(); await load();
    function renderForm() {
      clear(formHost);
      const inputs = {};
      const rows = opts.fields.map(fl => {
        let inp;
        if (fl.type === "select") inp = el("select", {}, fl.options.map(o => el("option", { value: o, text: o || "—" })));
        else if (fl.type === "textarea") inp = el("textarea", { placeholder: fl.label });
        else inp = el("input", { placeholder: fl.label, type: fl.type || "text" });
        inputs[fl.key] = inp; return field(fl.label, inp);
      });
      formHost.append(el("div", { class: "card mb" }, [...rows,
        el("div", { class: "row mt" }, [button("Add", { cls: "primary sm", icon: "plus", onclick: add })])]));
      async function add() {
        const body = {};
        for (const fl of opts.fields) {
          let v = inputs[fl.key].value;
          if (fl.type === "number" || fl.coerce === "int") v = v === "" ? null : parseInt(v, 10);
          if (v !== "" && v != null) body[fl.key] = v;
        }
        try { await api.post(opts.path, body); toast("Added"); for (const i of Object.values(inputs)) i.value = ""; await load(); }
        catch (e) { toast(e.message, true); }
      }
    }
    async function load() {
      clear(listHost);
      const rows = await api.get(opts.path);
      if (!rows.length) return listHost.append(emptyState("database", "Nothing yet", "Add your first entry above."));
      const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [...opts.columns.map(c => el("th", { text: c.label })), el("th", { text: "" })])])]);
      const tb = el("tbody");
      for (const r of rows) tb.append(el("tr", {}, [...opts.columns.map(c => el("td", { text: r[c.key] == null ? "" : String(r[c.key]) })),
        el("td", {}, [button("", { cls: "sm danger", icon: "trash", label: "Delete", onclick: async () => {
          if (!confirmAction("Delete this entry?")) return; await api.del(`${opts.path}/${r.id}`); await load(); } })])]));
      tbl.append(tb); listHost.append(el("div", { class: "tablewrap" }, [tbl]));
    }
  };
}
const DATA_CRUD = {
  identity: crudView({ path: "/api/identity",
    columns: [{ key: "kind", label: "Kind" }, { key: "value", label: "Value" }, { key: "label", label: "Label" }],
    fields: [{ key: "kind", label: "Kind", type: "select", options: ["email", "username", "handle", "realname", "phone", "domain"] },
      { key: "value", label: "Value" }, { key: "label", label: "Label" }, { key: "notes", label: "Notes", type: "textarea" }] }),
  accounts: crudView({ path: "/api/accounts",
    columns: [{ key: "service", label: "Service" }, { key: "status", label: "Status" }, { key: "has_2fa", label: "2FA" }, { key: "recovery_status", label: "Recovery" }],
    fields: [{ key: "service", label: "Service" }, { key: "url", label: "URL" },
      { key: "status", label: "Status", type: "select", options: ["", "active", "closed", "unknown"] },
      { key: "has_2fa", label: "2FA (1/0)", type: "select", options: ["", "1", "0"], coerce: "int" },
      { key: "recovery_email", label: "Recovery email" }, { key: "recovery_phone", label: "Recovery phone" },
      { key: "recovery_status", label: "Recovery status", type: "select", options: ["", "configured", "missing", "exposed", "unknown"] }] }),
  notes: crudView({ path: "/api/notes",
    columns: [{ key: "body", label: "Note" }, { key: "created_at", label: "Created" }],
    fields: [{ key: "body", label: "Note", type: "textarea" }] }),
};

/* ================================ Settings ============================ */
async function settingsView(root) {
  root.append(...pageHead("Settings & system", "Deployment details and documentation."));
  const h = await api.get("/api/health");
  root.append(el("div", { class: "grid two" }, [
    el("div", { class: "card" }, [el("div", { class: "ch mb", text: "System" }),
      kv("Version", h.version), kv("Vault", h.vault_mode + (h.vault_unlocked ? " · unlocked" : " · locked")),
      kv("Tool management", h.tool_mgmt ? "enabled" : "disabled"), kv("Packaged build", h.packaged ? "yes" : "no")]),
    el("div", { class: "card" }, [el("div", { class: "ch mb", text: "Data" }),
      kv("Data folder", h.data_dir || "—"), el("div", { class: "small muted", style: "margin-top:8px",
        text: "Your cases, findings and audit trail persist in the database at " + (h.db_path || "—") + ". Back it up by copying that file while the server is stopped." })]),
  ]));
  root.append(el("div", { class: "h-sec" }, [icon("shield"), "Documentation"]));
  root.append(el("div", { class: "grid" }, [
    docCard("Security whitepaper", "Architecture, crypto, controls, and NIST 800-53 alignment.", "docs/SECURITY.md"),
    docCard("Deployment guide", "On-prem, VPS, air-gapped, and desktop deployment.", "docs/DEPLOYMENT.md"),
  ]));
}
function kv(k, v) { return el("div", { class: "row", style: "justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)" },
  [el("span", { class: "muted small", text: k }), el("span", { class: "small", style: "font-weight:600;text-align:right;word-break:break-all", text: v })]); }
function docCard(title, sub, path) {
  return el("div", { class: "card" }, [el("div", { class: "ch", text: title }), el("div", { class: "cd", text: sub }),
    el("div", { class: "mt", text: "See " + path + " in the repository." })]);
}

export const VIEWS = {
  investigate: investigateView, cases: casesView, case: caseView, sources: sourcesView,
  analytics: analyticsView, audit: auditView, jobs: jobsView, tools: toolsView,
  data: dataView, settings: settingsView,
};
