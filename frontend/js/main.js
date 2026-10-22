// Entry point: menu, world loading, navigation between globe / room / rack view, input.
import { api, getToken, setToken } from "./api.js";
import { store, bus, resetStore, sync, setView, regionById, dcById, rackById, loadHardware } from "./store.js";
import { initStage, setStageView } from "./stage.js";
import { createGlobeView } from "./globe.js";
import { createRoomView } from "./room.js";
import { createRackView } from "./rack.js";
import { $, h, money } from "./util.js";
import { toast, banner, run, moneyPopup, animateMoney, renderHud, resetMoney, bumpCash } from "./ui.js";
import { renderGuide } from "./guide.js";
import { renderDecisions, reopenDecision, resetDecisions } from "./decisions.js";
import { renderContext, currentTemplate } from "./panels.js";
import { toggleDrawer, addLog, resetDrawers } from "./drawers.js";
import { sfx, setFanLevel, toggleMute, isMuted } from "./audio.js";

const nav = (patch) => bus.emit("nav", patch);
let views = null;
let pollTimer = null;
let syncing = false;
let localMode = false;
let roomSig = "";
let rackSig = "";
let lastCashSound = 0;
let lastSpeed = 1;

// ------------------------------------------------------------------ menu / auth

const menuViews = ["view-auth", "view-worlds"];
function showMenu(view) {
  $("menu").hidden = false;
  $("hud").hidden = true;
  menuViews.forEach((v) => ($(v).hidden = v !== view));
  $("msg").textContent = "";
}

async function startLocalSession() {
  try {
    setToken((await api.local()).token);
    localMode = true;
    return true;
  } catch {
    localMode = false;
    return false;
  }
}

async function fail(e) {
  if (e.status === 401) {
    if (localMode && (await startLocalSession())) return showWorlds();
    setToken(null);
    return showMenu("view-auth");
  }
  $("msg").textContent = e.message;
}

async function showWorlds() {
  stopPolling();
  showMenu("view-worlds");
  $("who-line").hidden = localMode;
  $("who").textContent = localStorage.getItem("dc_user") || "";
  try {
    const { worlds } = await api.listWorlds();
    const list = $("world-list");
    list.replaceChildren(...worlds.map((w) => h("li", {}, h("span", {}, `${w.name} `, h("span", { class: "muted" }, `(tick ${w.tick})`)),
      h("button", { class: "small", onclick: () => openWorld(w.id) }, "Open"))));
    if (!worlds.length) list.replaceChildren(h("li", { class: "muted" }, "No worlds yet. Create one below."));
  } catch (e) { fail(e); }
}

$("auth-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const res = await api[ev.submitter.dataset.mode]($("auth-user").value, $("auth-pass").value);
    setToken(res.token);
    localStorage.setItem("dc_user", res.username);
    showWorlds();
  } catch (e) { fail(e); }
});

$("world-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const res = await api.createWorld($("world-name").value || undefined, $("company-name").value || undefined, Number($("ai-count").value));
    openWorld(res.world_id);
  } catch (e) { fail(e); }
});

$("logout").addEventListener("click", () => { setToken(null); showMenu("view-auth"); });
$("btn-decisions").addEventListener("click", reopenDecision);
$("btn-menu").addEventListener("click", () => { sfx.click(); showWorlds(); });

// ------------------------------------------------------------------ views

function ensureViews() {
  if (views) return views;
  const canvas = $("scene");
  initStage(canvas);
  const tooltip = $("tooltip");
  views = {
    globe: createGlobeView(canvas, $("labels"), (id) => { sfx.click(); nav({ mode: "globe", regionId: id }); }),
    room: createRoomView(canvas, tooltip, {
      onRack: (r) => { sfx.click(); nav({ mode: "rack", dcId: store.view.dcId, rackId: r.id }); },
      onSlot: (slot) => bus.emit("buy-rack", { template: currentTemplate(), slot }),
    }),
    rack: createRackView(canvas, tooltip, {
      onSelect: (item) => bus.emit("select", item),
      onInstall: (code, u) => bus.emit("install", { code, u }),
      onMove: async (itemId, u) => { await run("move_item", { item_id: itemId, u_start: u }, "mount"); },
      onInvalid: () => { sfx.error(); toast("That does not fit there", "warn"); },
    }),
  };
  return views;
}

bus.on("nav", (p) => {
  const s = store.state;
  if (!s || !views) return;
  if (p.mode === "globe") {
    setView({ mode: "globe", regionId: p.regionId ?? null, dcId: null, rackId: null });
    setStageView(views.globe);
    views.globe.select(p.regionId ?? null);
    if (p.regionId) views.globe.focusRegion(p.regionId);
  } else if (p.mode === "room") {
    const dc = dcById(p.dcId);
    if (!dc) return;
    setView({ mode: "room", regionId: dc.region_id, dcId: dc.id, rackId: null });
    views.room.setDatacenter(dc);
    roomSig = JSON.stringify([dc.racks, dc.cooling_kw]);
    views.room.setPeople({ employees: s.team.employees, orders: s.team.orders, racks: dc.racks, dcId: dc.id });
    setStageView(views.room);
  } else if (p.mode === "rack") {
    const found = rackById(p.rackId);
    if (!found) return;
    setView({ mode: "rack", regionId: found.dc.region_id, dcId: found.dc.id, rackId: found.rack.id });
    views.rack.select(null);
    views.rack.setRack(found.rack, found.dc);
    rackSig = JSON.stringify(found.rack);
    setStageView(views.rack);
  }
  renderCrumbs();
  updateFan();
});

function renderCrumbs() {
  const v = store.view;
  const parts = [h("button", { class: "secondary small", onclick: () => nav({ mode: "globe" }) }, "World")];
  if (v.mode !== "globe") {
    const region = regionById(v.regionId), dc = dcById(v.dcId);
    parts.push(h("span", { class: "sep" }, "›"), h("button", { class: "secondary small", onclick: () => nav({ mode: "globe", regionId: v.regionId }) }, region?.name || "Region"));
    if (dc) parts.push(h("span", { class: "sep" }, "›"), h("button", { class: "secondary small", onclick: () => nav({ mode: "room", dcId: dc.id }) }, dc.name));
    if (v.mode === "rack") parts.push(h("span", { class: "sep" }, "›"), h("span", {}, rackById(v.rackId)?.rack.name || "Rack"));
  }
  $("crumbs").replaceChildren(...parts);
}

function updateFan() {
  const v = store.view;
  const dc = v.mode === "globe" ? null : dcById(v.dcId);
  if (!dc) { setFanLevel(0); return; }
  const heat = dc.cooling_cap_kw ? dc.heat_kw / dc.cooling_cap_kw : 0;
  setFanLevel(Math.min(1, heat * 0.6 + dc.util * 0.4));
}

// ------------------------------------------------------------------ state updates

bus.on("state", (state) => {
  if (!views) return;
  renderHud();
  renderGuide();
  renderDecisions();
  views.globe.setData(state);
  const v = store.view;
  if (v.mode === "room") {
    const dc = dcById(v.dcId);
    if (!dc) { nav({ mode: "globe" }); return; }
    const sig = JSON.stringify([dc.racks, dc.cooling_kw]);
    if (sig !== roomSig) { roomSig = sig; views.room.setDatacenter(dc); }
    views.room.setUtil(dc.util);
    views.room.setPeople({ employees: state.team.employees, orders: state.team.orders, racks: dc.racks, dcId: dc.id });
  } else if (v.mode === "rack") {
    const found = rackById(v.rackId);
    if (!found) { nav({ mode: "room", dcId: v.dcId }); return; }
    const sig = JSON.stringify(found.rack);
    if (sig !== rackSig && !views.rack.isDragging()) { rackSig = sig; views.rack.setRack(found.rack, found.dc); }
    else views.rack.setDc(found.dc);
  }
  renderCrumbs();
  renderContext();
  updateFan();
  if (state.world.speed) lastSpeed = state.world.speed;

  // Floating money popups
  const prev = store.prev;
  if (prev && prev.world.id === state.world.id) {
    const ticks = state.world.tick - prev.world.tick;
    if (ticks > 0) {
      const net = (state.company.revenue_cents_per_tick - state.company.expense_cents_per_tick) * ticks;
      moneyPopup(net);
      if (state.company.revenue_cents_per_tick > 0 && performance.now() - lastCashSound > 4000) { sfx.cash(); lastCashSound = performance.now(); }
    } else if (state.company.cash_cents !== prev.company.cash_cents) {
      moneyPopup(state.company.cash_cents - prev.company.cash_cents);
    }
  }
});

const EVENT_STYLE = {
  incident: "bad", breaker_trip: "bad", thermal_shutdown: "bad", contract_breached: "bad",
  grid_outage: "warn", heatwave: "warn", power_spike: "warn", sla_warning: "warn",
  contract_completed: "good", incident_absorbed: "good", rack_recovered: "good", market_boom: "good",
  decision: "warn", work_done: "good", promotion: "good", sales_signed: "good", research_done: "good", auto_approved: "good", auto_hired: "good", work_failed: "bad", proposal: "",
};

bus.on("events", ({ events, initial }) => {
  addLog(events);
  if (initial) return;
  for (const e of events) {
    if (e.kind === "milestone") {
      banner("Milestone reached!", `${e.message.replace("Milestone: ", "")}  +${money(e.reward_cents)}`);
      sfx.milestone();
      bumpCash();
      continue;
    }
    const style = EVENT_STYLE[e.kind] || "";
    toast(e.message, style);
    if (style === "bad") sfx.alarm();
  }
});

// ------------------------------------------------------------------ commands from panels and views

bus.on("buy-rack", async ({ template, slot }) => {
  const payload = { datacenter_id: store.view.dcId };
  if (template) payload.template_id = Number(template);
  if (slot !== undefined) payload.slot = slot;
  await run("buy_rack", payload, "mount");
});
bus.on("install", async ({ code, u }) => { await run("install_item", { rack_id: store.view.rackId, code, u_start: u }, "mount"); });
bus.on("remove", async (id) => { if (await run("remove_item", { item_id: id }, "unmount")) views.rack.select(null); });
bus.on("palette", (code) => { if (!views) return; views.rack.dragCode = code; if (!code) views.rack.clearDrag(); });
bus.on("heatmap", (on) => views?.room.setHeatmap(on));

// ------------------------------------------------------------------ HUD controls

$("speed-buttons").addEventListener("click", (ev) => {
  const speed = ev.target.dataset?.speed;
  if (speed === undefined) return;
  sfx.click();
  run("set_speed", { speed: Number(speed) });
});
document.querySelectorAll("[data-drawer]").forEach((b) => b.addEventListener("click", () => toggleDrawer(b.dataset.drawer)));
$("btn-mute").addEventListener("click", () => {
  const muted = toggleMute();
  $("btn-mute").textContent = muted ? "\u{1F507}" : "\u{1F50A}";
  updateFan();
});
$("btn-mute").textContent = isMuted() ? "\u{1F507}" : "\u{1F50A}";

window.addEventListener("keydown", (ev) => {
  if (!store.state || ["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName)) return;
  const speeds = { Digit1: 1, Digit2: 2, Digit3: 5 };
  if (ev.code === "Space") { ev.preventDefault(); run("set_speed", { speed: store.state.world.speed ? 0 : lastSpeed }); }
  else if (speeds[ev.code]) run("set_speed", { speed: speeds[ev.code] });
  else if (ev.code === "KeyM") $("btn-mute").click();
  else if (ev.code === "Escape") {
    const v = store.view;
    if (v.mode === "rack") nav({ mode: "room", dcId: v.dcId });
    else if (v.mode === "room") nav({ mode: "globe", regionId: v.regionId });
    else if (v.regionId) nav({ mode: "globe" });
  } else if ((ev.code === "Delete" || ev.code === "Backspace") && store.view.mode === "rack") {
    const id = views.rack.selected();
    if (id != null) bus.emit("remove", id);
  }
});

// ------------------------------------------------------------------ world lifecycle

function stopPolling() { clearInterval(pollTimer); pollTimer = null; setFanLevel(0); }

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    if (syncing) return;
    syncing = true;
    try { await sync(); } catch (e) { if (e.status === 401 || e.status === 404) { stopPolling(); fail(e); } } finally { syncing = false; }
  }, 1500);
}

async function openWorld(id) {
  try {
    resetStore(id);
    resetMoney();
    resetDrawers();
    resetDecisions();
    roomSig = rackSig = "";
    if (!store.hw.list.length) await loadHardware();
    ensureViews();
    $("menu").hidden = true;
    $("hud").hidden = false;
    setView({ mode: "globe", regionId: null, dcId: null, rackId: null });
    setStageView(views.globe);
    views.globe.select(null);
    views.room.setHeatmap(false);
    await sync();
    startPolling();
  } catch (e) {
    showMenu("view-worlds");
    fail(e);
  }
}

let lastFrame = performance.now();
(function frame(now) {
  requestAnimationFrame(frame);
  animateMoney(Math.min(0.1, (now - lastFrame) / 1000));
  lastFrame = now;
})(performance.now());

// Boot: local mode needs no login; otherwise reuse a stored token or show the login form.
(async () => {
  if (await startLocalSession()) return showWorlds();
  getToken() ? showWorlds() : showMenu("view-auth");
})();
