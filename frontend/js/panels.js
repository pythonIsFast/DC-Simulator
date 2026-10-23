// Context panel (right side): content depends on the current view (globe / room / rack).
// Kept deliberately small: the important things first, the rest inside collapsible sections.
import { $, h, money, num, pct, kw, bar, stat, keepDetails } from "./util.js";
import { store, bus, regionById, dcById, rackById } from "./store.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";
import { firstFit } from "./rules.js";
import { capacityBlock } from "./capacity.js";

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
    ? JSON.stringify([dcById(v.dcId), s.templates, heatmapOn, s.capacity, s.research.done])
    : JSON.stringify([v.regionId, s.regions, s.datacenters.map((d) => [d.id, d.name, d.region_id, d.racks.length, d.racks.map((r) => r.online)]), s.market_share, s.capacity]);
  if (!force && slice === lastSig) return;
  lastSig = slice;
  rackBuilt = null;
  const scroll = root.scrollTop;
  root.replaceChildren(v.mode === "room" ? roomPanel() : globePanel());
  keepDetails(root, v.mode);
  root.scrollTop = scroll;
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
    box.append(h("h2", {}, s.datacenters.length ? "Your datacenters" : "Click a region"));
    if (s.datacenters.length) {
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
  if (myDcs.length) box.append(h("h3", {}, "Capacity to sell"), capacityBlock(region.id));
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

function tile(label, value, ratio, kind = "") {
  return h("div", { class: "tile" }, h("div", { class: "muted", style: "font-size:.75rem" }, label), h("div", { class: "big " + kind }, value),
    bar(ratio, ratio > 1 ? "badbar" : ratio > 0.85 ? "warnbar" : ""));
}

// One verdict for the whole datacenter: the most important problem first.
function dcHealth(dc, uplinkNeed) {
  const heat = dc.cooling_cap_kw ? dc.heat_kw / dc.cooling_cap_kw : 0;
  const power = dc.power_capacity_kw ? dc.facility_kw / dc.power_capacity_kw : 0;
  const offline = dc.racks.filter((r) => !r.online && r.stats.server_count > 0).length;
  if (heat > 1) return ["Too hot", "bad", "Servers are throttled. Add cooling units under Upgrades."];
  if (power > 1) return ["Power limit", "bad", "Servers are throttled. Buy a power feed under Upgrades."];
  if (uplinkNeed > dc.uplink_ports) return ["No uplinks", "bad", "Some racks are offline. Buy an aggregation switch under Upgrades."];
  if (offline) return [`${offline} rack${offline > 1 ? "s" : ""} offline`, "warn", "Open the offline rack to see why."];
  return ["All good", "good", ""];
}

function roomPanel() {
  const s = store.state;
  const dc = dcById(store.view.dcId);
  if (!dc) return h("div", {});
  const region = regionById(dc.region_id);
  const uplinkNeed = dc.racks.reduce((a, r) => a + (r.stats.tor_count ? r.stats.uplinks_needed : 0), 0);
  const heat = dc.cooling_cap_kw ? dc.heat_kw / dc.cooling_cap_kw : 0;
  const power = dc.power_capacity_kw ? dc.facility_kw / dc.power_capacity_kw : 0;
  const [label, kind, hint] = dcHealth(dc, uplinkNeed);
  const box = h("div", {});
  box.append(
    h("div", { class: "row" }, h("h2", { style: "flex:1" }, dc.name), h("span", { class: "pill " + kind }, label)),
    h("div", { class: "muted", style: "margin:-.2rem 0 .5rem" }, region.name),
    ...(hint ? [h("p", { class: kind === "bad" ? "bad" : "warn", style: "margin:.2rem 0 .6rem" }, hint)] : []),
    h("div", { class: "tiles" },
      tile("Heat", pct(heat), heat), tile("Power", pct(power), power),
      tile("Uplinks", `${uplinkNeed}/${dc.uplink_ports}`, dc.uplink_ports ? uplinkNeed / dc.uplink_ports : 1)),
    h("h3", {}, "Capacity to sell"),
    capacityBlock(dc.region_id),
  );

  const free = dc.max_racks - dc.racks.length;
  box.append(h("div", { class: "row", style: "margin-top:1rem" },
    h("h3", { style: "flex:1;margin:0" }, `Racks ${dc.racks.length}/${dc.max_racks}`),
    h("button", { class: "small " + (heatmapOn ? "" : "secondary"), onclick: () => { heatmapOn = !heatmapOn; bus.emit("heatmap", heatmapOn); renderContext(true); } }, "Heatmap")));
  const grid = h("div", { class: "rackgrid" });
  dc.racks.forEach((r) => grid.append(h("div", { class: "rackcard", onclick: () => nav({ mode: "rack", dcId: dc.id, rackId: r.id }) },
    h("div", { class: "title" }, h("span", {}, r.name), h("i", { class: "dot " + (r.online ? "good" : r.stats.server_count ? "bad" : "idle") })),
    h("div", { class: "sub" }, r.online ? `${r.stats.server_count} servers · ${kw(r.stats.load_w)}` : (r.stats.server_count ? r.offline_text || "offline" : "empty")))));
  if (free > 0) grid.append(h("div", { class: "rackcard add", onclick: () => bus.emit("buy-rack", { template: templateChoice }) }, "+ Install rack"));
  box.append(grid);

  const up = h("details", {}, h("summary", {}, "Upgrades"));
  for (const hw of store.hw.list.filter((x) => x.category.startsWith("dc_"))) {
    const owned = dc.equipment[hw.code] || 0;
    up.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `owned: ${owned}`)),
      h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, isLocked(hw) ? `Research: ${hw.tech_name}` : money(hw.price_cents)),
        h("button", { class: "small", disabled: isLocked(hw), title: isLocked(hw) ? `Requires research: ${hw.tech_name}` : "", onclick: async () => { if (await run("buy_dc_equipment", { datacenter_id: dc.id, code: hw.code, qty: 1 }, "build")) toast(`${hw.name} installed`, "good"); } }, "Buy"))));
  }
  box.append(up);

  const tpl = h("details", {}, h("summary", {}, "Rack templates"));
  tpl.append(h("select", { onchange: (e) => { templateChoice = e.target.value; } },
    h("option", { value: "" }, `New racks are empty (${money(store.hw.rules.rack_shell_cents)})`),
    s.templates.map((t) => h("option", { value: t.id, selected: String(t.id) === templateChoice }, `New racks use: ${t.name}`))));
  s.templates.forEach((t) => tpl.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, t.name),
    h("button", { class: "danger small", onclick: async () => { if (await run("delete_template", { template_id: t.id })) sfx.click(); } }, "Delete")))));
  if (!s.templates.length) tpl.append(h("p", { class: "muted", style: "font-size:.85rem" }, "Save a finished rack as a template in the rack view to reuse it."));
  box.append(tpl);
  return box;
}

// ------------------------------------------------------------------ rack builder

const TABS = [
  ["Servers", [["Compute", ["server_cpu"]], ["Storage", ["server_storage"]], ["GPU / AI", ["server_gpu"]]]],
  ["Network", [["Top-of-rack switches", ["switch_tor"]]]],
  ["Power", [["PDUs", ["pdu"]], ["UPS (backup)", ["ups"]]]],
  ["Extras", [["Cooling and cabling", ["fan_panel", "patch_panel", "cable_mgmt", "blank"]]]],
];
let activeTab = "Servers";

function shortSpec(hw) {
  const a = hw.attrs;
  const parts = [`${hw.u_height} U`];
  if (hw.power_w) parts.push(`${hw.power_w} W`);
  if (a.cpu) parts.push(`${a.cpu} CPU`);
  if (a.storage_tb) parts.push(a.storage_tb >= 1000 ? `${a.storage_tb / 1000} PB` : `${a.storage_tb} TB`);
  if (a.gpu) parts.push(`${a.gpu} GPU`);
  if (hw.ports) parts.push(`${hw.ports} ports`);
  if (a.max_w) parts.push(`${a.max_w / 1000} kW max`);
  if (a.ups_w) parts.push(`${a.ups_w / 1000} kW backup`);
  if (a.heat_reduction) parts.push(`-${Math.round(a.heat_reduction * 100)}% heat`);
  return parts.join(" · ");
}

const isLocked = (hw) => !!hw.tech && !store.state.research.done.includes(hw.tech);

function hwCard(hw) {
  if (isLocked(hw)) {
    const lockedEl = h("div", { class: "item locked", title: `Requires research: ${hw.tech_name}` },
      h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, "\uD83D\uDD12 Locked")),
      h("div", { class: "sub" }, `Research: ${hw.tech_name}`));
    lockedEl.addEventListener("click", () => { toast(`Requires research: ${hw.tech_name}`, "warn"); sfx.error(); });
    return lockedEl;
  }
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

function buildPalette(tabsBox, listBox) {
  tabsBox.replaceChildren(...TABS.map(([name]) => h("button", {
    class: "small " + (name === activeTab ? "" : "secondary"),
    onclick: () => { activeTab = name; sfx.click(); buildPalette(tabsBox, listBox); },
  }, name)));
  const groups = TABS.find(([name]) => name === activeTab)[1];
  listBox.replaceChildren(...groups.flatMap(([title, cats]) => [
    h("h3", {}, title),
    ...store.hw.list.filter((x) => cats.includes(x.category)).map(hwCard),
  ]));
}

function buildRackPanel(root, found) {
  const statsBox = h("div", {});
  const selBox = h("div", {});
  const itemsBox = h("div", {});
  const detailsBox = h("div", {});
  const tabsBox = h("div", { class: "row", style: "margin:.4rem 0" });
  const listBox = h("div", {});
  buildPalette(tabsBox, listBox);
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
    statsBox, selBox, itemsBox,
    h("h3", {}, "Add equipment"),
    h("p", { class: "muted", style: "font-size:.82rem;margin:0" }, "Drag into the rack, or click to mount."),
    tabsBox, listBox, detailsBox, actions,
  );
  rackBuilt = { rackId: found.rack.id, statsBox, selBox, itemsBox, itemsSig: "", detailsBox, tabsBox, listBox, researchSig: store.state.research.done.join() };
  updateSelection();
}

function chip(text, ok) { return h("span", { class: "tag " + (ok ? "ok" : "") }, text); }
const check = (ok, text) => h("div", { class: "check " + (ok ? "ok" : "no") }, (ok ? "✓" : "✗") + " " + text);

function updateRackStats(found) {
  const { rack, dc } = found;
  const st = rack.stats;
  const rsig = store.state.research.done.join();
  if (rackBuilt.researchSig !== rsig) { rackBuilt.researchSig = rsig; buildPalette(rackBuilt.tabsBox, rackBuilt.listBox); }
  const loadRatio = st.limit_w ? st.load_w / st.limit_w : 0;
  const empty = st.used_u === 0;
  const [pill, kind] = rack.online ? (empty ? ["Empty", ""] : ["Online", "good"]) : [rack.offline_text || "Offline", "bad"];
  const top = [
    h("div", { class: "row", style: "margin-bottom:.5rem" }, h("span", { class: "pill " + kind }, pill),
      st.redundant ? h("span", { class: "tag ok" }, "redundant") : null),
    h("div", { class: "tiles" },
      tile("Space", `${st.used_u}/${store.hw.rules.rack_u} U`, st.used_u / store.hw.rules.rack_u),
      tile("Power", `${(st.load_w / 1000).toFixed(1)}/${(st.limit_w / 1000).toFixed(1)} kW`, loadRatio),
      tile("Ports", `${st.ports_used}/${st.ports_total}`, st.ports_total ? st.ports_used / st.ports_total : 0)),
  ];
  if (!rack.online && rack.status !== "ok") {
    top.push(h("button", { class: "small wide", style: "margin-top:.5rem", onclick: async () => {
      if (await run("repair_rack", { rack_id: rack.id }, "build")) toast("Rack repaired", "good");
    } }, rack.status === "tripped" ? "Reset breaker (free)" : `Repair now (${money(store.hw.rules.repair_cost_cents)})`));
  }
  top.push(h("div", { style: "margin-top:.6rem" },
    check(st.pdu_count > 0, st.pdu_count ? `Power: ${st.pdu_count} PDU` : "Power: add a PDU"),
    check(st.tor_count > 0, st.tor_count ? `Network: ${st.tor_count} ToR switch` : "Network: add a ToR switch"),
    check(st.server_count > 0 && st.connected_ids.length === st.server_count, `Servers connected: ${st.connected_ids.length}/${st.server_count}`)));
  rackBuilt.statsBox.replaceChildren(...top);
  updateInstalledList(rack);

  const det = h("details", {}, h("summary", {}, `Rack details${st.warnings.length ? ` (${st.warnings.length} notes)` : ""}`),
    stat("Heat output", kw(st.heat_w)),
    h("div", { style: "margin:.3rem 0" }, chip("Power N+1", st.power_redundant), chip("2x ToR", st.net_redundant), chip("UPS", st.has_ups)),
    stat("Sellable CPU", num(st.cpu)), stat("Sellable storage", num(st.storage_tb) + " TB"), stat("Sellable GPU", num(st.gpu)));
  if (st.warnings.length) det.append(h("ul", { class: "warnings" }, st.warnings.map((w) => h("li", { class: /Overload|No PDU|No ToR/.test(w) ? "bad" : "" }, w))));
  if (dc.perf < 1) det.append(h("p", { class: "warn" }, `Datacenter throttled to ${pct(dc.perf)}.`));
  rackBuilt.detailsBox.replaceChildren(det);
  keepDetails(rackBuilt.detailsBox, "rack");
}

// Touch-friendly way to take parts out again: every mounted item gets its own Remove button.
function updateInstalledList(rack) {
  const sig = JSON.stringify(rack.items.map((i) => [i.id, i.code, i.u_start]));
  if (rackBuilt.itemsSig === sig) return;
  rackBuilt.itemsSig = sig;
  const rows = [...rack.items].sort((a, b) => b.u_start - a.u_start).map((it) => {
    const hw = store.hw.byCode[it.code];
    return h("div", { class: "item" },
      h("div", { class: "title" }, h("span", {}, hw ? hw.name : it.code), h("span", { class: "muted" }, `U${it.u_start}`)),
      h("div", { class: "row" },
        h("span", { class: "sub", style: "flex:1" }, hw ? `Sell for ${money(hw.price_cents * store.hw.rules.sell_back_ratio)}` : ""),
        h("button", { class: "danger small", onclick: () => bus.emit("remove", it.id) }, "Remove")));
  });
  rackBuilt.itemsBox.replaceChildren(rows.length
    ? h("details", { open: "" }, h("summary", {}, `Installed equipment (${rows.length})`), ...rows)
    : h("p", { class: "muted", style: "font-size:.82rem" }, "Nothing installed yet."));
}

function updateSelection() {
  if (!rackBuilt) return;
  const box = rackBuilt.selBox;
  if (!selectedItem) { box.replaceChildren(); return; }
  const hw = store.hw.byCode[selectedItem.code];
  const id = selectedItem.id;
  box.replaceChildren(h("div", { class: "item", style: "border-color:var(--accent);margin-top:.6rem" },
    h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `U${selectedItem.u_start}`)),
    h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, `Sell for ${money(hw.price_cents * store.hw.rules.sell_back_ratio)}`),
      h("button", { class: "danger small", onclick: () => bus.emit("remove", id) }, "Remove"))));
}
