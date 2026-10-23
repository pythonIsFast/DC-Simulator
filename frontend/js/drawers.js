// Left drawer: contracts, market, event log and milestones.
import { $, h, money, money2, num, pct, bar, stat, dateText, keepDetails } from "./util.js";
import { store, bus, regionById } from "./store.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";
import { capacityBlock, RES_LABEL } from "./capacity.js";
import { teamView } from "./team.js";
import { researchView } from "./research.js";

let open = null;       // name of the open drawer or null
let tab = "offers";
let lastSig = "";
const log = [];        // newest first

export function addLog(events) {
  for (const e of events) log.unshift(e);
  log.length = Math.min(log.length, 120);
  if (open === "market") renderDrawer(true);
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
  const sig = open + tab + JSON.stringify(open === "contracts" ? [s.offers, s.contracts, s.capacity]
    : open === "team" ? s.team : open === "research" ? s.research : open === "market" ? [s.market_share, s.rivals, s.company.net_worth_cents, log.length] : open === "goals" ? s.milestones : log.length);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  el.hidden = false;
  const scroll = el.scrollTop;
  const body = { contracts: contractsView, market: marketView, log: logView, goals: goalsView, team: teamView, research: researchView }[open](s);
  el.replaceChildren(h("div", { class: "row" }, h("h2", { style: "flex:1;margin:0" }, { contracts: "Contracts", market: "Overview", log: "Event log", goals: "Goals", team: "Team", research: "Research" }[open]),
    h("button", { class: "secondary small", onclick: () => toggleDrawer(open) }, "Close")), body);
  keepDetails(el, open);
  el.scrollTop = scroll;
}

function contractsView(s) {
  const cap = s.capacity;
  const tabs = h("div", { class: "row", style: "margin:.6rem 0" },
    h("button", { class: tab === "offers" ? "" : "secondary", onclick: () => { tab = "offers"; renderDrawer(true); } }, `Offers (${s.offers.length})`),
    h("button", { class: tab === "active" ? "" : "secondary", onclick: () => { tab = "active"; renderDrawer(true); } }, `Active (${s.contracts.length})`));
  const list = h("div", {});
  if (tab === "offers") {
    const hasDc = new Set(s.datacenters.map((d) => d.region_id));
    const offers = [...s.offers].sort((a, b) => (hasDc.has(b.region_id) - hasDc.has(a.region_id)) || b.revenue_cents_per_tick - a.revenue_cents_per_tick);
    if (!offers.length) list.append(h("p", { class: "muted" }, "No offers right now. New customers arrive every day."));
    for (const o of offers) {
      const region = regionById(o.region_id);
      const mine = hasDc.has(o.region_id);
      const rc = cap[o.region_id];
      const free = rc ? (o.premium ? rc[o.resource].red_free : rc[o.resource].free) : 0;
      const enough = free >= o.units;
      const status = !mine ? h("span", { class: "muted" }, `Needs a datacenter in ${region.name}`)
        : enough ? h("span", { class: "good" }, "✓ You have the capacity")
          : h("span", { class: "warn" }, o.premium ? "Needs redundant racks (2 PDU + 2 ToR)" : "Not enough capacity yet");
      list.append(h("div", { class: "item", style: mine ? "" : "opacity:.6" },
        h("div", { class: "title" }, h("span", {}, o.name, o.premium ? h("span", { class: "tag premium" }, "premium") : null),
          h("span", { class: "good" }, money2(o.revenue_cents_per_tick) + "/h")),
        h("div", { class: "sub" }, `${num(o.units)} ${RES_LABEL[o.resource]} · ${Math.round(o.duration_ticks / 24)} days`),
        h("div", { class: "row", style: "margin-top:.3rem" }, h("span", { style: "flex:1;font-size:.88rem" }, status),
          h("button", { class: "small", disabled: !mine, onclick: async () => { if (await run("accept_contract", { contract_id: o.id }, "cash")) toast(`Signed '${o.name}'. It is served from your racks in ${region.name}.`, "good"); } }, "Accept"))));
    }
  } else {
    if (!s.contracts.length) list.append(h("p", { class: "muted" }, "No active contracts. Accept an offer first."));
    for (const c of s.contracts) {
      const region = regionById(c.region_id);
      const left = Math.max(0, c.end_tick - s.world.tick);
      const failing = c.sla_fail_streak > 0;
      list.append(h("div", { class: "item", style: failing ? "border-color:var(--bad)" : "" },
        h("div", { class: "title" }, h("span", {}, c.name, c.premium ? h("span", { class: "tag premium" }, "premium") : null),
          h("span", { class: failing ? "bad" : "good" }, failing ? "NOT SERVED" : money2(c.revenue_cents_per_tick) + "/h")),
        h("div", { class: "sub" }, `${region.name} · ${num(c.units)} ${RES_LABEL[c.resource]} · ${Math.ceil(left / 24)} days left`),
        failing ? h("div", { class: "bad", style: "font-size:.88rem" }, `Unserved for ${c.sla_fail_streak} h. Breach at 48 h: add servers or repair racks!`) : null,
        h("div", { class: "row", style: "margin-top:.3rem;justify-content:flex-end" },
          h("button", { class: "danger small", onclick: async () => { if (confirm(`Cancel '${c.name}'? Penalty: ${money(c.penalty_cents / 2)}`)) await run("cancel_contract", { contract_id: c.id }, "unmount"); } }, "Cancel"))));
    }
  }
  const regionsWithCap = Object.keys(cap);
  const info = h("details", { open: tab === "offers" },
    h("summary", {}, "Your free capacity"),
    h("p", { class: "muted", style: "font-size:.85rem;margin:.3rem 0" }, "A contract is served from the pooled capacity of all your online racks in its region, not from one rack. Premium contracts only count racks with 2 PDUs and 2 ToR switches."),
    regionsWithCap.length ? regionsWithCap.map((rid) => h("div", {}, h("h3", {}, regionById(Number(rid)).name), capacityBlock(rid))) : h("p", { class: "muted" }, "Build a datacenter and mount servers first."));
  return h("div", {}, info, tabs, list);
}

const tileBox = (label, value, kind = "") => h("div", { class: "tile" }, h("div", { class: "muted", style: "font-size:.75rem" }, label), h("div", { class: "big " + kind }, value));

function marketView(s) {
  const rows = [{ id: s.company.id, name: s.company.name + " (you)", color: s.company.color, worth: s.company.net_worth_cents, me: true },
    // Subsidiaries are part of our own net worth, so they do not count as competitors.
    ...s.rivals.filter((r) => r.owner_id !== s.company.id).map((r) => ({ id: r.id, name: r.name, color: r.color, worth: r.net_worth_cents }))].sort((a, b) => b.worth - a.worth);
  const rank = rows.findIndex((r) => r.me) + 1;
  const b = s.company.breakdown || {};
  const net = s.company.revenue_cents_per_tick - s.company.expense_cents_per_tick;
  const box = h("div", {});

  box.append(h("div", { class: "tiles" },
    tileBox("Cash", money(s.company.cash_cents), s.company.cash_cents < 0 ? "bad" : ""),
    tileBox("Net worth", money(s.company.net_worth_cents)),
    tileBox("Rank", `#${rank} of ${rows.length}`)));

  box.append(h("h3", {}, "Money per hour"),
    stat("Customers pay", "+" + money2(b.revenue || 0), "good"),
    stat("Electricity", "-" + money2(-(b.power || 0))),
    stat("Rent", "-" + money2(-(b.rent || 0))),
    stat("Salaries", "-" + money2(-(b.salary || 0))),
    h("div", { class: "stat", style: "border-top:1px solid var(--line);margin-top:.2rem;padding-top:.3rem;font-weight:600" },
      h("span", {}, "Profit"), h("span", { class: net >= 0 ? "good" : "bad" }, (net >= 0 ? "+" : "-") + money2(Math.abs(net)))));

  const next = Object.entries(s.milestone_defs).find(([code]) => s.milestones[code] === undefined);
  box.append(h("h3", {}, "Next goal"));
  box.append(next ? h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, next[1].name), h("span", { class: "good" }, "+" + money(next[1].reward_cents))))
    : h("p", { class: "good" }, "All goals reached!"));

  box.append(h("h3", {}, "Ranking by net worth"));
  rows.forEach((r, i) => box.append(h("div", { class: "stat" }, h("span", { style: `color:${r.me ? "var(--accent)" : r.color};font-weight:${r.me ? 700 : 400}` }, `${i + 1}. ${r.name}`), h("span", {}, money(r.worth)))));

  box.append(companiesView(s));

  // Market share: only regions where someone has customers; the rest stays collapsed.
  const ownedIds = new Set(s.rivals.filter((r) => r.owner_id === s.company.id).map((r) => r.id));
  const colorOf = new Map(rows.map((r) => [r.id, r.color]));
  ownedIds.forEach((id) => colorOf.set(id, s.company.color));  // owned companies count as ours
  const shareBox = h("details", {}, h("summary", {}, "Market share per region"));
  for (const region of s.regions) {
    const shares = s.market_share.filter((m) => m.region_id === region.id);
    const mineShare = shares.filter((m) => m.company_id === s.company.id || ownedIds.has(m.company_id)).reduce((a, m) => a + m.share, 0);
    const mine = mineShare > 0 ? { share: mineShare } : null;
    const bars = h("div", { style: "display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--panel2);margin:.2rem 0 .6rem" },
      shares.map((m) => h("i", { style: `width:${(m.share * 100).toFixed(1)}%;background:${colorOf.get(m.company_id)}`, title: pct(m.share, 1) })));
    shareBox.append(h("div", { class: "stat" }, h("span", {}, region.name), h("span", { class: "muted" }, mine ? "you: " + pct(mine.share, 1) : "")), bars);
  }
  box.append(shareBox);

  const goals = h("details", {}, h("summary", {}, "All goals"), goalsView(s));
  box.append(goals, h("details", {}, h("summary", {}, "Recent events"), logView()));
  return box;
}

// Rival companies: buy them out; owned ones keep running as subsidiaries and pay dividends.
function companiesView(s) {
  const box = h("div", {}, h("h3", {}, "Companies"),
    h("p", { class: "muted", style: "font-size:.82rem;margin:0 0 .3rem" }, "Buy a rival completely. Its treasury and customers become yours: you get its daily profit (a quarter is reinvested in its growth)."));
  const mine = s.rivals.filter((r) => r.owner_id === s.company.id);
  const free = s.rivals.filter((r) => r.is_ai && r.owner_id == null).sort((a, b) => a.net_worth_cents - b.net_worth_cents);
  mine.forEach((r) => box.append(h("div", { class: "item" },
    h("div", { class: "title" }, h("span", { style: `color:${r.color}` }, r.name), h("span", { class: "tag ok" }, "Owned")),
    h("div", { class: "sub" }, `Worth about ${money(r.net_worth_cents)}`))));
  free.forEach((r) => {
    const affordable = s.company.cash_cents >= r.price_cents;
    box.append(h("div", { class: "item" },
      h("div", { class: "title" }, h("span", { style: `color:${r.color}` }, r.name), h("span", { class: "muted" }, money(r.net_worth_cents))),
      h("div", { class: "row" },
        h("span", { class: "sub", style: "flex:1" }, `Price ${money(r.price_cents)}`),
        h("button", { class: "small", title: affordable ? "" : "Not enough cash yet", onclick: async () => {
          if (!confirm(`Buy ${r.name} for ${money(r.price_cents)}?`)) return;
          if (await run("acquire_rival", { rival_id: r.id }, "cash")) toast(`You bought ${r.name}.`, "good");
        } }, "Buy"))));
  });
  if (!mine.length && !free.length) box.append(h("p", { class: "muted" }, "No companies to buy right now."));
  return box;
}

const LOG_CLASS = { incident: "bad", breaker_trip: "bad", thermal_shutdown: "bad", contract_breached: "bad", grid_outage: "warn", heatwave: "warn",
  power_spike: "warn", sla_warning: "warn", milestone: "good", rival_founded: "warn", rival_acquired: "good", contract_completed: "good", incident_absorbed: "good", rack_recovered: "good" };

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
