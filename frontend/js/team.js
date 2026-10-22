// Team drawer: plans proposed by admins, work in progress, employees and the job market.
import { h, money, money2, num, bar } from "./util.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";

const ROLE = {
  technician: ["Technician", "Builds approved plans. Repairs failures faster."],
  admin: ["Admin", "Plans racks, datacenters and upgrades. Prevents failures."],
  sales: ["Sales", "Signs customer contracts for you and negotiates better prices."],
};
const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);
const hours = (t) => `${Math.max(1, Math.round(t))} h`;
const tile = (label, value) => h("div", { class: "tile" }, h("div", { class: "muted", style: "font-size:.75rem" }, label), h("div", { class: "big" }, value));

const LEVELS = [[0, "Off"], [1, "Low"], [2, "Normal"], [3, "High"]];
const PRIORITY_ROWS = [
  ["capacity", "New capacity", "Racks and servers for customer demand"],
  ["reliability", "Reliability", "Redundancy, bigger PDUs"],
  ["infrastructure", "Infrastructure", "Cooling, power, uplinks"],
  ["expansion", "Expansion", "New datacenters"],
  ["cleanup", "Rack style", "Rebuild mixed racks"],
  ["modernize", "Modernization", "Replace old servers with denser ones"],
];

function select(options, value, onchange) {
  return h("select", { onchange: (e) => onchange(e.target.value) },
    options.map(([v, label]) => h("option", { value: String(v), selected: String(v) === String(value) }, label)));
}

const field = (label, control) => h("div", { class: "row", style: "justify-content:space-between;margin:.25rem 0" }, h("span", { style: "font-size:.9rem" }, label), h("div", { style: "min-width:11rem" }, control));

// What the player wants from the admins: style, priorities, focus, budget.
function policySection(t) {
  const p = t.policy;
  const save = (patch) => run("set_admin_policy", { policy: patch }, "click");
  const box = h("details", { open: true }, h("summary", {}, "Admin priorities"));
  box.append(
    h("p", { class: "muted", style: "font-size:.82rem;margin:.3rem 0" }, `Each admin suggests at most one plan every ${t.proposal_interval_days} days. A new admin needs two days to get started.`),
    field("Rack style", select([["pure", "One kind per rack"], ["mixed", "Mixed racks allowed"]], p.rack_style, (v) => save({ rack_style: v }))),
    field("Focus", select([["auto", "Wherever customers wait"], ["cpu", "Compute"], ["storage_tb", "Storage"], ["gpu", "GPU / AI"]], p.focus, (v) => save({ focus: v }))),
    field("Max cost per plan", select([[25, "25 % of cash"], [50, "50 % of cash"], [90, "90 % of cash"]], p.budget_pct, (v) => save({ budget_pct: Number(v) }))),
    field("Auto-hire people", select([["off", "Off: I hire"], ["on", "On"]], p.auto_hire, (v) => save({ auto_hire: v }))),
    ...(p.auto_hire === "on" ? [field("Minimum skill", select([[1, "1 star or more"], [2, "2 stars or more"], [3, "3 stars or more"]], p.hire_min_skill, (v) => save({ hire_min_skill: Number(v) }))),
      h("p", { class: "muted", style: "font-size:.8rem;margin:0 0 .3rem" }, `Keeps ${t.targets.technician} technician(s), ${t.targets.admin} admin(s) and ${t.targets.sales} sales for your current size. Only hires if ten days of salaries stay in the bank.`)] : []),
    field("Auto-approve plans", select([["off", "Off: I decide"], ["cheap", "Small plans only"], ["all", "All within the cost limit"]], p.auto_approve, (v) => save({ auto_approve: v }))),
    ...(p.auto_approve === "off" ? [] : [h("p", { class: "muted", style: "font-size:.8rem;margin:0 0 .3rem" }, p.auto_approve === "cheap" ? "Plans up to 10 % of your cash are approved automatically. New datacenters always ask you." : `Every plan up to ${p.budget_pct} % of your cash is approved automatically, including new datacenters.`)]),
    field("Redundancy (new racks)", select([["auto", "By admin skill"], ["always", "Always"], ["never", "Never (cheaper)"]], p.redundancy, (v) => save({ redundancy: v }))),
    h("h3", {}, "What should they work on?"),
    ...PRIORITY_ROWS.map(([key, label, hint]) => h("div", { style: "margin:.25rem 0" },
      field(label, select(LEVELS, p.priorities[key], (v) => save({ priorities: { [key]: Number(v) } }))),
      h("div", { class: "muted", style: "font-size:.75rem;margin-top:-.15rem" }, hint))),
  );
  if (p.rack_style === "pure") box.append(h("p", { class: "muted", style: "font-size:.8rem" }, "Admins also propose to rebuild existing racks that mix compute, storage and GPU servers."));
  return box;
}

function proposalCard(p, hasTech) {
  const adds = Object.entries(p.adds || {}).map(([k, v]) => `${num(v)} ${{ cpu: "CPU", storage_tb: "TB", gpu: "GPU" }[k]}`).join(", ");
  return h("div", { class: "item" },
    h("div", { class: "title" }, h("span", {}, p.title), h("span", { class: "muted" }, money(p.cost_cents))),
    h("div", { class: "sub" }, `Proposed by ${p.admin || "an admin"} · ${hours(p.est_ticks)} to build`),
    ...p.lines.map((l) => h("div", { class: "sub", style: "margin-top:.2rem" }, l)),
    p.revenue_cents_per_tick ? h("div", { class: "good", style: "font-size:.88rem;margin-top:.2rem" }, `Could earn about ${money2(p.revenue_cents_per_tick)}/h when sold${adds ? " (" + adds + ")" : ""}`) : null,
    p.removes && p.removes.length ? h("div", { class: "sub", style: "margin-top:.2rem" }, "Removes: " + p.removes.map((r) => `${r.count}x ${r.name}`).join(", ")) : null,
    p.items.length ? h("details", {}, h("summary", {}, "What gets installed"), ...p.items.map((i) => h("div", { class: "sub" }, `${i.count}× ${i.name}`))) : null,
    !hasTech ? h("div", { class: "warn", style: "font-size:.85rem;margin-top:.3rem" }, "You have no technician yet: nobody can build this.") : null,
    h("div", { class: "row", style: "margin-top:.4rem" },
      h("button", { class: "small", onclick: async () => { if (await run("approve_proposal", { proposal_id: p.id }, "build")) toast(`Approved: ${p.title}`, "good"); } }, `Approve and pay ${money(p.cost_cents)}`),
      h("button", { class: "secondary small", onclick: async () => { if (await run("reject_proposal", { proposal_id: p.id }, "click")) sfx.click(); } }, "Reject")));
}

function employeeCard(e) {
  const [roleName] = ROLE[e.role];
  return h("div", { class: "item" },
    h("div", { class: "title" }, h("span", {}, e.name, h("span", { class: "tag" }, roleName)), h("span", { style: "color:var(--warn)" }, stars(e.skill))),
    h("div", { class: "sub" }, `${money2(e.salary_cents_per_tick)}/h · ${e.status === "working" ? "Working: " + (e.task || "") : "Idle"}`),
    e.skill < 5 ? bar(e.xp / e.xp_needed) : null,
    h("div", { class: "row", style: "justify-content:flex-end" },
      h("button", { class: "danger small", onclick: async () => { if (confirm(`Fire ${e.name}?`)) await run("fire_employee", { employee_id: e.id }, "unmount"); } }, "Fire")));
}

function candidateCard(c) {
  const [roleName, desc] = ROLE[c.role];
  return h("div", { class: "item" },
    h("div", { class: "title" }, h("span", {}, c.name, h("span", { class: "tag" }, roleName)), h("span", { style: "color:var(--warn)" }, stars(c.skill))),
    h("div", { class: "sub" }, `${desc} ${money2(c.salary_cents_per_tick)}/h`),
    h("div", { class: "row", style: "justify-content:flex-end;margin-top:.3rem" },
      h("button", { class: "small", onclick: async () => { if (await run("hire_candidate", { candidate_id: c.id }, "cash")) toast(`${c.name} joined the team`, "good"); } }, `Hire for ${money(c.hire_cost_cents)}`)));
}

export function teamView(s) {
  const t = s.team;
  const hasTech = t.employees.some((e) => e.role === "technician");
  const hasAdmin = t.employees.some((e) => e.role === "admin");
  const box = h("div", {});
  box.append(h("div", { class: "tiles" },
    tile("Team", `${t.employees.length}/${t.max_employees}`), tile("Salaries", `${money2(t.salary_cents_per_tick)}/h`), tile("Open plans", String(t.proposals.length))));

  if (t.employees.some((e) => e.role === "sales")) {
    box.append(h("div", { class: "item", style: "margin-top:.6rem" },
      h("div", { class: "title" }, h("span", {}, "Auto-accept contracts"), h("span", { class: t.auto_accept ? "good" : "muted" }, t.auto_accept ? "ON" : "OFF")),
      h("div", { class: "sub" }, `Sales signs up to ${t.sales_per_day} offers per day, only if you have the free capacity.`),
      h("div", { class: "row", style: "justify-content:flex-end;margin-top:.3rem" },
        h("button", { class: "secondary small", onclick: () => run("set_auto_accept", { enabled: !t.auto_accept }, "click") }, t.auto_accept ? "Turn off" : "Turn on"))));
  }

  box.append(policySection(t));
  box.append(h("h3", {}, "Plans from your admins"));
  if (!hasAdmin) box.append(h("p", { class: "muted" }, "Hire an admin: they suggest racks (with an exact layout), new datacenters and upgrades. You decide what gets built."));
  else if (!t.proposals.length) box.append(h("p", { class: "muted" }, "No plans right now. Admins come up with new ideas every day."));
  t.proposals.forEach((p) => box.append(proposalCard(p, hasTech)));

  if (t.orders.length) {
    box.append(h("h3", {}, "Work in progress"));
    t.orders.forEach((o) => box.append(h("div", { class: "item" },
      h("div", { class: "title" }, h("span", {}, o.title)),
      bar(o.progress / o.total_ticks),
      h("div", { class: "sub" }, o.status === "in_progress" ? `${o.employee} is working on it` : "Waiting for a free technician"))));
  }

  box.append(h("h3", {}, "Your team"));
  if (!t.employees.length) box.append(h("p", { class: "muted" }, "Nobody yet. Hire from the list below."));
  else {
    const e = t.effects;
    box.append(h("p", { class: "muted", style: "font-size:.85rem;margin:0 0 .3rem" },
      `Repairs take ${Math.round(e.repair_factor * 100)} % of the normal time${hasTech ? "" : " (no technician)"}. Failure chance ${Math.round((e.incident_mult - 1) * 100)} %.`));
    t.employees.forEach((x) => box.append(employeeCard(x)));
  }

  box.append(h("h3", {}, "Job market"));
  if (!t.candidates.length) box.append(h("p", { class: "muted" }, "No candidates right now."));
  t.candidates.forEach((c) => box.append(candidateCard(c)));
  return box;
}
