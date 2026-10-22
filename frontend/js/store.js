// Client-side state: latest server snapshot, view navigation and a tiny event bus.
import { api } from "./api.js";

const listeners = {};
export const bus = {
  on(name, fn) { (listeners[name] ||= new Set()).add(fn); return () => listeners[name].delete(fn); },
  emit(name, data) { (listeners[name] || []).forEach((fn) => fn(data)); },
};

export const store = {
  worldId: null,
  state: null,
  prev: null,
  syncedAt: 0,           // performance.now() of the last snapshot
  cursor: null,          // last seen event id
  hw: { list: [], byCode: {}, rules: {} },
  view: { mode: "globe", regionId: null, dcId: null, rackId: null },
};

export async function loadHardware() {
  const data = await api.hardware();
  store.hw.list = data.hardware;
  store.hw.byCode = Object.fromEntries(data.hardware.map((h) => [h.code, h]));
  store.hw.rules = data.rules;
}

function accept(state) {
  const first = store.state === null;
  store.prev = store.state;
  store.state = state;
  store.syncedAt = performance.now();
  // A poll and a command response may overlap: only forward events newer than the cursor.
  const events = (state.events || []).filter((e) => store.cursor == null || e.id > store.cursor);
  if (state.latest_event_id != null) store.cursor = Math.max(store.cursor ?? 0, state.latest_event_id);
  bus.emit("state", state);
  if (events.length) bus.emit("events", { events, initial: first });
}

export async function sync() {
  const state = await api.getWorld(store.worldId, store.cursor);
  accept(state);
  return state;
}

// Send a command; resolves with the result or rejects with the server's error message.
export async function send(type, payload = {}) {
  const res = await api.command(store.worldId, type, payload, store.cursor);
  accept(res.state);
  return res.result;
}

export function resetStore(worldId) {
  store.worldId = worldId;
  store.state = null;
  store.prev = null;
  store.cursor = null;
  store.view = { mode: "globe", regionId: null, dcId: null, rackId: null };
}

export function setView(patch) {
  store.view = { ...store.view, ...patch };
  bus.emit("view", store.view);
}

// ---- derived helpers
export const regionById = (id) => store.state?.regions.find((r) => r.id === id);
export const dcById = (id) => store.state?.datacenters.find((d) => d.id === id);
export function rackById(id) {
  for (const dc of store.state?.datacenters || []) {
    const r = dc.racks.find((x) => x.id === id);
    if (r) return { rack: r, dc };
  }
  return null;
}

// Expected tick progress since the last snapshot (for smooth money/clock interpolation).
export function ticksSinceSync() {
  const s = store.state;
  if (!s || !s.world.speed) return 0;
  const elapsed = (performance.now() - store.syncedAt) / 1000;
  return Math.min(1.2, (elapsed * s.world.speed) / s.world.seconds_per_tick);
}
