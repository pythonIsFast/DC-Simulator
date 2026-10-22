// Thin API client. The server is authoritative; the client only sends commands.
const TOKEN_KEY = "dc_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

async function request(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  register: (username, password) => request("POST", "/api/auth/register", { username, password }),
  local: () => request("POST", "/api/auth/local"),
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  listWorlds: () => request("GET", "/api/worlds"),
  createWorld: (name, company_name, ai_count) => request("POST", "/api/worlds", { name, company_name, ai_count }),
  getWorld: (id) => request("GET", `/api/worlds/${id}`),
  command: (id, type, payload = {}) => request("POST", `/api/worlds/${id}/commands`, { type, payload }),
};
