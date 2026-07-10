import { api, setToken, clearToken, getToken, setUnauthorizedHandler } from "./api.js";
import { el, clear, toast, button, field, icon, runDisposers } from "./ui.js";
import { VIEWS, setRerender, setPrefill } from "./views.js";

const app = document.getElementById("app");

// Primary nav (sidebar) + which appear in the mobile bottom bar.
const NAV = [
  { key: "investigate", label: "Investigate", icon: "investigate", mobile: true },
  { key: "cases", label: "Cases", icon: "cases", mobile: true },
  { key: "sources", label: "Sources", icon: "key", mobile: true },
  { key: "analytics", label: "Analytics", icon: "chart", mobile: false },
  { key: "audit", label: "Audit Trail", icon: "shield", mobile: true },
];
const ADV = [
  { key: "jobs", label: "Activity", icon: "activity" },
  { key: "tools", label: "Tools", icon: "tool" },
  { key: "data", label: "Data", icon: "database" },
  { key: "settings", label: "Settings", icon: "settings", mobile: true },
];
const LABELS = Object.fromEntries([...NAV, ...ADV].map(n => [n.key, n.label]));

let me = null;

setUnauthorizedHandler(() => { clearToken(); showLogin(); });
boot();

async function boot() {
  let health;
  try { health = await api.get("/api/health"); }
  catch { app.textContent = "Cannot reach the GoFindMe server."; return; }
  if (!health.setup_complete) return showSetup();
  if (!getToken()) return showLogin();
  try { me = await api.get("/api/me"); renderShell(); }
  catch { showLogin(); }
}

/* ------------------------------ brand mark ------------------------------ */
function brandmark(withTag = true) {
  return el("div", { class: "brandmark" }, [
    el("div", { class: "glyph" }, [icon("investigate")]),
    el("div", {}, [
      el("div", { class: "wm", text: "GoFindMe" }),
      withTag ? el("div", { class: "tag", text: "Mobile · Investigations" }) : null,
    ]),
  ]);
}

/* ------------------------------ auth screens ---------------------------- */
// onSubmit receives a `showErr` callback so failures render inline on the card
// (a bottom toast is easily hidden behind the phone keyboard).
function authShell(title, subtitle, inputs, submitText, onSubmit) {
  clear(app);
  const err = el("div", { class: "auth-err hidden", role: "alert", "aria-live": "assertive" });
  const showErr = msg => { err.textContent = msg || ""; err.classList.toggle("hidden", !msg); };
  let busy = false;
  const submit = async () => {
    if (busy) return;
    busy = true; showErr("");
    try { await onSubmit(showErr); } finally { busy = false; }
  };
  const card = el("div", { class: "authcard" }, [
    brandmark(),
    el("h1", { text: title }),
    el("div", { class: "sub", text: subtitle }),
    el("div", { class: "col", style: "margin-top:8px" }, [
      ...Object.entries(inputs).map(([k, i]) => field(k, i)),
      err,
      button(submitText, { cls: "primary block lg", onclick: submit }),
    ]),
  ]);
  Object.values(inputs).forEach(i => i.addEventListener("keydown", e => { if (e.key === "Enter") submit(); }));
  app.append(el("div", { class: "authwrap" }, [card]));
}

function showSetup() {
  const inputs = {
    Username: el("input", { autocomplete: "username", placeholder: "e.g. analyst" }),
    Password: el("input", { type: "password", autocomplete: "new-password", placeholder: "at least 8 characters" }),
  };
  authShell("Create owner account", "One-time setup for this console.", inputs, "Create account", async showErr => {
    const username = inputs.Username.value.trim();
    const password = inputs.Password.value;
    if (!username) return showErr("Enter a username.");
    if (password.length < 8) return showErr("Password must be at least 8 characters.");
    try {
      const r = await api.post("/api/auth/setup", { username, password });
      setToken(r.token); me = { username }; renderShell();
    } catch (e) { showErr(e.message); }
  });
}

function showLogin() {
  const inputs = {
    Username: el("input", { autocomplete: "username" }),
    Password: el("input", { type: "password", autocomplete: "current-password" }),
  };
  authShell("Sign in", "Access your investigations console.", inputs, "Sign in", async showErr => {
    const username = inputs.Username.value.trim();
    const password = inputs.Password.value;
    if (!username || !password) return showErr("Enter your username and password.");
    try {
      const r = await api.post("/api/auth/login", { username, password });
      setToken(r.token); me = { username }; renderShell();
    } catch (e) { showErr(e.message); }
  });
}

/* -------------------------------- app shell ----------------------------- */
function navButton(item) {
  return el("button", { class: "navlink", "data-route": item.key,
    onclick: () => { location.hash = "#/" + item.key; } },
    [icon(item.icon), el("span", { text: item.label })]);
}

function renderShell() {
  clear(app);
  const uname = (me && me.username) || "operator";
  const sidebar = el("aside", { class: "sidebar" }, [
    brandmark(),
    ...NAV.map(navButton),
    el("div", { class: "navsec", text: "Advanced" }),
    ...ADV.map(navButton),
    el("div", { class: "grow" }),
    el("div", { class: "userchip" }, [
      el("div", { class: "av", text: uname.slice(0, 1).toUpperCase() }),
      el("div", { style: "min-width:0;flex:1" }, [
        el("div", { class: "nm", text: uname }), el("div", { class: "ro", text: "Owner · single-user" })]),
      button("", { cls: "sm ghost", icon: "logout", label: "Log out", onclick: logout }),
    ]),
  ]);

  const topbar = el("header", { class: "topbar" }, [
    el("div", { class: "crumbs", id: "crumbs" }, [el("h1", { id: "page-title", text: "Investigate" })]),
    el("div", { class: "sp" }),
    el("div", { id: "topbar-actions", class: "row" }),
  ]);
  const main = el("main", { class: "main" }, [topbar, el("div", { class: "content", id: "view" })]);

  const mob = el("nav", { class: "mobnav" }, [...NAV.filter(n => n.mobile), ...ADV.filter(n => n.mobile)]
    .map(item => el("button", { "data-route": item.key, onclick: () => { location.hash = "#/" + item.key; } },
      [icon(item.icon), el("span", { text: item.label })])));

  app.append(el("div", { class: "app-shell" }, [sidebar, main]), mob);

  setRerender(() => renderRoute(parseHash()));
  window.addEventListener("hashchange", () => renderRoute(parseHash()));
  renderRoute(parseHash());
}

function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const route = parts[0] || "investigate";
  return { route: VIEWS[route] ? route : "investigate", params: parts.slice(1) };
}

async function renderRoute({ route, params }) {
  runDisposers();
  for (const t of document.querySelectorAll(".navlink, .mobnav button"))
    t.classList.toggle("active", t.dataset.route === route);
  // reset header
  const crumbs = document.getElementById("crumbs");
  clear(crumbs); crumbs.append(el("h1", { id: "page-title", text: LABELS[route] || "Investigate" }));
  clear(document.getElementById("topbar-actions"));
  const view = document.getElementById("view");
  clear(view);
  try {
    await VIEWS[route](view, params);
  } catch (e) {
    view.append(el("div", { class: "callout bad" }, [icon("alert"), el("div", { text: "Error: " + e.message })]));
  }
  window.scrollTo(0, 0);
}

async function logout() {
  try { await api.post("/api/auth/logout"); } catch {}
  clearToken(); showLogin();
}
