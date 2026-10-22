// Tutorial card: guides through the first steps, then disappears for good.
// Afterwards it only shows up as a red alert when something needs attention.
import { $, h } from "./util.js";
import { store } from "./store.js";

const KEY = "dc_tutorial_off";
let skipped = false;
try { skipped = localStorage.getItem(KEY) === "1"; } catch { /* storage unavailable */ }

function problem(s, racks) {
  const notServed = s.contracts.find((c) => c.sla_fail_streak > 0);
  if (notServed) return [`"${notServed.name}" is not served`, "Add servers or repair offline racks. After 48 h the contract is breached."];
  const offline = racks.find((r) => r.stats.server_count > 0 && !r.online);
  if (offline) return [`${offline.name} is offline`, `${offline.offline_text || "Unknown reason"}. Open the rack to fix it.`];
  return null;
}

function tutorialStep(s, racks) {
  const any = (fn) => racks.some(fn);
  if (!s.datacenters.length) return ["1. Build a datacenter", "Click a region on the globe, then \"Build datacenter\"."];
  if (!racks.length) return ["2. Install a rack", "Open your datacenter, then click an empty square."];
  if (!any((r) => r.stats.pdu_count > 0)) return ["3. Add power", "Open the rack and drag a PDU into it."];
  if (!any((r) => r.stats.tor_count > 0)) return ["3. Add a switch", "Drag a ToR Switch into the rack."];
  if (!any((r) => r.stats.server_count > 0)) return ["3. Add servers", "Drag a few Compute servers into the rack."];
  if (!s.contracts.length) return ["4. Win a customer", "Open Contracts and accept an offer."];
  if (s.world.speed === 0) return ["5. Start the clock", "Press 1x, 2x or 5x. Money only flows while time runs."];
  return null; // tutorial finished
}

export function renderGuide() {
  const s = store.state;
  const el = $("guide");
  if (!s) { el.hidden = true; return; }
  const racks = s.datacenters.flatMap((d) => d.racks);
  const alert = problem(s, racks);
  const step = skipped ? null : tutorialStep(s, racks);
  const shown = alert || step;
  if (!shown) { el.hidden = true; return; }
  el.hidden = false;
  el.style.borderColor = alert ? "var(--bad)" : "";
  el.replaceChildren(
    h("b", { style: alert ? "color:var(--bad)" : "" }, shown[0]), h("div", {}, shown[1]),
    !alert ? h("button", { class: "secondary small", style: "margin-top:.4rem", onclick: () => {
      skipped = true;
      try { localStorage.setItem(KEY, "1"); } catch { /* ignore */ }
      renderGuide();
    } }, "Skip tutorial") : null,
  );
}
