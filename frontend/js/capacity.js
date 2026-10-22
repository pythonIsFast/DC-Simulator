// Sellable capacity per region (computed by the server): total, sold and free per resource.
import { h, num, bar, stat } from "./util.js";
import { store } from "./store.js";

export const RES_LABEL = { cpu: "CPU units", storage_tb: "TB storage", gpu: "GPU units" };
const TITLE = { cpu: "CPU", storage_tb: "Storage (TB)", gpu: "GPU" };

export function capacityBlock(regionId) {
  const cap = store.state.capacity[regionId];
  const box = h("div", {});
  let any = false;
  for (const key of ["cpu", "storage_tb", "gpu"]) {
    const c = cap?.[key];
    if (!c || (c.total <= 0 && c.sold <= 0)) continue;
    any = true;
    const ratio = c.total ? c.sold / c.total : 1;
    box.append(stat(TITLE[key], `${num(c.free)} free of ${num(c.total)}`, c.free < 0 ? "bad" : ""),
      bar(ratio, ratio > 1 ? "badbar" : ratio > 0.9 ? "warnbar" : ""));
  }
  if (!any) box.append(h("p", { class: "muted" }, "Nothing to sell yet. Mount servers in a rack that is online."));
  return box;
}
