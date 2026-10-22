// "What now?" card: tells the player the next concrete step based on the current state.
import { $, h, money2 } from "./util.js";
import { store } from "./store.js";

function nextStep(s) {
  const racks = s.datacenters.flatMap((d) => d.racks);
  const any = (fn) => racks.some(fn);
  const net = s.company.revenue_cents_per_tick - s.company.expense_cents_per_tick;
  const notServed = s.contracts.find((c) => c.sla_fail_streak > 0);

  if (!s.datacenters.length) {
    return ["1. Build a datacenter", "Click a region on the globe, then \"Build datacenter\"."];
  }
  if (!racks.length) {
    return ["2. Install a rack", "Open your datacenter, then click an empty square."];
  }
  if (!any((r) => r.stats.pdu_count > 0)) {
    return ["3. Add power", "Open the rack and drag a PDU into it."];
  }
  if (!any((r) => r.stats.tor_count > 0)) {
    return ["3. Add a switch", "Drag a ToR Switch into the rack."];
  }
  if (!any((r) => r.stats.server_count > 0)) {
    return ["3. Add servers", "Drag a few Compute servers into the rack."];
  }
  if (!any((r) => r.online)) {
    const r = racks[0];
    return ["The rack is offline", `Reason: ${r.offline_text || "unknown"}. Fix it in the rack panel (red box).`];
  }
  if (!s.contracts.length) {
    return ["4. Win a customer", "Open Contracts and accept an offer."];
  }
  if (s.world.speed === 0) {
    return ["5. Start the clock", "Press 1x, 2x or 5x. Money only flows while time runs."];
  }
  if (notServed) {
    return ["A contract is not served!", `"${notServed.name}" needs more capacity. Add servers (or fix offline racks). After 48 h it is breached.`];
  }
  if (net < 0) {
    return ["You are losing money", "Costs are higher than revenue. Accept more contracts and mount more servers to sell."];
  }
  return ["Keep growing", "Add servers, take more contracts, open new regions."];
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
      `Per hour: revenue ${money2(b.revenue || 0)} | costs ${money2(costs)}`),
  );
}
