// Context panel (right side): content depends on the current view (globe / room / rack).
import { $, h, money, money2, num, pct, kw, bar, stat } from "./util.js";
import { store, bus, regionById, dcById, rackById } from "./store.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";
import { canPlaceItems, firstFit } from "./rules.js";

const nav = (patch) => bus.emit("nav", patch);
let lastSig = "";
let selectedItem = null;
let heatmapOn = false;
let templateChoice = "";
let rackBuilt = null;    // {rackId, statsBox, selBox}

bus.on("select", (item) => { selectedItem = item; if (rackBuilt) updateSelection(); });
bus.on("view", () => { rackBuilt = null; lastSig = ""; selectedItem = null; renderContext(true); });

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
    ? JSON.stringify([dcById(v.dcId), s.templates, heatmapOn, s.company.cash_cents > 0])
    : JSON.stringify([v.regionId, s.regions, s.datacenters.map((d) => [d.id, d.name, d.region_id, d.racks.length, d.racks.map((r) => r.online)]), s.market_share, s.contracts.length, s.company.cash_cents >= 0]);
  if (!force && slice === lastSig) return;
  lastSig = slice;
  rackBuilt = null;
  root.replaceChildren(v.mode === "room" ? roomPanel() : globePanel());
}

// ------------------------------------------------------------------ globe

function guide(s) {
  const dcs = s.datacenters;
  const racks = dcs.flatMap((d) => d.racks);
  const steps = [
    ["Click a region and build a datacenter", dcs.length > 0],
    ["Open it and install a rack in an empty slot", racks.length > 0],
    ["Mount PDU, ToR switch and servers into the rack", racks.some((r) => r.online && r.stats.server_count > 0)],
    ["Accept a customer contract (Contracts)", s.contracts.length > 0],
    ["Watch the cash grow and expand", s.company.cash_cents > 400_000_00],
  ];
  return h("div", {}, h("h3", {}, "Getting started"),
    steps.map(([text, done]) => h("div", { class: done ? "good" : "" }, (done ? "✓ " : "○ ") + text)));
}

function globePanel() {
  const s = store.state;
  const v = store.view;
  const region = v.regionId ? regionById(v.regionId) : null;
  const box = h("div", {});
  if (!region) {
    box.append(h("h2", {}, "World map"), h("p", { class: "muted" }, "Drag to rotate, scroll to zoom. Click a region to see its market."));
    if (s.datacenters.length) {
      box.append(h("h3", {}, "Your datacenters"));
      for (const dc of s.datacenters) box.append(dcCard(dc));
    }
    box.append(guide(s));
    return box;
  }
  const myDcs = s.datacenters.filter((d) => d.region_id === region.id);
  box.append(
    h("div", { class: "row" }, h("h2", { style: "flex:1;margin:0" }, region.name), h("button", { class: "secondary small", onclick: () => nav({ mode: "globe", regionId: null }) }, "Close")),
    h("h3", {}, "Market"),
    stat("Customer demand", num(region.demand_units) + " units"),
    stat("Unserved demand", num(region.free_units) + " units", region.free_units > region.demand_units * 0.3 ? "good" : "warn"),
    bar(1 - region.free_units / Math.max(1, region.demand_units)),
    stat("Power price", (region.power_price_cents_kwh).toFixed(0) + " c/kWh"),
    stat("Average temperature", region.avg_temp_c.toFixed(0) + " °C"),
    stat("Land cost index", region.land_cost_index.toFixed(1)),
  );
  if (region.events.length) box.append(h("p", { class: "warn" }, "Active: " + region.events.map((e) => e.replace("_", " ")).join(", ")));
  box.append(h("h3", {}, "Market share"));
  const shares = s.market_share.filter((m) => m.region_id === region.id).sort((a, b) => b.share - a.share);
  const nameOf = (id) => (id === s.company.id ? s.company.name + " (you)" : s.rivals.find((r) => r.id === id)?.name || "?");
  const colorOf = (id) => (id === s.company.id ? s.company.color : s.rivals.find((r) => r.id === id)?.color);
  if (!shares.length) box.append(h("p", { class: "muted" }, "Nobody serves this region yet."));
  for (const m of shares) {
    box.append(h("div", { class: "stat" }, h("span", { style: `color:${colorOf(m.company_id)}` }, nameOf(m.company_id)), h("span", {}, pct(m.share, 1))));
  }
  box.append(h("h3", {}, "Your datacenters here"));
  for (const dc of myDcs) box.append(dcCard(dc));
  const count = myDcs.length;
  box.append(h("button", {
    style: "width:100%;margin-top:.5rem",
    onclick: async () => {
      const r = await run("build_datacenter", { region_id: region.id }, "build");
      if (r) { toast("Datacenter built in " + region.name, "good"); nav({ mode: "room", dcId: r.datacenter_id }); }
    },
  }, `Build datacenter (${money(region.build_cost_cents)})`));
  if (count >= 3) box.append(h("p", { class: "muted" }, "Maximum of 3 per region."));
  return box;
}

function dcCard(dc) {
  const online = dc.racks.filter((r) => r.online).length;
  return h("div", { class: "item draggable", onclick: () => nav({ mode: "room", dcId: dc.id }) },
    h("div", { class: "title" }, h("span", {}, dc.name), h("span", { class: dc.perf < 1 ? "warn" : "good" }, pct(dc.perf))),
    h("div", { class: "sub" }, `${online}/${dc.racks.length} racks online | ${dc.heat_kw.toFixed(1)} kW heat | ${dc.facility_kw.toFixed(1)} kW power`));
}

// ------------------------------------------------------------------ room

function roomPanel() {
  const s = store.state;
  const dc = dcById(store.view.dcId);
  if (!dc) return h("div", {});
  const region = regionById(dc.region_id);
  const box = h("div", {});
  const heatRatio = dc.cooling_cap_kw ? dc.heat_kw / dc.cooling_cap_kw : 0;
  const powerRatio = dc.facility_kw / dc.power_capacity_kw;
  const uplinkNeed = dc.racks.reduce((a, r) => a + (r.stats.tor_count ? r.stats.uplinks_needed : 0), 0);
  box.append(
    h("h2", {}, dc.name), h("p", { class: "muted" }, region.name),
    h("h3", {}, "Cooling"),
    stat("Heat / cooling capacity", `${dc.heat_kw.toFixed(1)} / ${dc.cooling_cap_kw.toFixed(1)} kW`, heatRatio > 1 ? "bad" : ""),
    bar(heatRatio, heatRatio > 1 ? "badbar" : heatRatio > 0.85 ? "warnbar" : ""),
    h("h3", {}, "Power"),
    stat("Facility load / grid", `${dc.facility_kw.toFixed(1)} / ${dc.power_capacity_kw.toFixed(0)} kW`, powerRatio > 1 ? "bad" : ""),
    bar(powerRatio, powerRatio > 1 ? "badbar" : powerRatio > 0.85 ? "warnbar" : ""),
    h("h3", {}, "Network"),
    stat("Uplink ports used / available", `${uplinkNeed} / ${dc.uplink_ports}`, uplinkNeed > dc.uplink_ports ? "bad" : ""),
    bar(dc.uplink_ports ? uplinkNeed / dc.uplink_ports : 1, uplinkNeed > dc.uplink_ports ? "badbar" : ""),
    stat("Performance", pct(dc.perf), dc.perf < 1 ? "warn" : "good"),
    stat("Sold capacity", pct(dc.util)),
  );
  box.append(h("div", { class: "row", style: "margin:.6rem 0" },
    h("button", { class: heatmapOn ? "" : "secondary", onclick: () => { heatmapOn = !heatmapOn; bus.emit("heatmap", heatmapOn); renderContext(true); } }, "Heatmap " + (heatmapOn ? "on" : "off"))));

  box.append(h("h3", {}, "Racks"),
    h("p", { class: "muted" }, `${dc.racks.length}/${dc.max_racks}. Click a rack to edit it, or an empty slot to install a new one.`));
  const select = h("select", { onchange: (e) => { templateChoice = e.target.value; } },
    h("option", { value: "" }, `Empty rack (${money(store.hw.rules.rack_shell_cents)})`),
    s.templates.map((t) => h("option", { value: t.id, selected: String(t.id) === templateChoice }, `Template: ${t.name}`)));
  box.append(h("label", { class: "muted" }, "New racks are installed as:"), select);
  box.append(h("button", { style: "width:100%;margin-top:.4rem", onclick: () => bus.emit("buy-rack", { template: templateChoice }) }, "Install rack in next free slot"));
  if (s.templates.length) {
    box.append(h("h3", {}, "Templates"));
    for (const t of s.templates) {
      box.append(h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, t.name),
        h("button", { class: "danger small", onclick: async () => { if (await run("delete_template", { template_id: t.id })) sfx.click(); } }, "Delete")),
        h("div", { class: "sub" }, `${t.layout.length} devices`)));
    }
  }

  box.append(h("h3", {}, "Datacenter equipment"));
  for (const hw of store.hw.list.filter((x) => x.category.startsWith("dc_"))) {
    const owned = dc.equipment[hw.code] || 0;
    box.append(h("div", { class: "item" },
      h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `x${owned}`)),
      h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, money(hw.price_cents)),
        h("button", { class: "small", onclick: async () => { if (await run("buy_dc_equipment", { datacenter_id: dc.id, code: hw.code, qty: 1 }, "build")) toast(`${hw.name} installed`, "good"); } }, "Buy"))));
  }
  box.append(h("h3", {}, "Racks in this room"));
  for (const r of dc.racks) {
    box.append(h("div", { class: "item draggable", onclick: () => nav({ mode: "rack", dcId: dc.id, rackId: r.id }) },
      h("div", { class: "title" }, h("span", {}, r.name), h("span", { class: r.online ? "good" : "bad" }, r.online ? "online" : (r.offline_text || "offline"))),
      h("div", { class: "sub" }, `${r.stats.used_u}/42 U | ${kw(r.stats.load_w)} | ${r.stats.server_count} servers`)));
  }
  return box;
}

// ------------------------------------------------------------------ rack builder

const GROUPS = [
  ["Compute", ["server_cpu"]], ["Storage", ["server_storage"]], ["AI / GPU", ["server_gpu"]],
  ["Network", ["switch_tor"]], ["Power", ["pdu", "ups"]], ["Extras", ["patch_panel", "cable_mgmt", "blank"]],
];

function hwCard(hw, rack) {
  const el = h("div", { class: "item draggable", draggable: "true", title: "Drag into the rack, or click to mount at the first free spot" },
    h("div", { class: "title" }, h("span", {}, hw.name), h("span", {}, money(hw.price_cents))),
    h("div", { class: "sub" }, [`${hw.u_height} U`, hw.power_w ? `${hw.power_w} W` : null, hw.ports ? `${hw.ports} ports` : null,
      hw.attrs.cpu ? `${hw.attrs.cpu} cpu` : null, hw.attrs.storage_tb ? `${hw.attrs.storage_tb} TB` : null,
      hw.attrs.gpu ? `${hw.attrs.gpu} gpu` : null, hw.attrs.max_w ? `${hw.attrs.max_w / 1000} kW max` : null,
      hw.attrs.nic ? `${hw.attrs.nic} NIC` : null].filter(Boolean).join(" | ")));
  el.addEventListener("dragstart", (ev) => {
    ev.dataTransfer.setData("text/plain", hw.code);
    ev.dataTransfer.effectAllowed = "copy";
    bus.emit("palette", hw.code);
  });
  el.addEventListener("dragend", () => bus.emit("palette", null));
  el.addEventListener("click", async () => {
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
  const palette = h("div", {});
  for (const [title, cats] of GROUPS) {
    palette.append(h("h3", {}, title));
    for (const hw of store.hw.list.filter((x) => cats.includes(x.category))) palette.append(hwCard(hw));
  }
  const dcId = found.dc.id;
  root.replaceChildren(
    h("div", { class: "row" }, h("h2", { style: "flex:1;margin:0" }, found.rack.name),
      h("button", { class: "secondary small", onclick: () => nav({ mode: "room", dcId }) }, "Back")),
    statsBox, selBox,
    h("div", { class: "row", style: "margin:.6rem 0" },
      h("button", { class: "secondary small", onclick: async () => {
        const name = prompt("Template name:", found.rack.name + " template");
        if (name && await run("save_template", { rack_id: store.view.rackId, name }, "click")) toast("Template saved", "good");
      } }, "Save template"),
      h("button", { class: "secondary small", onclick: async () => {
        const r = await run("buy_rack", { datacenter_id: dcId, clone_rack_id: store.view.rackId }, "build");
        if (r) { toast("Rack cloned", "good"); nav({ mode: "rack", dcId, rackId: r.rack_id }); }
      } }, "Clone rack"),
      h("button", { class: "danger small", onclick: async () => {
        if (!confirm("Sell this rack and everything in it? You get " + Math.round(store.hw.rules.sell_back_ratio * 100) + " % back.")) return;
        if (await run("sell_rack", { rack_id: store.view.rackId }, "unmount")) nav({ mode: "room", dcId });
      } }, "Sell rack")),
    h("div", { class: "muted", style: "font-size:.8rem" }, "Drag equipment into the rack. Drag mounted devices to move them. Del removes the selected device."),
    palette,
  );
  rackBuilt = { rackId: found.rack.id, statsBox, selBox };
  updateSelection();
}

function chip(text, ok) { return h("span", { class: "tag " + (ok ? "ok" : "bad") }, text); }

function updateRackStats(found) {
  const { rack, dc } = found;
  const st = rack.stats;
  const box = rackBuilt.statsBox;
  const loadRatio = st.limit_w ? st.load_w / st.limit_w : 0;
  const kids = [];
  if (!rack.online) {
    kids.push(h("div", { class: "item", style: "border-color:var(--bad)" },
      h("div", { class: "title bad" }, "OFFLINE: " + (rack.offline_text || "no power")),
      rack.status !== "ok" ? h("button", { class: "small", style: "margin-top:.3rem", onclick: async () => {
        if (await run("repair_rack", { rack_id: rack.id }, "build")) toast("Rack repaired", "good");
      } }, rack.status === "tripped" ? "Reset breaker (free)" : `Repair now (${money(store.hw.rules.repair_cost_cents)})`) : null));
  }
  const item = (ok, text) => h("div", { class: "check " + (ok ? "ok" : "no") }, (ok ? "✓" : "✗") + " " + text);
  kids.push(
    h("h3", {}, "Checklist"),
    item(st.pdu_count > 0, st.pdu_count ? `Power: ${st.pdu_count} PDU` : "Power: add a PDU"),
    item(st.tor_count > 0, st.tor_count ? `Network: ${st.tor_count} ToR switch` : "Network: add a ToR switch"),
    item(st.server_count > 0 && st.connected_ids.length === st.server_count, `Servers connected: ${st.connected_ids.length}/${st.server_count}`),
    item(rack.online, rack.online ? "Rack is online and sellable" : "Rack is offline"),
    h("h3", {}, "Details"),
    stat("Rack space",`${st.used_u} / ${store.hw.rules.rack_u} U`), bar(st.used_u / store.hw.rules.rack_u),
    stat("Power draw / limit", `${kw(st.load_w)} / ${kw(st.limit_w)}`, st.overload ? "bad" : ""),
    bar(loadRatio, st.overload ? "badbar" : loadRatio > 0.85 ? "warnbar" : ""),
    stat("Heat output", kw(st.heat_w)),
    stat("Switch ports used", `${st.ports_used} / ${st.ports_total}`), bar(st.ports_total ? st.ports_used / st.ports_total : 0),
    h("div", { style: "margin:.3rem 0" }, chip("Power N+1", st.power_redundant), chip("2x ToR", st.net_redundant), chip("UPS", st.has_ups)),
    h("h3", {}, "Sellable capacity"),
    stat("CPU units", num(st.cpu)), stat("Storage", num(st.storage_tb) + " TB"), stat("GPU units", num(st.gpu)),
  );
  if (st.warnings.length) kids.push(h("ul", { class: "warnings" }, st.warnings.map((w) => h("li", { class: /Overload|No PDU|No ToR/.test(w) ? "bad" : "" }, w))));
  if (dc.perf < 1) kids.push(h("p", { class: "warn" }, `Datacenter throttled to ${pct(dc.perf)} (cooling or power).`));
  box.replaceChildren(...kids);
}

function updateSelection() {
  if (!rackBuilt) return;
  const box = rackBuilt.selBox;
  if (!selectedItem) { box.replaceChildren(); return; }
  const hw = store.hw.byCode[selectedItem.code];
  const id = selectedItem.id;
  box.replaceChildren(h("div", { class: "item", style: "border-color:#ffd33d" },
    h("div", { class: "title" }, h("span", {}, hw.name), h("span", { class: "muted" }, `U${selectedItem.u_start}`)),
    h("div", { class: "row" }, h("span", { class: "sub", style: "flex:1" }, `Sell for ${money(hw.price_cents * store.hw.rules.sell_back_ratio)}`),
      h("button", { class: "danger small", onclick: () => bus.emit("remove", id) }, "Remove"))));
}

export { canPlaceItems };

export const currentTemplate = () => templateChoice;
