// Client-side mirror of the server's rack placement rules (backend/racks.py placement_error).
// Only used for instant feedback; the server stays authoritative.
import { store } from "./store.js";

export function canPlaceItems(items, hw, uStart, ignoreId = null) {
  const rackU = store.hw.rules.rack_u;
  if (hw.u_height < 1) return false;
  const top = uStart + hw.u_height - 1;
  if (uStart < 1 || top > rackU) return false;
  const others = items.filter((i) => i.id !== ignoreId);
  for (const i of others) {
    const o = store.hw.byCode[i.code];
    if (uStart <= i.u_start + o.u_height - 1 && top >= i.u_start) return false;
  }
  const limit = store.hw.rules.max_per_rack?.[hw.category];
  if (limit !== undefined && others.filter((i) => store.hw.byCode[i.code].category === hw.category).length >= limit) return false;
  return true;
}

const FROM_TOP = new Set(["switch_tor", "pdu", "patch_panel", "cable_mgmt", "ups"]);

// First free position for `hw`: network/power gear from the top, servers from the bottom.
export function firstFit(items, hw) {
  const rackU = store.hw.rules.rack_u;
  if (FROM_TOP.has(hw.category)) {
    for (let u = rackU - hw.u_height + 1; u >= 1; u--) if (canPlaceItems(items, hw, u)) return u;
  } else {
    for (let u = 1; u <= rackU - hw.u_height + 1; u++) if (canPlaceItems(items, hw, u)) return u;
  }
  return null;
}
