// Context panel (right side): content depends on the current view (globe / room / rack).
// Kept deliberately small: the important things first, the rest inside collapsible sections.
import { $, h, money, num, pct, kw, bar, stat } from "./util.js";
import { store, bus, regionById, dcById, rackById } from "./store.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";
import { firstFit } from "./rules.js";

const nav = (patch) => bus.emit("nav", patch);
let lastSig = "";
let selectedItem = null;
let heatmapOn = false;
let templateChoice = "";
let rackBuilt = null;    // {rackId, statsBox, selBox, detailsBox}

bus.on("select", (item) => { selectedItem = item; if (rackBuilt) updateSelection(); });
bus.on("view", () => { rackBuilt = null; lastSig = ""; selectedItem = null; renderContext(true); });

export const currentTemplate = () => templateChoice;

export function renderContext(force = false) {
  const s = store.state;
  if (!s) return;
  const v = store.view;
  const root = $("context");
  if (v.mode === "rack") {
    const found = rackById(v.rackId);
    if (!found) { nav({ mode: "room", dcId: v.dcId }); return; }
    if (!rackBuilt || rackBuilt.rackId !== v.rackId) buildRackPanel(root, found);
    updateRackStats(found);
    return;
  }
  const slice = v.mode === "room"
    ? JSON.stringify([dcById(v.dcId), s.templates, heatmapOn])
    : JSON.stringify([v.regionId, s.regions, s.datacenters.map((d) => [d.id, d.name, d.region_id, d.racks.length, d.racks.map((r) => r.online)]), s.market_share]);
  if (!force && slice === lastSig) return;
  lastSig = slice;
  rackBuilt = null;
  root.replaceChildren(v.mode === "room" ? roomPanel() : globePanel());
}

// ------------------------------------------------------------------ globe

function dcCard(dc) {
  const online = dc.racks.filter((r) => r.online).length;
  return h("div", { class: "item clickable", onclick: () => nav({ mode: "room", dcId: dc.id }) },
    h("div", { class: "title" }, h("span", {}, dc.name), h("span", { class: "muted" }, "Open ›")),
    h("div", { class: "sub" }, `${online}/${dc.racks.length} racks online`));
}

function globePanel() {
  const s = store.state;
  const region = store.view.regionId ? regionById(store.view.regionId) : null;
  const box = h("div", {});
  if (!region) {
    box.append(h("h2", {}, "World map"), h("p", { class: "muted" }, "Click a region to see it. Drag to rotate, scroll to zoom."));
    if (s.datacenters.length) {
      box.append(h("h3", {}, "Your datacenters"));
      s.datacenters.forEach((dc) => box.append(dcCard(dc)));
    }
    return box;
  }
  const myDcs = s.datacenters.filter((d) => d.region_id === region.id);
  const freePct = region.demand_units ? region.free_units / region.demand_units : 0;
  box.append(
    h("div", { class: "row" }, h("h2", { style: "flex:1" }, region.name), h("button", { class: "secondary small", onclick: () => nav({ mode: "globe", regionId: null }) }, "Close")),
    stat("Unserved customers", pct(freePct), freePct > 0.3 ? "good" : "warn"),
    stat("Electricity", region.power_price_cents_kwh.toFixed(0) + " c/kWh"),
    stat("Climate", region.avg_temp_c.toFixed(0) + " °C"),
  );
  if (region.events.length) box.append(h("p", { class: "warn" }, "Active: " + region.events.map((e) => e.replace("_", " ")).join(", ")));
  const names = new Map([[s.company.id, s.company.name + " (you)"], ...s.rivals.map((r) => [r.id, r.name])]);
  const shares = s.market_share.filter((m) => m.region_id === region.id).sort((a, b) => b.share - a.share).slice(0, 4);
  if (shares.length) {
    box.append(h("h3", {}, "Market share"));
    shares.forEach((m) => box.append(stat(names.get(m.company_id) || "?", pct(m.share, 1))));
  }
  box.append(h("h3", {}, "Your datacenters here"));
  if (!myDcs.length) box.append(h("p", { class: "muted" }, "None yet."));
  myDcs.forEach((dc) => box.append(dcCard(dc)));
  if (myDcs.length < 3) {
    box.append(h("button", { class: "wide", style: "margin-top:.6rem", onclick: async () => {
      const r = await run("build_datacenter", { region_id: region.id }, "build");
      if (r) nav({ mode: "room", dcId: r.datacenter_id });
    } }, `Build datacenter – ${money(region.build_cost_cents)}`));
  }
  return box;
}

// ------------------------------------------------------------------ room

function meter(label, value, max, unit) {
  const ratio = max ? value / max : 0;
  const kind = ratio > 1 ? "badbar" : ratio > 0.85 ? "warnbar" : "";
  return h("div", {}, stat(label, `${value.toFixed(1)} / ${max.toFixed(0)} ${unit}`, ratio > 1 ? "bad" : ""), bar(ratio, kind));
}

function roomPanel() {
  const s = store.state;
  const dc = dcById(store.view.dcId);
  if (!dc) return h("div", {});
  const box = h("div", {});
  const uplinkNeed = dc.racks.reduce((a, r) => a + (r.stats.tor_count ? r.stats.uplinks_needed : 0), 0);
  box.append(
    h("h2", {}, dc.name),
    meter("Cooling (heat)", dc.heat_kw, dc.cooling_cap_kw, "kW"),
    meter("Electricity", dc.facility_kw, dc.power_capacity_kw, "kW"),
  );
  if (dc.perf < 1) box.append(h("p", { class: "warn" }, `Throttled to ${pct(dc.perf)}: add cooling or power (Upgrades).`));
  if (uplinkNeed > dc.uplink_ports) box.append(h("p", { class: "bad" }, "Not enough uplink ports: buy an aggregation switch (Upgrades)."));

  box.append(h("div", { class: "row", style: "margin:.6rem 0" },
    h("button", { style: "flex:1", onclick: () => bus.emit("buy-rack", { template: templateChoice }) }, "+ Install rack"),
    h("button", { class: heatmapOn ? "" : "secondary", onclick: () => { heatmapOn = !heatmapOn; bus.emit("heatmap", heatmapOn); renderContext(true); } }, "Heatmap")));
  box.append(h("p", { class: "muted", style: "font-size:.8rem" }, "Or click an empty square on the floor. Click a rack to edit it."));

  box.append(h("h3", {}, `Racks (${dc.racks.length}/${dc.max_racks})`));
  if (!dc.racks.length) box.append(h("p", { class: "muted" }, "No racks yet."));
  dc.racks.forEach((r) => box.append(h("div", { class: "item clickable", onclick: () => nav({ mode: "rack", dcId: dc.id, rackId: r.id }) },
    h("div", { class: "title" }, h("span", {}, r.name), h("span", { class: r.online ? "good" : "bad" }, r.online ? "online" : (r.offline_text || "offline"))),
    h("div", { class: "sub" }, `${r.stats.server_count} servers | ${kw(r.stats.load_w)}`))));

  const up = h("details", {}, h("summary", {}, "Upgrades"));
  for (const hw of store.hw.list.filter((x) => x.category.startsWith("dc_"))) {
    const owned = dc.equipment[hw.code] || 0;
    up.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `owned: ${owned}`)),
      h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, money(hw.price_cents)),
        h("button", { class: "small", onclick: async () => { if (await run("buy_dc_equipment", { datacenter_id: dc.id, code: hw.code, qty: 1 }, "build")) toast(`${hw.name} installed`, "good"); } }, "Buy"))));
  }
  up.append(h("p", { class: "muted", style: "font-size:.8rem" }, `Uplink ports used: ${uplinkNeed} / ${dc.uplink_ports}`));
  box.append(up);

  const tpl = h("details", {}, h("summary", {}, "Rack templates"));
  tpl.append(h("select", { onchange: (e) => { templateChoice = e.target.value; } },
    h("option", { value: "" }, `New racks are empty (${money(store.hw.rules.rack_shell_cents)})`),
    s.templates.map((t) => h("option", { value: t.id, selected: String(t.id) === templateChoice }, `New racks use: ${t.name}`))));
  s.templates.forEach((t) => tpl.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, t.name),
    h("button", { class: "danger small", onclick: async () => { if (await run("delete_template", { template_id: t.id })) sfx.click(); } }, "Delete")))));
  if (!s.templates.length) tpl.append(h("p", { class: "muted", style: "font-size:.8rem" }, "Save a finished rack as a template in the rack view to reuse it."));
  box.append(tpl);
  return box;
}

// ------------------------------------------------------------------ rack builder

const GROUPS = [
  ["Servers", ["server_cpu", "server_storage", "server_gpu"]], ["Network", ["switch_tor"]],
  ["Power", ["pdu", "ups"]], ["Extras", ["patch_panel", "cable_mgmt", "blank"]],
];

function shortSpec(hw) {
  const a = hw.attrs;
  const parts = [`${hw.u_height} U`];
  if (hw.power_w) parts.push(`${hw.power_w} W`);
  if (a.cpu) parts.push(`${a.cpu} CPU`);
  if (a.storage_tb) parts.push(`${a.storage_tb} TB`);
  if (a.gpu) parts.push(`${a.gpu} GPU`);
  if (hw.ports) parts.push(`${hw.ports} ports`);
  if (a.max_w) parts.push(`${a.max_w / 1000} kW`);
  return parts.join(" · ");
}

function hwCard(hw) {
  const el = h("div", { class: "item draggable", draggable: "true", title: "Drag into the rack, or click to mount at the first free spot" },
    h("div", { class: "title" }, h("span", {}, hw.name), h("span", {}, money(hw.price_cents))),
    h("div", { class: "sub" }, shortSpec(hw)));
  el.addEventListener("dragstart", (ev) => {
    ev.dataTransfer.setData("text/plain", hw.code);
    ev.dataTransfer.effectAllowed = "copy";
    bus.emit("palette", hw.code);
  });
  el.addEventListener("dragend", () => bus.emit("palette", null));
  el.addEventListener("click", () => {
    const found = rackById(store.view.rackId);
    const u = found ? firstFit(found.rack.items, hw) : null;
    if (u === null) { toast("No free space for " + hw.name, "warn"); sfx.error(); return; }
    bus.emit("install", { code: hw.code, u });
  });
  return el;
}

function buildRackPanel(root, found) {
  const statsBox = h("div", {});
  const selBox = h("div", {});
  const detailsBox = h("div", {});
  const palette = h("div", {});
  for (const [title, cats] of GROUPS) {
    palette.append(h("h3", {}, title));
    store.hw.list.filter((x) => cats.includes(x.category)).forEach((hw) => palette.append(hwCard(hw)));
  }
  const dcId = found.dc.id;
  const actions = h("details", {}, h("summary", {}, "Rack actions"),
    h("div", { class: "row", style: "margin-top:.4rem" },
      h("button", { class: "secondary small", onclick: async () => {
        const name = prompt("Template name:", found.rack.name + " template");
        if (name && await run("save_template", { rack_id: store.view.rackId, name }, "click")) toast("Template saved", "good");
      } }, "Save template"),
      h("button", { class: "secondary small", onclick: async () => {
        const r = await run("buy_rack", { datacenter_id: dcId, clone_rack_id: store.view.rackId }, "build");
        if (r) nav({ mode: "rack", dcId, rackId: r.rack_id });
      } }, "Clone rack"),
      h("button", { class: "danger small", onclick: async () => {
        if (!confirm("Sell this rack and everything in it? You get " + Math.round(store.hw.rules.sell_back_ratio * 100) + " % back.")) return;
        if (await run("sell_rack", { rack_id: store.view.rackId }, "unmount")) nav({ mode: "room", dcId });
      } }, "Sell rack")));
  root.replaceChildren(
    h("div", { class: "row" }, h("h2", { style: "flex:1" }, found.rack.name), h("button", { class: "secondary small", onclick: () => nav({ mode: "room", dcId }) }, "Back")),
    statsBox, selBox,
    h("details", { open: true }, h("summary", {}, "Add equipment"),
      h("p", { class: "muted", style: "font-size:.8rem;margin:.3rem 0" }, "Drag into the rack, or click to mount."), palette),
    detailsBox, actions,
  );
  rackBuilt = { rackId: found.rack.id, statsBox, selBox, detailsBox };
  updateSelection();
}

function chip(text, ok) { return h("span", { class: "tag " + (ok ? "ok" : "") }, text); }
const check = (ok, text) => h("div", { class: "check " + (ok ? "ok" : "no") }, (ok ? "✓" : "✗") + " " + text);

function updateRackStats(found) {
  const { rack, dc } = found;
  const st = rack.stats;
  const loadRatio = st.limit_w ? st.load_w / st.limit_w : 0;
  const top = [];
  if (!rack.online) {
    top.push(h("div", { class: "item", style: "border-color:var(--bad)" },
      h("div", { class: "title bad" }, "Offline: " + (rack.offline_text || "no power")),
      rack.status !== "ok" ? h("button", { class: "small", style: "margin-top:.3rem", onclick: async () => {
        if (await run("repair_rack", { rack_id: rack.id }, "build")) toast("Rack repaired", "good");
      } }, rack.status === "tripped" ? "Reset breaker (free)" : `Repair now (${money(store.hw.rules.repair_cost_cents)})`) : null));
  }
  top.push(
    check(st.pdu_count > 0, st.pdu_count ? `Power: ${st.pdu_count} PDU` : "Power: add a PDU"),
    check(st.tor_count > 0, st.tor_count ? `Network: ${st.tor_count} ToR switch` : "Network: add a ToR switch"),
    check(st.server_count > 0 && st.connected_ids.length === st.server_count, `Servers connected: ${st.connected_ids.length}/${st.server_count}`),
    h("div", { style: "margin-top:.5rem" }, stat("Power", `${kw(st.load_w)} / ${kw(st.limit_w)}`, st.overload ? "bad" : ""),
      bar(loadRatio, st.overload ? "badbar" : loadRatio > 0.85 ? "warnbar" : "")),
  );
  rackBuilt.statsBox.replaceChildren(...top);

  const det = h("details", {}, h("summary", {}, "Rack details"),
    stat("Space", `${st.used_u} / ${store.hw.rules.rack_u} U`),
    stat("Heat", kw(st.heat_w)),
    stat("Switch ports", `${st.ports_used} / ${st.ports_total}`),
    h("div", { style: "margin:.3rem 0" }, chip("Power N+1", st.power_redundant), chip("2x ToR", st.net_redundant), chip("UPS", st.has_ups)),
    stat("Sellable CPU", num(st.cpu)), stat("Sellable storage", num(st.storage_tb) + " TB"), stat("Sellable GPU", num(st.gpu)));
  if (st.warnings.length) det.append(h("ul", { class: "warnings" }, st.warnings.map((w) => h("li", { class: /Overload|No PDU|No ToR/.test(w) ? "bad" : "" }, w))));
  if (dc.perf < 1) det.append(h("p", { class: "warn" }, `Datacenter throttled to ${pct(dc.perf)}.`));
  if (rackBuilt.detailsBox.firstChild?.open) det.open = true;
  rackBuilt.detailsBox.replaceChildren(det);
}

function updateSelection() {
  if (!rackBuilt) return;
  const box = rackBuilt.selBox;
  if (!selectedItem) { box.replaceChildren(); return; }
  const hw = store.hw.byCode[selectedItem.code];
  const id = selectedItem.id;
  box.replaceChildren(h("div", { class: "item", style: "border-color:var(--accent)" },
    h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `U${selectedItem.u_start}`)),
    h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, `Sell for ${money(hw.price_cents * store.hw.rules.sell_back_ratio)}`),
      h("button", { class: "danger small", onclick: () => bus.emit("remove", id) }, "Remove"))));
}
