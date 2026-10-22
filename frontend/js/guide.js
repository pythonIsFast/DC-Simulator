// "What now?" card: tells the player the next concrete step based on the current state.
import { $, h, money2 } from "./util.js";
import { store } from "./store.js";

function nextStep(s) {
  const racks = s.datacenters.flatMap((d) => d.racks);
  const any = (fn) => racks.some(fn);
  const net = s.company.revenue_cents_per_tick - s.company.expense_cents_per_tick;
  const notServed = s.contracts.find((c) => c.sla_fail_streak > 0);

  if (!s.datacenters.length) {
    return ["1/6 Build a datacenter", "Click a region on the globe (e.g. Frankfurt) and press \"Build datacenter\" in the right panel."];
  }
  if (!racks.length) {
    return ["2/6 Install a rack", "Click your datacenter in the right panel. In the room, click an empty blue square to install a rack."];
  }
  if (!any((r) => r.stats.pdu_count > 0)) {
    return ["3/6 Add power", "Click the rack to open it. Drag a PDU (Power) from the list on the right into the rack. Two PDUs = redundancy."];
  }
  if (!any((r) => r.stats.tor_count > 0)) {
    return ["3/6 Add a network switch", "Drag a ToR Switch (Network) into the rack. Servers have no network without it."];
  }
  if (!any((r) => r.stats.server_count > 0)) {
    return ["3/6 Add servers", "Drag servers into the rack, e.g. several \"Compute 1U\". Each server needs a free switch port."];
  }
  if (!any((r) => r.online)) {
    const r = racks[0];
    return ["The rack is offline", `Reason: ${r.offline_text || "unknown"}. Fix it in the rack panel (red box).`];
  }
  if (!s.contracts.length) {
    return ["4/6 Win customers", "Open \"Contracts\" at the top and accept an offer you have capacity for. Without customers you only pay costs."];
  }
  if (s.world.speed === 0) {
    return ["5/6 Start the clock", "Time is paused. Press 1x, 2x or 5x (or Space). Money only flows while time runs."];
  }
  if (notServed) {
    return ["A contract is not served!", `"${notServed.name}" needs more capacity. Add servers (or fix offline racks). After 48 h it is breached.`];
  }
  if (net < 0) {
    return ["You are losing money", "Costs are higher than revenue. Accept more contracts and mount more servers to sell."];
  }
  return ["6/6 Expand", "Add servers, accept more contracts, watch heat and power in the datacenter panel, then open new regions. Rivals grow every day."];
}

export function renderGuide() {
  const s = store.state;
  const el = $("guide");
  if (!s) { el.hidden = true; return; }
  const [title, text] = nextStep(s);
  el.hidden = false;
  const b = s.company.breakdown || {};
  const costs = -((b.power || 0) + (b.rent || 0) + (b.staff || 0));
  el.replaceChildren(
    h("b", {}, title), h("div", {}, text),
    h("div", { class: "muted", style: "margin-top:.3rem;font-size:.8rem" },
      `Per hour: revenue ${money2(b.revenue || 0)} | power ${money2(-(b.power || 0))} | rent ${money2(-(b.rent || 0))} | staff ${money2(-(b.staff || 0))} | costs total ${money2(costs)}`),
  );
}
