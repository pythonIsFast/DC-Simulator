// Decision modal: big events with options, costs and risks.
import { $, h, money } from "./util.js";
import { store } from "./store.js";
import { run } from "./ui.js";
import { sfx } from "./audio.js";

let currentId = null;        // decision shown in the modal
let showingResult = false;
const dismissed = new Set(); // "decide later"

function close() {
  currentId = null;
  showingResult = false;
  $("decision").hidden = true;
}

function showResult(res) {
  showingResult = true;
  $("decision").replaceChildren(h("div", { class: "card" },
    h("h2", {}, res.bad ? "That did not go well" : "Done"),
    h("p", { class: res.bad ? "bad" : "good" }, res.text),
    h("button", { class: "wide", onclick: () => { sfx.click(); close(); renderDecisions(); } }, "Continue")));
}

function open(d) {
  currentId = d.id;
  showingResult = false;
  const tick = store.state.world.tick;
  const left = Math.max(0, d.expires_tick - tick);
  const modal = $("decision");
  modal.replaceChildren(h("div", { class: "card" },
    h("h2", {}, d.title),
    h("p", {}, d.body),
    h("p", { class: "muted", style: "font-size:.85rem" }, `Decide within ${left} h. Otherwise "${d.options[d.default_option].label}" happens automatically.`),
    ...d.options.map((o, i) => h("div", { class: "item clickable", onclick: async () => {
      const res = await run("resolve_decision", { decision_id: d.id, option: i }, "click");
      if (res) showResult(res);
    } },
    h("div", { class: "title" }, h("span", {}, o.label), h("span", { class: o.cost_cents ? "" : "muted" }, o.cost_cents ? money(o.cost_cents) : "Free")),
    h("div", { class: "sub" }, o.hint, o.risk > 0 ? h("span", { class: "tag bad" }, `Risk ${Math.round(o.risk * 100)} %`) : null))),
    h("button", { class: "secondary small", style: "margin-top:.6rem", onclick: () => { dismissed.add(d.id); close(); renderDecisions(); } }, "Decide later")));
  modal.hidden = false;
  sfx.alarm();
  if (store.state.world.speed > 0) run("set_speed", { speed: 0 });   // pause so the player can think
}

export function renderDecisions() {
  const s = store.state;
  if (!s) return;
  const list = s.decisions || [];
  const badge = $("decision-badge");
  badge.textContent = list.length;
  $("btn-decisions").hidden = list.length === 0;
  if (showingResult) return;
  if (currentId !== null && !list.some((d) => d.id === currentId)) close();   // resolved or expired meanwhile
  if (currentId === null) {
    const next = list.find((d) => !dismissed.has(d.id));
    if (next) open(next);
  }
}

export function reopenDecision() {
  const s = store.state;
  const d = s?.decisions?.[0];
  if (!d) return;
  dismissed.delete(d.id);
  sfx.click();
  if (currentId === null) open(d);
}

export function resetDecisions() { dismissed.clear(); close(); }
