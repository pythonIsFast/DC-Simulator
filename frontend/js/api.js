// Thin API client. The server is authoritative; the client only sends commands.
const TOKEN_KEY = "dc_token";
const REQUEST_TIMEOUT_MS = 10000;

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

async function request(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  // A request that never settles (e.g. a loopback socket that died while the app was in the background)
  // must not block the poll loop forever.
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: "no-store", signal: ctl.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

const since = (cursor) => (cursor == null ? "" : `?since_event=${cursor}`);

export const api = {
  register: (username, password) => request("POST", "/api/auth/register", { username, password }),
  local: () => request("POST", "/api/auth/local"),
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  listWorlds: () => request("GET", "/api/worlds"),
  createWorld: (name, company_name, ai_count) => request("POST", "/api/worlds", { name, company_name, ai_count }),
  hardware: () => request("GET", "/api/worlds/hardware"),
  getWorld: (id, cursor) => request("GET", `/api/worlds/${id}${since(cursor)}`),
  command: (id, type, payload = {}, cursor) =>
    request("POST", `/api/worlds/${id}/commands${since(cursor)}`, { type, payload }),
};
