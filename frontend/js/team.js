// Team drawer: plans proposed by admins, work in progress, employees and the job market.
import { h, money, money2, num, bar } from "./util.js";
import { run, toast } from "./ui.js";
import { sfx } from "./audio.js";

const ROLE = {
  technician: ["Technician", "Builds approved plans. Repairs failures faster."],
  admin: ["Admin", "Plans racks, datacenters and upgrades. Prevents failures."],
};
const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);
const hours = (t) => `${Math.max(1, Math.round(t))} h`;
const tile = (label, value) => h("div", { class: "tile" }, h("div", { class: "muted", style: "font-size:.75rem" }, label), h("div", { class: "big" }, value));

function proposalCard(p, hasTech) {
  const adds = Object.entries(p.adds || {}).map(([k, v]) => `${num(v)} ${{ cpu: "CPU", storage_tb: "TB", gpu: "GPU" }[k]}`).join(", ");
  return h("div", { class: "item" },
    h("div", { class: "title" }, h("span", {}, p.title), h("span", { class: "muted" }, money(p.cost_cents))),
    h("div", { class: "sub" }, `Proposed by ${p.admin || "an admin"} · ${hours(p.est_ticks)} to build`),
    ...p.lines.map((l) => h("div", { class: "sub", style: "margin-top:.2rem" }, l)),
    p.revenue_cents_per_tick ? h("div", { class: "good", style: "font-size:.88rem;margin-top:.2rem" }, `Could earn about ${money2(p.revenue_cents_per_tick)}/h when sold${adds ? " (" + adds + ")" : ""}`) : null,
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
