// HUD, toasts, banners and money display.
import { $, h, money, signedMoney, dateText } from "./util.js";
import { store, send, ticksSinceSync } from "./store.js";
import { sfx } from "./audio.js";

export function toast(msg, kind = "") {
  const el = h("div", { class: "toast " + kind }, msg);
  $("toasts").append(el);
  while ($("toasts").children.length > 5) $("toasts").firstChild.remove();
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 350); }, 4500);
}

export function banner(title, sub) {
  const el = $("banner");
  el.replaceChildren(h("b", {}, title), sub);
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth; // restart the CSS animation
  el.style.animation = "";
  clearTimeout(banner.t);
  banner.t = setTimeout(() => { el.hidden = true; }, 3300);
}

// Run a command; shows the server error as a toast. Returns the result or null.
export async function run(type, payload = {}, sound = null) {
  try {
    const result = await send(type, payload);
    if (sound) sfx[sound]();
    return result;
  } catch (e) {
    toast(e.message, "bad");
    sfx.error();
    return null;
  }
}

export function moneyPopup(cents) {
  if (!cents) return;
  const el = h("div", { class: "popup " + (cents > 0 ? "in" : "out"), style: `left:${Math.round(Math.random() * 40)}px` }, signedMoney(cents));
  $("popups").append(el);
  setTimeout(() => el.remove(), 1700);
}

let shownCash = null;
export function bumpCash() {
  const el = $("cash");
  el.classList.remove("bump");
  void el.offsetWidth;
  el.classList.add("bump");
}

// Called every frame: smoothly ticks the cash display towards the expected value.
export function animateMoney(dt) {
  const s = store.state;
  if (!s) return;
  const net = s.company.revenue_cents_per_tick - s.company.expense_cents_per_tick;
  const target = s.company.cash_cents + net * ticksSinceSync();
  if (shownCash === null) shownCash = target;
  shownCash += (target - shownCash) * Math.min(1, dt * 6);
  const text = money(shownCash);
  const el = $("cash");
  if (el.textContent !== text) el.textContent = text;
  el.style.color = target < 0 ? "var(--bad)" : "";
}

export function resetMoney() { shownCash = null; }

export function renderHud() {
  const s = store.state;
  if (!s) return;
  const net = s.company.revenue_cents_per_tick - s.company.expense_cents_per_tick;
  const netEl = $("net");
  netEl.textContent = `${signedMoney(net)}/h`;
  netEl.className = net >= 0 ? "good" : "bad";
  $("date").textContent = dateText(s.world.tick);
  document.querySelectorAll("#speed-buttons button").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.speed) === s.world.speed);
  });
}
