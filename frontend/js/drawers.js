// Left drawer: contracts, market, event log and milestones.
import { $, h, money, money2, num, pct, bar, stat, dateText } from "./util.js";
import { store, bus, regionById } from "./store.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";

let open = null;       // name of the open drawer or null
let tab = "offers";
let lastSig = "";
const log = [];        // newest first

export function addLog(events) {
  for (const e of events) log.unshift(e);
  log.length = Math.min(log.length, 120);
  if (open === "log") renderDrawer(true);
}

export function toggleDrawer(name) {
  open = open === name ? null : name;
  document.querySelectorAll("[data-drawer]").forEach((b) => b.classList.toggle("active", b.dataset.drawer === open));
  sfx.click();
  renderDrawer(true);
}

export function resetDrawers() { open = null; log.length = 0; lastSig = ""; $("drawer").hidden = true; }

export function renderDrawer(force = false) {
  const el = $("drawer");
  const s = store.state;
  if (!open || !s) { el.hidden = true; return; }
  const sig = open + tab + JSON.stringify(open === "contracts" ? [s.offers, s.contracts, s.datacenters.map((d) => [d.region_id, d.racks.map((r) => [r.online, r.stats.cpu, r.stats.storage_tb, r.stats.gpu])])]
    : open === "market" ? [s.market_share, s.rivals, s.company.net_worth_cents] : open === "goals" ? s.milestones : log.length);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  el.hidden = false;
  const body = { contracts: contractsView, market: marketView, log: logView, goals: goalsView }[open](s);
  el.replaceChildren(h("div", { class: "row" }, h("h2", { style: "flex:1;margin:0" }, { contracts: "Contracts", market: "Market", log: "Event log", goals: "Goals" }[open]),
    h("button", { class: "secondary small", onclick: () => toggleDrawer(open) }, "Close")), body);
}

// Capacity currently available per region and resource (client-side estimate from the rack stats).
function regionCapacity(s) {
  const cap = {};
  for (const dc of s.datacenters) {
    const c = (cap[dc.region_id] ||= { all: { cpu: 0, storage_tb: 0, gpu: 0 }, red: { cpu: 0, storage_tb: 0, gpu: 0 } });
    for (const r of dc.racks) {
      if (!r.online) continue;
      for (const k of ["cpu", "storage_tb", "gpu"]) {
        c.all[k] += r.stats[k] * dc.perf;
        if (r.stats.redundant) c.red[k] += r.stats[k] * dc.perf;
      }
    }
  }
  for (const c of s.contracts) {
    const rc = cap[c.region_id];
    if (!rc) continue;
    rc.all[c.resource] -= c.units;
    if (c.premium) rc.red[c.resource] -= c.units;
  }
  return cap;
}

const RES_LABEL = { cpu: "CPU units", storage_tb: "TB storage", gpu: "GPU units" };

function contractsView(s) {
  const cap = regionCapacity(s);
  const tabs = h("div", { class: "row", style: "margin:.6rem 0" },
    h("button", { class: tab === "offers" ? "" : "secondary", onclick: () => { tab = "offers"; renderDrawer(true); } }, `Offers (${s.offers.length})`),
    h("button", { class: tab === "active" ? "" : "secondary", onclick: () => { tab = "active"; renderDrawer(true); } }, `Active (${s.contracts.length})`));
  const list = h("div", {});
  if (tab === "offers") {
    const hasDc = new Set(s.datacenters.map((d) => d.region_id));
    const offers = [...s.offers].sort((a, b) => (hasDc.has(b.region_id) - hasDc.has(a.region_id)) || b.revenue_cents_per_tick - a.revenue_cents_per_tick);
    if (!offers.length) list.append(h("p", { class: "muted" }, "No offers right now. Customers appear in regions where you own a datacenter and demand is not already served."));
    for (const o of offers) {
      const region = regionById(o.region_id);
      const mine = hasDc.has(o.region_id);
      const free = cap[o.region_id] ? (o.premium ? cap[o.region_id].red : cap[o.region_id].all)[o.resource] : 0;
      const enough = free >= o.units;
      list.append(h("div", { class: "item", style: mine ? "" : "opacity:.55" },
        h("div", { class: "title" }, h("span", {}, o.name, h("span", { class: "tag" }, o.kind), o.premium ? h("span", { class: "tag premium", title: "Needs racks with 2 PDUs (N+1) and 2 ToR switches" }, "premium") : null),
          h("span", { class: "good" }, money2(o.revenue_cents_per_tick) + "/h")),
        h("div", { class: "sub" }, `${region.name} | needs ${num(o.units)} ${RES_LABEL[o.resource]} | ${Math.round(o.duration_ticks / 24)} days | SLA penalty ${money(o.penalty_cents)}`),
        mine ? h("div", { class: "sub " + (enough ? "good" : "warn") }, `Your free capacity: ${num(free)} ${RES_LABEL[o.resource]}${o.premium ? " (redundant racks)" : ""}`) : h("div", { class: "sub" }, "No datacenter in this region"),
        h("div", { class: "row", style: "margin-top:.3rem" }, h("span", { class: "sub", style: "flex:1" }, `Expires ${dateText(o.offer_expires_tick)}`),
          h("button", { class: "small", disabled: !mine, onclick: async () => { if (await run("accept_contract", { contract_id: o.id }, "cash")) toast(`Contract '${o.name}' signed`, "good"); } }, "Accept"))));
    }
  } else {
    if (!s.contracts.length) list.append(h("p", { class: "muted" }, "No active contracts. Accept an offer first."));
    for (const c of s.contracts) {
      const region = regionById(c.region_id);
      const left = Math.max(0, c.end_tick - s.world.tick);
      const failing = c.sla_fail_streak > 0;
      list.append(h("div", { class: "item", style: failing ? "border-color:var(--bad)" : "" },
        h("div", { class: "title" }, h("span", {}, c.name, h("span", { class: "tag" }, c.kind), c.premium ? h("span", { class: "tag premium" }, "premium") : null),
          h("span", { class: failing ? "bad" : "good" }, failing ? "NOT SERVED" : money2(c.revenue_cents_per_tick) + "/h")),
        h("div", { class: "sub" }, `${region.name} | ${num(c.units)} ${RES_LABEL[c.resource]} | ${Math.ceil(left / 24)} days left`),
        failing ? h("div", { class: "sub bad" }, `Unserved for ${c.sla_fail_streak} h (breach at 48 h). Add capacity or repair racks!`) : null,
        h("div", { class: "row", style: "margin-top:.3rem" }, h("span", { class: "sub", style: "flex:1" }, `Penalty if cancelled: ${money(c.penalty_cents / 2)}`),
          h("button", { class: "danger small", onclick: async () => { if (confirm(`Cancel '${c.name}'? Penalty: ${money(c.penalty_cents / 2)}`)) await run("cancel_contract", { contract_id: c.id }, "unmount"); } }, "Cancel"))));
    }
  }
  return h("div", {}, tabs, list);
}

function marketView(s) {
  const rows = [{ id: s.company.id, name: s.company.name + " (you)", color: s.company.color, worth: s.company.net_worth_cents },
    ...s.rivals.map((r) => ({ id: r.id, name: r.name, color: r.color, worth: r.net_worth_cents }))].sort((a, b) => b.worth - a.worth);
  const box = h("div", {}, h("h3", {}, "Net worth ranking"));
  rows.forEach((r, i) => box.append(h("div", { class: "stat" }, h("span", { style: `color:${r.color}` }, `${i + 1}. ${r.name}`), h("span", {}, money(r.worth)))));
  box.append(h("h3", {}, "Market share per region"));
  const colorOf = new Map(rows.map((r) => [r.id, r.color]));
  for (const region of s.regions) {
    const shares = s.market_share.filter((m) => m.region_id === region.id);
    const bars = h("div", { style: "display:flex;height:10px;border-radius:5px;overflow:hidden;background:#1b2433;margin:.2rem 0 .6rem" },
      shares.map((m) => h("i", { style: `width:${(m.share * 100).toFixed(1)}%;background:${colorOf.get(m.company_id)}`, title: pct(m.share, 1) })));
    const mine = shares.find((m) => m.company_id === s.company.id);
    box.append(h("div", { class: "stat" }, h("span", {}, region.name), h("span", { class: "muted" }, mine ? "you: " + pct(mine.share, 1) : "")), bars);
  }
  return box;
}

const LOG_CLASS = { incident: "bad", breaker_trip: "bad", thermal_shutdown: "bad", contract_breached: "bad", grid_outage: "warn", heatwave: "warn",
  power_spike: "warn", sla_warning: "warn", milestone: "good", contract_completed: "good", incident_absorbed: "good", rack_recovered: "good" };

function logView() {
  if (!log.length) return h("p", { class: "muted" }, "Nothing happened yet.");
  return h("ul", { class: "plain" }, log.map((e) => h("li", {}, h("span", { class: LOG_CLASS[e.kind] || "" }, e.message), h("span", { class: "muted" }, dateText(e.tick)))));
}

function goalsView(s) {
  const box = h("div", {});
  for (const [code, def] of Object.entries(s.milestone_defs)) {
    const done = s.milestones[code] !== undefined;
    box.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", { class: done ? "good" : "" }, (done ? "✓ " : "○ ") + def.name), h("span", { class: "muted" }, "+" + money(def.reward_cents)))));
  }
  return box;
}

bus.on("state", () => renderDrawer());
void bar; void stat;
