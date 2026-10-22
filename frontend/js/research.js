// Research drawer: unlock hardware and permanent bonuses.
import { h, money, num, bar } from "./util.js";
import { run, toast } from "./ui.js";

const BRANCH_ORDER = ["Compute", "Storage", "GPU / AI", "Network", "Facility", "Operations"];
const STATUS_TEXT = { done: "Researched", researching: "In progress", available: "", locked: "Locked" };

function effectText(effects) {
  const out = [];
  if (effects.pue) out.push(`Power overhead ${effects.pue > 0 ? "+" : ""}${effects.pue}`);
  if (effects.tech_speed) out.push(`+${Math.round(effects.tech_speed * 100)} % technician speed`);
  if (effects.incident_mult) out.push(`${Math.round(effects.incident_mult * 100)} % failure chance`);
  if (effects.revenue_mult) out.push(`+${Math.round(effects.revenue_mult * 100)} % contract revenue`);
  return out.join(", ");
}

function techCard(t, r) {
  const info = [];
  if (t.unlocks.length) info.push("Unlocks: " + t.unlocks.join(", "));
  const eff = effectText(t.effects);
  if (eff) info.push(eff);
  const canStart = t.status === "available" && r.active < r.max_parallel;
  return h("div", { class: "item", style: t.status === "locked" ? "opacity:.55" : t.status === "done" ? "border-color:var(--good)" : "" },
    h("div", { class: "title" }, h("span", {}, t.name), h("span", { class: t.status === "done" ? "good" : "muted" }, STATUS_TEXT[t.status])),
    h("div", { class: "sub" }, t.desc),
    ...info.map((i) => h("div", { class: "sub", style: "color:var(--accent)" }, i)),
    t.status === "locked" ? h("div", { class: "sub" }, "Needs: " + t.requires.join(", ")) : null,
    t.status === "researching" ? bar(t.progress) : null,
    t.status === "available" || t.status === "locked"
      ? h("div", { class: "row", style: "margin-top:.3rem" }, h("span", { class: "sub", style: "flex:1" }, `${money(t.cost_cents)} · ${num(t.ticks / 24, 1)} days`),
        h("button", { class: "small", disabled: !canStart, title: canStart ? "" : (t.status === "locked" ? "Research the requirements first" : "Two projects at a time"),
          onclick: async () => { if (await run("start_research", { code: t.code }, "build")) toast(`Research started: ${t.name}`, "good"); } }, "Research"))
      : null);
}

export function researchView(s) {
  const r = s.research;
  const box = h("div", {});
  box.append(h("p", { class: "muted", style: "font-size:.85rem;margin:.3rem 0" },
    `Research unlocks new hardware and bonuses. ${r.active}/${r.max_parallel} projects running. Skilled admins research faster.`));
  for (const branch of BRANCH_ORDER) {
    const techs = r.techs.filter((t) => t.branch === branch);
    if (!techs.length) continue;
    box.append(h("h3", {}, branch), ...techs.map((t) => techCard(t, r)));
  }
  return box;
}
