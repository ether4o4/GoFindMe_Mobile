// DOM helpers + inline-SVG icon set. All text goes through textContent so tool
// output / API data can never inject HTML; the `html` key is used ONLY with the
// trusted, static icon markup defined in this file.
export function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "html") e.innerHTML = v; // trusted static strings only
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "for") e.htmlFor = v;
    else e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

/* ------------------------------- icons ------------------------------- */
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  investigate: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6"/><path d="M8 11h6"/>',
  cases: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m10.85 12.15 8.15-8.15"/><path d="m18 5 2 2"/><path d="m15 8 2 2"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 3-3 3 2 4-6"/>',
  shield: '<path d="M12 3 5 6v5c0 4 3 7 7 8 4-1 7-4 7-8V6z"/><path d="m9 12 2 2 4-4"/>',
  activity: '<path d="M22 12h-4l-3 8-4-16-3 8H2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.2V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 8 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.2-2.7H2a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 3.4 8a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.2V2a2 2 0 0 1 4 0v.1A1.6 1.6 0 0 0 16 3.4a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.2 2.7H22a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  graph: '<circle cx="6" cy="12" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><line x1="8.6" y1="10.6" x2="15.4" y2="7.4"/><line x1="8.6" y1="13.4" x2="15.4" y2="16.6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><polyline points="14 3 14 8 19 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>',
  tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  unlock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.9-1"/>',
  home: '<path d="M3 10l9-7 9 7"/><path d="M5 9v11h14V9"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  chevron: '<polyline points="9 18 15 12 9 6"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 15c2.3.6 3.5 2.2 3.5 5"/>',
  print: '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
};
function fromHTML(s) { const t = document.createElement("template"); t.innerHTML = s.trim(); return t.content.firstChild; }
export function icon(name, cls = "") {
  return fromHTML(`<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.dot}</svg>`);
}

/* ------------------------------- toast ------------------------------- */
let toastTimer;
export function toast(msg, isErr = false) {
  let t = document.querySelector(".toast");
  if (!t) { t = el("div", { class: "toast", role: "status", "aria-live": "polite" }); document.body.append(t); }
  clear(t);
  t.append(icon(isErr ? "alert" : "check"), el("span", { text: msg }));
  t.className = "toast show " + (isErr ? "err" : "ok");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 2200);
}

export function field(labelText, input) {
  const id = "f_" + Math.random().toString(36).slice(2, 8);
  input.id = input.id || id;
  return el("div", { class: "field" }, [el("label", { text: labelText, for: input.id }), input]);
}

export function button(text, opts = {}) {
  const kids = [];
  if (opts.icon) kids.push(icon(opts.icon));
  if (text) kids.push(el("span", { text }));
  const b = el("button", { class: "btn " + (opts.cls || ""), onclick: opts.onclick,
    type: "button", "aria-label": opts.label || text || undefined }, kids);
  if (opts.title) b.title = opts.title;
  return b;
}

export function statusDot(status) {
  const map = { done: "ok", running: "run", queued: "warn", error: "bad",
                timeout: "bad", cancelled: "bad" };
  return el("span", { class: "dot " + (map[status] || "warn"), title: status });
}

export function confirmAction(msg) { return window.confirm(msg); }

/* skeleton loader */
export function skeleton(n = 3, cls = "skel-card") {
  return el("div", { class: "grid" }, Array.from({ length: n }, () => el("div", { class: "skel " + cls })));
}

/* empty state */
export function emptyState(iconName, title, sub, action) {
  return el("div", { class: "empty" }, [icon(iconName, "lg"), el("h4", { text: title }),
    sub ? el("p", { text: sub }) : null, action || null]);
}

/* modal dialog */
export function modal(title, sub, body, actions) {
  const back = el("div", { class: "modal-back", onclick: e => { if (e.target === back) close(); } });
  function close() { back.remove(); document.removeEventListener("keydown", onKey); }
  function onKey(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", onKey);
  const card = el("div", { class: "modal", role: "dialog", "aria-modal": "true" }, [
    el("h3", { text: title }),
    sub ? el("div", { class: "sub", text: sub }) : null,
    ...[].concat(body),
    el("div", { class: "row", style: "margin-top:20px;justify-content:flex-end" }, actions),
  ]);
  back.append(card);
  document.body.append(back);
  return { close };
}

/* Disposer registry (EventSource.close / clearInterval) run by the router on nav. */
const _disposers = [];
export function onDispose(fn) { _disposers.push(fn); }
export function runDisposers() { while (_disposers.length) { try { _disposers.pop()(); } catch {} } }
