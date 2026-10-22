// Phase 1 test UI: auth, world list, world state, time control.
import { api, getToken, setToken } from "./api.js";

const $ = (id) => document.getElementById(id);
const views = ["view-auth", "view-worlds", "view-world"];
let currentWorldId = null;
let pollTimer = null;

function show(view) {
  views.forEach((v) => ($(v).hidden = v !== view));
  clearInterval(pollTimer);
  $("msg").textContent = "";
}

const fail = (e) => {
  if (e.status === 401 && getToken()) {
    setToken(null);
    show("view-auth");
  }
  $("msg").textContent = e.message;
};

const money = (cents) => (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

function li(text) {
  const el = document.createElement("li");
  el.textContent = text;
  return el;
}

async function showWorlds() {
  show("view-worlds");
  $("who").textContent = localStorage.getItem("dc_user") || "";
  try {
    const { worlds } = await api.listWorlds();
    const list = $("world-list");
    list.replaceChildren();
    for (const w of worlds) {
      const item = li(`${w.name} (tick ${w.tick}) `);
      const btn = document.createElement("button");
      btn.textContent = "Open";
      btn.addEventListener("click", () => openWorld(w.id));
      item.append(btn);
      list.append(item);
    }
  } catch (e) { fail(e); }
}

function render(state) {
  $("world-title").textContent = state.world.name;
  $("tick").textContent = state.world.tick;
  $("cash").textContent = money(state.company.cash_cents);
  document.querySelectorAll("#speed-buttons button").forEach((b) => {
    b.disabled = Number(b.dataset.speed) === state.world.speed;
  });
  $("rivals").replaceChildren(...state.rivals.map((r) => li(r.name)));
  $("regions").replaceChildren(
    ...state.regions.map((r) => li(`${r.name} (${r.code}) - ${r.unlocked ? "unlocked" : "locked"}`)),
  );
}

async function refresh() {
  try { render(await api.getWorld(currentWorldId)); } catch (e) { fail(e); }
}

async function openWorld(id) {
  currentWorldId = id;
  show("view-world");
  await refresh();
  pollTimer = setInterval(refresh, 2000);
}

$("auth-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const mode = ev.submitter.dataset.mode;
  try {
    const res = await api[mode]($("auth-user").value, $("auth-pass").value);
    setToken(res.token);
    localStorage.setItem("dc_user", res.username);
    showWorlds();
  } catch (e) { fail(e); }
});

$("world-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const res = await api.createWorld(
      $("world-name").value || undefined,
      $("company-name").value || undefined,
      Number($("ai-count").value),
    );
    openWorld(res.world_id);
  } catch (e) { fail(e); }
});

$("speed-buttons").addEventListener("click", async (ev) => {
  const speed = ev.target.dataset?.speed;
  if (speed === undefined) return;
  try {
    const res = await api.command(currentWorldId, "set_speed", { speed: Number(speed) });
    render(res.state);
  } catch (e) { fail(e); }
});

$("logout").addEventListener("click", () => { setToken(null); show("view-auth"); });
$("back").addEventListener("click", showWorlds);

getToken() ? showWorlds() : show("view-auth");
