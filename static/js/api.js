// Thin fetch wrapper: bearer token from localStorage, JSON in/out, 401 handling.
const TOKEN_KEY = "gfm_token";

export function getToken() { return localStorage.getItem(TOKEN_KEY); }
export function setToken(t) { if (t) localStorage.setItem(TOKEN_KEY, t); }
export function clearToken() { localStorage.removeItem(TOKEN_KEY); }

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function req(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const opts = { method, headers, credentials: "same-origin" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, "Authentication required");
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) {
    const msg = (data && (data.detail || data.error)) || res.statusText;
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg), data);
  }
  return data;
}

export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}

// Multipart upload: sends a FormData (files) with the bearer token, no JSON body.
async function upload(path, fileList, field = "uploads") {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const fd = new FormData();
  for (const f of fileList) fd.append(field, f, f.name);
  const res = await fetch(path, { method: "POST", headers, body: fd, credentials: "same-origin" });
  if (res.status === 401) { onUnauthorized(); throw new ApiError(401, "Authentication required"); }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) {
    const msg = (data && (data.detail || data.error)) || res.statusText;
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg), data);
  }
  return data;
}

export const api = {
  get: (p) => req("GET", p),
  post: (p, b) => req("POST", p, b),
  put: (p, b) => req("PUT", p, b),
  del: (p) => req("DELETE", p),
  upload,
};

// SSE helper. Returns the EventSource so callers can close it.
export function streamJob(jobId, onEvent) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)); } catch {}
  };
  es.onerror = () => { es.close(); };
  return es;
}
