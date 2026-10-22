"""Employees: hiring, admin proposals and technician work orders.

- Admins plan: every day they propose racks (with an exact layout), new datacenters or upgrades.
- The player approves a proposal: the cost is paid and a work order is created.
- Technicians execute work orders over time (faster with more skill) and repair incidents faster.
- Admins also lower the chance of random incidents.
"""
import json
import random

import builder
import capacity
import market
import racks as rk
import research
from bookkeeping import add_event, book, change_cash
from data import game_config as cfg

RESOURCE_CATEGORY = {"cpu": "server_cpu", "storage_tb": "server_storage", "gpu": "server_gpu"}
RESOURCE_LABEL = {"cpu": "Compute", "storage_tb": "Storage", "gpu": "GPU"}
RESOURCE_UNIT = {"cpu": "CPU units", "storage_tb": "TB storage", "gpu": "GPU units"}


class StaffError(Exception):
    pass


def salary_for(role, skill):
    return int(cfg.ROLE_BASE_SALARY_CENTS[role] * (0.7 + cfg.SALARY_PER_SKILL * skill))


def _money(cents):
    return "{:,.0f}".format(cents / 100)


# ---------------------------------------------------------------- job market

def _random_person(rng, role):
    skill = rng.choices([1, 2, 3, 4, 5], [30, 30, 22, 13, 5])[0]
    name = "%s %s" % (rng.choice(cfg.FIRST_NAMES), rng.choice(cfg.LAST_NAMES))
    return name, skill


def ensure_candidates(db, company_id, tick, rng):
    """Keep the job market stocked with both roles."""
    db.execute("DELETE FROM candidates WHERE company_id = ? AND expires_tick < ?", (company_id, tick))
    rows = db.execute("SELECT role FROM candidates WHERE company_id = ?", (company_id,)).fetchall()
    counts = {role: 0 for role in cfg.ROLES}
    for r in rows:
        counts[r["role"]] += 1
    for _ in range(cfg.CANDIDATE_POOL - len(rows)):
        role = min(cfg.ROLES, key=lambda x: (counts[x], rng.random()))
        counts[role] += 1
        name, skill = _random_person(rng, role)
        salary = salary_for(role, skill)
        db.execute(
            "INSERT INTO candidates (company_id, name, role, skill, salary_cents_per_tick, hire_cost_cents, expires_tick)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (company_id, name, role, skill, salary, salary * cfg.HIRE_COST_TICKS, tick + cfg.CANDIDATE_LIFETIME_TICKS))


def ensure_candidates_tx(db, company_id, tick):
    """Same as ensure_candidates, in its own transaction, and only if the pool is short (used on reads)."""
    n = db.execute("SELECT COUNT(*) FROM candidates WHERE company_id = ? AND expires_tick >= ?", (company_id, tick)).fetchone()[0]
    if n >= cfg.CANDIDATE_POOL:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_candidates(db, company_id, tick, random.Random(company_id * 7919 + tick))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def max_employees(db, company_id):
    """The team can grow with the company: a base plus room for every datacenter and rack."""
    dcs = db.execute("SELECT COUNT(*) FROM datacenters WHERE company_id = ? AND status = 'active'", (company_id,)).fetchone()[0]
    racks = db.execute("SELECT COUNT(*) FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE d.company_id = ?", (company_id,)).fetchone()[0]
    return min(cfg.MAX_EMPLOYEES, cfg.EMPLOYEES_BASE + cfg.EMPLOYEES_PER_DC * dcs + cfg.EMPLOYEES_PER_RACK * racks)


def staff_targets(db, company_id):
    """How many people of each role the company needs right now (used by auto-hire and shown in the UI)."""
    one = lambda sql: db.execute(sql, (company_id,)).fetchone()[0]
    dcs = one("SELECT COUNT(*) FROM datacenters WHERE company_id = ? AND status = 'active'")
    racks = one("SELECT COUNT(*) FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE d.company_id = ?")
    queued = one("SELECT COUNT(*) FROM work_orders WHERE company_id = ? AND status = 'queued'")
    contracts = one("SELECT COUNT(*) FROM contracts WHERE company_id = ? AND status = 'active'")
    technicians = 0 if racks == 0 else 1 + racks // 12 + (1 if queued >= 2 else 0)
    admins = 0 if dcs == 0 else 1 + (1 if racks >= 10 else 0) + (1 if racks >= 25 else 0)
    sales = 0 if (racks < 4 and contracts < 3) else 1 + (1 if contracts >= 15 else 0) + (1 if contracts >= 35 else 0)
    return {"technician": technicians, "admin": admins, "sales": sales}


def run_auto_hire(db, world, company, tick=None):
    """Hire from the job market where the company is short of people, if the policy allows and the cash lasts."""
    policy = get_policy(db, company["id"])
    if policy["auto_hire"] != "on":
        return 0
    world = dict(world, tick=world["tick"] if tick is None else tick)
    targets = staff_targets(db, company["id"])
    hired = 0
    for role in ("admin", "technician", "sales"):
        have = db.execute("SELECT COUNT(*) FROM employees WHERE company_id = ? AND role = ?", (company["id"], role)).fetchone()[0]
        if have >= targets[role]:
            continue
        cands = db.execute("SELECT * FROM candidates WHERE company_id = ? AND role = ? AND skill >= ? AND expires_tick >= ?"
                           " ORDER BY skill DESC, salary_cents_per_tick", (company["id"], role, policy["hire_min_skill"], world["tick"])).fetchall()
        for cand in cands:
            reserve = 10 * 24 * (salary_total(db, company["id"]) + cand["salary_cents_per_tick"])   # ten days of salaries must stay in the bank
            if cand["hire_cost_cents"] + reserve > _cash(db, company["id"]):
                continue
            try:
                hire(db, world, company, cand["id"])
            except StaffError:
                break
            add_event(db, world["id"], world["tick"], "auto_hired", "Hired %s (%s, skill %d) automatically" % (cand["name"], role, cand["skill"]), company_id=company["id"])
            hired += 1
            break
    return hired


def hire(db, world, company, candidate_id):
    cand = db.execute("SELECT * FROM candidates WHERE id = ? AND company_id = ?", (candidate_id, company["id"])).fetchone()
    if cand is None:
        raise StaffError("Candidate is no longer available")
    count = db.execute("SELECT COUNT(*) FROM employees WHERE company_id = ?", (company["id"],)).fetchone()[0]
    limit = max_employees(db, company["id"])
    if count >= limit:
        raise StaffError("The team is full (%d people). Build more datacenters and racks to grow it." % limit)
    _pay(db, world, company, cand["hire_cost_cents"], "hiring", "Hired " + cand["name"])
    cur = db.execute(
        "INSERT INTO employees (company_id, name, role, skill, salary_cents_per_tick, hired_tick) VALUES (?, ?, ?, ?, ?, ?)",
        (company["id"], cand["name"], cand["role"], cand["skill"], cand["salary_cents_per_tick"], world["tick"]))
    db.execute("DELETE FROM candidates WHERE id = ?", (cand["id"],))
    return cur.lastrowid


def fire(db, world, company, employee_id):
    emp = db.execute("SELECT * FROM employees WHERE id = ? AND company_id = ?", (employee_id, company["id"])).fetchone()
    if emp is None:
        raise StaffError("Employee not found")
    if emp["order_id"]:   # the unfinished job goes back to the queue
        db.execute("UPDATE work_orders SET status = 'queued', employee_id = NULL WHERE id = ? AND status = 'in_progress'", (emp["order_id"],))
    db.execute("DELETE FROM employees WHERE id = ?", (emp["id"],))
    return emp["name"]


def salary_total(db, company_id):
    return db.execute("SELECT COALESCE(SUM(salary_cents_per_tick), 0) FROM employees WHERE company_id = ?", (company_id,)).fetchone()[0]


def effects(db, company_id):
    """Passive effects of the team: incident probability and repair time multipliers."""
    tech = db.execute("SELECT COALESCE(SUM(skill), 0) FROM employees WHERE company_id = ? AND role = 'technician'", (company_id,)).fetchone()[0]
    adm = db.execute("SELECT COALESCE(SUM(skill), 0) FROM employees WHERE company_id = ? AND role = 'admin'", (company_id,)).fetchone()[0]
    repair = cfg.NO_TECH_REPAIR_FACTOR if tech == 0 else max(0.25, 1.0 / (1.0 + 0.3 * tech))
    return {"repair_factor": repair, "incident_mult": max(0.4, 1.0 - cfg.ADMIN_INCIDENT_REDUCTION * adm)}


def _pay(db, world, company, cents, category, description):
    cash = db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company["id"],)).fetchone()[0]
    if cents > cash:
        raise StaffError("Not enough cash (need %s, have %s)" % (_money(cents), _money(cash)))
    change_cash(db, company["id"], -cents)
    book(db, world["id"], company["id"], world["tick"], category, -cents, description)


def _gain_xp(db, world, company, emp_id, tick):
    emp = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if emp is None:
        return
    xp = emp["xp"] + 1
    if emp["skill"] < cfg.MAX_SKILL and xp >= cfg.XP_PER_LEVEL * emp["skill"]:
        skill = emp["skill"] + 1
        db.execute("UPDATE employees SET skill = ?, xp = 0, salary_cents_per_tick = ? WHERE id = ?",
                   (skill, salary_for(emp["role"], skill), emp_id))
        add_event(db, world["id"], tick, "promotion", "%s reached skill level %d (higher salary)" % (emp["name"], skill),
                  company_id=company["id"])
    else:
        db.execute("UPDATE employees SET xp = ? WHERE id = ?", (xp, emp_id))


# ---------------------------------------------------------------- admin policy (set by the player)

CATEGORIES = ("capacity", "reliability", "infrastructure", "expansion", "cleanup", "modernize")
PRIORITY_WEIGHT = {0: 0, 1: 1, 2: 3, 3: 8}      # Off, Low, Normal, High
DEFAULT_POLICY = {
    "rack_style": "pure",            # pure = one kind of server per rack, mixed = anything goes
    "focus": "auto",                 # auto | cpu | storage_tb | gpu
    "budget_pct": 50,                # a single plan may cost at most this share of the cash
    "redundancy": "auto",            # new racks: auto (by admin skill) | always | never
    "auto_approve": "off",           # off | cheap (small plans, no new datacenters) | all (within the cost limit)
    "auto_hire": "off",              # off | on: hire from the job market where the company is short of people
    "hire_min_skill": 1,             # auto-hire only takes candidates with at least this skill
    "priorities": {"capacity": 2, "reliability": 2, "infrastructure": 2, "expansion": 1, "cleanup": 2, "modernize": 1},
}
CAT_RESOURCE = {"server_cpu": "cpu", "server_storage": "storage_tb", "server_gpu": "gpu"}
NON_SERVER = ()


def get_policy(db, company_id):
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    row = db.execute("SELECT policy_json FROM admin_policy WHERE company_id = ?", (company_id,)).fetchone()
    if row:
        saved = json.loads(row["policy_json"])
        policy.update({k: v for k, v in saved.items() if k != "priorities"})
        policy["priorities"].update(saved.get("priorities", {}))
    return policy


def set_policy(db, company_id, data):
    if not isinstance(data, dict):
        raise StaffError("Invalid policy")
    policy = get_policy(db, company_id)
    choices = {"rack_style": ("pure", "mixed"), "focus": ("auto", "cpu", "storage_tb", "gpu"),
               "budget_pct": (25, 50, 90), "redundancy": ("auto", "always", "never"),
               "auto_approve": ("off", "cheap", "all"), "auto_hire": ("off", "on"), "hire_min_skill": (1, 2, 3)}
    for key, allowed in choices.items():
        if key in data:
            if data[key] not in allowed or isinstance(data[key], bool):
                raise StaffError("Invalid value for %s" % key)
            policy[key] = data[key]
    for cat, level in (data.get("priorities") or {}).items():
        if cat not in CATEGORIES or level not in (0, 1, 2, 3) or isinstance(level, bool):
            raise StaffError("Invalid priority")
        policy["priorities"][cat] = level
    db.execute("INSERT INTO admin_policy (company_id, policy_json) VALUES (?, ?)"
               " ON CONFLICT(company_id) DO UPDATE SET policy_json = excluded.policy_json", (company_id, json.dumps(policy)))


# ---------------------------------------------------------------- rack design (what admins propose)

def _pick_server(servers, resource, skill):
    if skill >= 4:
        return max(servers, key=lambda h: h["attrs"][resource] / max(1, h["power_w"]))
    if skill == 3:
        return max(servers, key=lambda h: h["attrs"][resource] / h["price_cents"])
    return servers[len(servers) // 2]


def _redundant_wanted(skill, redundancy):
    return {"always": True, "never": False}.get(redundancy, skill >= 3)


def design_extension(rack, hws, resource, skill, redundancy="auto"):
    """Servers for the free space of an existing rack, as long as power, ports and (if present) redundancy hold."""
    servers = sorted((h for h in hws if h["category"] == RESOURCE_CATEGORY[resource]), key=lambda h: h["price_cents"])
    if not servers:
        return None
    server = _pick_server(servers, resource, skill)
    items = list(rack["items"])
    keep_redundant = rk.rack_stats(items)["redundant"] and redundancy != "never" and (skill >= 3 or redundancy == "always")
    added = []
    for n in range(40):
        pos = next((u for u in range(1, cfg.RACK_U - server["u_height"] + 2) if rk.placement_error(items, server, u) is None), None)
        if pos is None:
            break
        trial = items + [{**server, "id": 100000 + n, "u_start": pos}]
        st = rk.rack_stats(trial)
        if st["overload"] or len(st["connected_ids"]) < st["server_count"] or st["load_w"] > 0.95 * st["limit_w"]:
            break
        if keep_redundant and not st["redundant"]:
            break
        items = trial
        added.append({"code": server["code"], "u_start": pos})
    return added or None


def design_redundancy(rack, hws):
    """A second PDU and a second ToR switch for a rack that has only one of them."""
    st = rack["stats"]
    by_code = {h["code"]: h for h in hws}
    pdus = [i for i in rack["items"] if i["category"] == "pdu"]
    tors = [i for i in rack["items"] if i["category"] == "switch_tor"]
    trial = list(rack["items"])
    added = []

    def put(hw):
        for u in range(cfg.RACK_U - hw["u_height"] + 1, 0, -1):
            if rk.placement_error(trial, hw, u) is None:
                trial.append({**hw, "id": 200000 + len(added), "u_start": u})
                added.append({"code": hw["code"], "u_start": u})
                return True
        return False

    if len(pdus) == 1 and st["load_w"] <= pdus[0]["attrs"].get("max_w", 0):
        fits = sorted((h for h in hws if h["category"] == "pdu" and h["attrs"]["max_w"] >= st["load_w"]), key=lambda h: h["price_cents"])
        if fits:
            put(fits[0])
    if len(tors) == 1 and tors[0]["code"] in by_code:
        put(by_code[tors[0]["code"]])
    return added or None


def design_restyle(rack, hws, skill, redundancy):
    """Rack style 'pure': keep the dominant kind of server, replace the others with the dominant kind."""
    servers = [i for i in rack["items"] if i["category"] in CAT_RESOURCE]
    units = {}
    for i in servers:
        units[i["category"]] = units.get(i["category"], 0) + i["u_height"]
    if len(units) < 2:
        return None
    dominant = max(units, key=lambda c: units[c])
    remove = [i for i in servers if i["category"] != dominant]
    gone = {i["id"] for i in remove}
    probe = {**rack, "items": [i for i in rack["items"] if i["id"] not in gone]}
    add = design_extension(probe, hws, CAT_RESOURCE[dominant], skill, redundancy)
    if not add:
        return None
    return {"resource": CAT_RESOURCE[dominant], "remove": remove, "add": add}


def design_power_fix(rack, hws):
    """Replace PDUs that are too small for the load (overload, or no N+1 redundancy although there are two)."""
    st = rack["stats"]
    pdus = [i for i in rack["items"] if i["category"] == "pdu"]
    if not pdus or st["server_count"] == 0 or not (st["overload"] or (len(pdus) >= 2 and not st["power_redundant"])):
        return None
    need = st["load_w"]
    remove = [p for p in pdus if p["attrs"]["max_w"] < need]
    fits = sorted((h for h in hws if h["category"] == "pdu" and h["attrs"]["max_w"] >= need), key=lambda h: h["price_cents"])
    if not remove or not fits:
        return None
    return {"remove": remove, "add": [{"code": fits[0]["code"], "u_start": p["u_start"]} for p in remove]}


def design_modernize(rack, hws, skill, redundancy):
    """Swap old servers for denser models of the same size, as long as power, ports and redundancy hold."""
    servers = [i for i in rack["items"] if i["category"] in CAT_RESOURCE]
    if not servers:
        return None
    keep_redundant = rack["stats"]["redundant"] and redundancy != "never"
    items = list(rack["items"])
    removed, added = [], []
    for old in sorted(servers, key=lambda i: i["attrs"].get(CAT_RESOURCE[i["category"]], 0)):
        key = CAT_RESOURCE[old["category"]]
        better = [h for h in hws if h["category"] == old["category"] and h["u_height"] == old["u_height"]
                  and h["attrs"][key] >= 1.4 * old["attrs"].get(key, 0)]
        if not better or len(removed) >= 12:
            continue
        new = max(better, key=lambda h: h["attrs"][key])
        trial = [i for i in items if i["id"] != old["id"]] + [{**new, "id": 300000 + len(added), "u_start": old["u_start"]}]
        st = rk.rack_stats(trial)
        if st["overload"] or len(st["connected_ids"]) < st["server_count"] or st["load_w"] > 0.95 * st["limit_w"]:
            continue
        if keep_redundant and not st["redundant"]:
            continue
        items = trial
        removed.append(old)
        added.append({"code": new["code"], "u_start": old["u_start"]})
    return {"remove": removed, "add": added} if removed else None


def design_rack(hws, resource, skill, redundancy="auto"):
    """Rule-based rack layout. Higher skill = better server choice, redundancy, fans and cabling.

    Returns a layout [{code, u_start}] or None. Gear sits at the top, servers fill from the bottom.
    """
    by_code = {h["code"]: h for h in hws}
    servers = sorted((h for h in hws if h["category"] == RESOURCE_CATEGORY[resource]), key=lambda h: h["price_cents"])
    if not servers or "pdu_7k2" not in by_code:
        return None
    server = _pick_server(servers, resource, skill)
    redundant = _redundant_wanted(skill, redundancy)
    tor = by_code["tor_48" if skill >= 2 else "tor_24"]
    n_pdu, n_tor = (2, 2) if redundant else (1, 1)
    top = [by_code["pdu_7k2"]] * n_pdu + [tor] * n_tor
    if skill >= 4:
        top += [by_code["fan_1u"], by_code["cable_1u"]]
    top_u = sum(h["u_height"] for h in top)
    overhead_w = sum(h["power_w"] for h in top)
    ports = tor["ports"] * n_tor
    target_w = 7000                      # keeps N+1 redundancy valid with 2 x 7.2 kW PDUs
    nic = server["attrs"].get("nic", 1)
    n = 0
    while True:
        m = n + 1
        if (m * server["u_height"] + top_u > cfg.RACK_U or overhead_w + m * server["power_w"] > target_w
                or m * nic > ports):
            break
        n = m
    if n == 0:
        return None
    layout = []
    u = 1
    for _ in range(n):
        layout.append({"code": server["code"], "u_start": u})
        u += server["u_height"]
    u = cfg.RACK_U
    for h in top:
        layout.append({"code": h["code"], "u_start": u - h["u_height"] + 1})
        u -= h["u_height"]
    if skill >= 4:   # blanking panels over the free space reduce heat recirculation
        free = u - (n * server["u_height"])
        for k in range(max(0, min(free, 6))):
            layout.append({"code": "blank_1u", "u_start": u - k})
    return layout


def _layout_summary(layout, hws):
    by_code = {h["code"]: h for h in hws}
    items = []
    stats_items = []
    counts = {}
    for i, e in enumerate(layout):
        counts[e["code"]] = counts.get(e["code"], 0) + 1
        hw = by_code[e["code"]]
        stats_items.append({**hw, "id": i + 1, "u_start": e["u_start"]})
    for code, count in counts.items():
        items.append({"code": code, "name": by_code[code]["name"], "count": count})
    return items, rk.rack_stats(stats_items), sum(by_code[e["code"]]["price_cents"] for e in layout)


def _count_items(layout, by_code):
    counts = {}
    for e in layout:
        counts[e["code"]] = counts.get(e["code"], 0) + 1
    return [{"code": c, "name": by_code[c]["name"], "count": n} for c, n in counts.items()]


# ---------------------------------------------------------------- build times

def _ticks_rack(n_items):
    return int(cfg.BUILD_TICKS_RACK_BASE + cfg.BUILD_TICKS_PER_ITEM * n_items)


def _ticks_extend(n_items):
    return int(cfg.BUILD_TICKS_EXTEND_BASE + cfg.BUILD_TICKS_PER_ITEM * n_items)


def _ticks_rebuild(n_items):
    return int(cfg.BUILD_TICKS_REBUILD_BASE + cfg.BUILD_TICKS_REBUILD_PER_ITEM * n_items)


# ---------------------------------------------------------------- proposals

def _insert_proposal(db, world, company, admin, tick, kind, title, plan, summary, cost, est):
    db.execute(
        "INSERT INTO proposals (company_id, admin_id, kind, title, plan_json, summary_json, cost_cents, est_ticks,"
        " created_tick, expires_tick) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (company["id"], admin["id"], kind, title, json.dumps(plan), json.dumps(summary), cost, est, tick,
         tick + cfg.PROPOSAL_LIFETIME_TICKS))
    add_event(db, world["id"], tick, "proposal", "%s proposes: %s" % (admin["name"], title), company_id=company["id"])
    _gain_xp(db, world, company, admin["id"], tick)


def _planned_keys(db, company_id):
    """What is already proposed or being built, so admins do not repeat themselves."""
    keys = set()
    for table, status in (("proposals", "('open')"), ("work_orders", "('queued', 'in_progress')")):
        for row in db.execute("SELECT plan_json FROM %s WHERE company_id = ? AND status IN %s" % (table, status), (company_id,)):
            plan = json.loads(row["plan_json"])
            if plan["type"] == "upgrade":
                keys.add(("upgrade", plan["dc_id"], plan["code"]))
            elif plan["type"] == "new_rack":
                keys.add(("new_rack", plan["dc_id"]))
            elif plan["type"] in ("extend_rack", "add_redundancy", "rebuild_rack"):
                keys.add(("rack", plan["rack_id"]))   # one pending change per rack
            else:
                keys.add(("new_datacenter", plan["region_id"]))
    return keys


def _cash(db, company_id):
    return db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company_id,)).fetchone()[0]


def _affordable(c, cost):
    return cost <= _cash(c["db"], c["company"]["id"]) * c["policy"]["budget_pct"] / 100.0


def _racks(c):
    return [(dc, r) for dc in c["dcs"] for r in dc["racks"] if r["status"] == "ok" and ("rack", r["id"]) not in c["keys"]]


def _rate(res):
    return cfg.KIND_RATE_MULT["ai"] if res == "gpu" else 1.0


def _propose_upgrade(c):
    admin, hws, keys = c["admin"], c["hws"], c["keys"]
    by_code = {h["code"]: h for h in hws}
    threshold = 1.0 if admin["skill"] == 1 else 0.9
    for dc in c["dcs"]:
        agg_ports = sum(e["qty"] * e["ports"] for e in dc["equip"].values() if e["category"] == "dc_agg")
        feed_kw = dc["power_capacity_kw"] + sum(e["qty"] * e["attrs"].get("power_kw", 0) for e in dc["equip"].values())
        uplinks = sum(r["stats"]["uplinks_needed"] for r in dc["racks"] if r["stats"]["tor_count"])
        cases = []
        if dc["cooling_cap_kw"] > 0 and dc["heat_kw"] / dc["cooling_cap_kw"] > threshold:
            excess = dc["heat_kw"] - dc["cooling_cap_kw"] * 0.8
            cases.append(("dc_chiller" if excess > 40 else "dc_crac", "Heat is at %d %% of the cooling capacity." % (100 * dc["heat_kw"] / dc["cooling_cap_kw"])))
        if feed_kw > 0 and dc["facility_kw"] / feed_kw > threshold:
            cases.append(("dc_feed_big" if dc["facility_kw"] > feed_kw + 50 else "dc_feed", "Power use is at %d %% of the grid connection." % (100 * dc["facility_kw"] / feed_kw)))
        if uplinks > 0 and uplinks > agg_ports * (1.0 if admin["skill"] == 1 else 0.85):
            cases.append(("dc_agg", "Racks need %d uplink ports, only %d are available." % (uplinks, agg_ports)))
        for code, why in cases:
            hw = by_code.get(code) or by_code.get({"dc_chiller": "dc_crac", "dc_feed_big": "dc_feed"}.get(code))   # locked? use the basic variant
            if hw is None or not _affordable(c, hw["price_cents"]):
                continue
            code = hw["code"]
            if ("upgrade", dc["id"], code) in keys:
                continue
            plan = {"type": "upgrade", "dc_id": dc["id"], "code": code, "qty": 1}
            summary = {"lines": [why, "Installs: 1x %s" % hw["name"]], "items": [], "adds": {}, "revenue_cents_per_tick": 0}
            _insert_proposal(c["db"], c["world"], c["company"], admin, c["tick"], "upgrade", "Add %s to %s" % (hw["name"], dc["name"]),
                             plan, summary, hw["price_cents"], cfg.BUILD_TICKS_UPGRADE.get(code, 30))
            return True
    return False


def _gaps(c):
    """Regions and resources where open customer offers exceed what we can serve, biggest gap first."""
    db, world, dcs, cap = c["db"], c["world"], c["dcs"], c["cap"]
    focus = c["policy"]["focus"]
    gaps = []
    for row in db.execute("SELECT region_id, resource, SUM(units) AS u, COUNT(*) AS n FROM contracts"
                          " WHERE world_id = ? AND status = 'offered' GROUP BY region_id, resource", (world["id"],)):
        rid = row["region_id"]
        if not any(dc["region_id"] == rid for dc in dcs) or (focus != "auto" and row["resource"] != focus):
            continue
        free = max(0.0, cap.get(rid, {}).get(row["resource"], {}).get("free", 0.0))
        gap_eq = (row["u"] - free) * cfg.UNIT_WEIGHT[row["resource"]]
        if gap_eq >= 20:
            gaps.append((gap_eq, rid, row["resource"], row["n"], row["u"], free))
    if not gaps and focus != "auto" and c["admin"]["skill"] >= 2:
        # The player wants more of one resource: invest even without open offers where customers are unserved.
        for dc in dcs:
            rid = dc["region_id"]
            free_demand = c["info"][rid]["free"]
            free = max(0.0, cap.get(rid, {}).get(focus, {}).get("free", 0.0))
            if free_demand > 1000 and free * cfg.UNIT_WEIGHT[focus] < 200:
                gaps.append((min(500.0, free_demand * 0.05), rid, focus, 0, 0.0, free))
    gaps.sort(reverse=True)
    return gaps


def _propose_extend(c):
    db, admin, hws = c["db"], c["admin"], c["hws"]
    by_code = {h["code"]: h for h in hws}
    pure = c["policy"]["rack_style"] == "pure"
    for _, rid, res, n_offers, units, free in _gaps(c):
        racks = [(dc, r) for dc, r in _racks(c) if dc["region_id"] == rid and r["stats"]["pdu_count"] and r["stats"]["tor_count"] and r["stats"]["free_u"] >= 1]
        if pure:   # only racks that already hold this kind of server (or nothing)
            racks = [(dc, r) for dc, r in racks if all(i["category"] in (RESOURCE_CATEGORY[res], *NON_SERVER) or not i["category"].startswith("server_") for i in r["items"])]
        racks.sort(key=lambda x: -x[1]["stats"]["free_u"])
        for dc, rack in racks:
            add = design_extension(rack, hws, res, admin["skill"], c["policy"]["redundancy"])
            if not add:
                continue
            cost = sum(by_code[a["code"]]["price_cents"] for a in add)
            if not _affordable(c, cost):
                continue
            server = by_code[add[0]["code"]]
            gained = len(add) * server["attrs"][res]
            why = ("Why: %d open offers ask for %s %s, you have %s free." % (n_offers, "{:,.0f}".format(units), RESOURCE_UNIT[res], "{:,.0f}".format(free))
                   if n_offers else "Why: customers in this region are unserved and you want more %s." % RESOURCE_UNIT[res])
            summary = {
                "lines": [why, "%s has free space: add %d more servers without touching the existing setup." % (rack["name"], len(add)),
                          "Adds %s %s." % ("{:,.0f}".format(gained), RESOURCE_UNIT[res])],
                "items": [{"code": server["code"], "name": server["name"], "count": len(add)}], "adds": {res: gained},
                "revenue_cents_per_tick": int(gained * cfg.UNIT_WEIGHT[res] * cfg.BASE_RATE_CENTS * _rate(res)),
            }
            plan = {"type": "extend_rack", "dc_id": dc["id"], "rack_id": rack["id"], "slot": rack["slot"], "layout": add}
            _insert_proposal(db, c["world"], c["company"], admin, c["tick"], "extend_rack",
                             "Add %d x %s to %s (%s)" % (len(add), server["name"], rack["name"], dc["name"]), plan, summary, cost, _ticks_extend(len(add)))
            return True
    return False


def _propose_rack(c):
    db, admin, hws, keys = c["db"], c["admin"], c["hws"], c["keys"]
    by_code = {h["code"]: h for h in hws}
    for _, rid, res, n_offers, units, free in _gaps(c):
        candidates = [dc for dc in c["dcs"] if dc["region_id"] == rid and len(dc["racks"]) < dc["max_racks"] and ("new_rack", dc["id"]) not in keys]
        if not candidates:
            continue
        dc = max(candidates, key=lambda d: d["max_racks"] - len(d["racks"]))
        layout = design_rack(hws, res, admin["skill"], c["policy"]["redundancy"])
        if not layout:
            continue
        items, stats, items_cost = _layout_summary(layout, hws)
        cost = cfg.RACK_SHELL_CENTS + items_cost
        if not _affordable(c, cost):
            continue
        region = c["regions"][rid]
        why = ("Why: %d open offers ask for %s %s, you have %s free." % (n_offers, "{:,.0f}".format(units), RESOURCE_UNIT[res], "{:,.0f}".format(free))
               if n_offers else "Why: customers in %s are unserved and you want more %s." % (region["name"], RESOURCE_UNIT[res]))
        summary = {
            "lines": [why,
                      "Adds %s %s and uses %.1f kW." % ("{:,.0f}".format(stats[res]), RESOURCE_UNIT[res], stats["load_w"] / 1000),
                      "Redundant power and network: %s." % ("yes" if stats["redundant"] else "no (cheaper, riskier)")],
            "items": items, "adds": {res: stats[res]},
            "revenue_cents_per_tick": int(stats[res] * cfg.UNIT_WEIGHT[res] * cfg.BASE_RATE_CENTS * _rate(res)),
        }
        plan = {"type": "new_rack", "dc_id": dc["id"], "layout": layout}
        _insert_proposal(db, c["world"], c["company"], admin, c["tick"], "new_rack",
                         "%s rack for %s (%s)" % (RESOURCE_LABEL[res], region["name"], dc["name"]), plan, summary, cost, _ticks_rack(len(layout)))
        return True
    return False


def _propose_redundancy(c):
    admin, hws = c["admin"], c["hws"]
    if admin["skill"] < 3:
        return False
    by_code = {h["code"]: h for h in hws}
    for dc, rack in _racks(c):
        st = rack["stats"]
        if st["server_count"] == 0 or st["redundant"]:
            continue
        add = design_redundancy(rack, hws)
        if not add:
            continue
        cost = sum(by_code[a["code"]]["price_cents"] for a in add)
        if not _affordable(c, cost):
            continue
        what = [w for w, missing in (("a second PDU", st["pdu_count"] < 2), ("a second ToR switch", st["tor_count"] < 2)) if missing]
        summary = {
            "lines": ["%s has no redundancy: if its PDU or switch fails, the whole rack goes offline." % rack["name"],
                      "Adds %s. Redundant racks absorb failures and can serve premium contracts." % " and ".join(what)],
            "items": _count_items(add, by_code), "adds": {}, "revenue_cents_per_tick": 0,
        }
        plan = {"type": "add_redundancy", "dc_id": dc["id"], "rack_id": rack["id"], "slot": rack["slot"], "layout": add}
        _insert_proposal(c["db"], c["world"], c["company"], admin, c["tick"], "add_redundancy", "Add redundancy to %s (%s)" % (rack["name"], dc["name"]),
                         plan, summary, cost, _ticks_extend(len(add)))
        return True
    return False


def _rebuild_proposal(c, dc, rack, kind_title, why_lines, design, reason):
    """Shared by restyle / power fix / modernize: sell some devices, mount others."""
    by_code = {h["code"]: h for h in c["hws"]}
    removed = design["remove"]
    cost = sum(by_code[a["code"]]["price_cents"] for a in design["add"])
    refund = int(sum(i["price_cents"] for i in removed) * cfg.SELL_BACK_RATIO)
    if not _affordable(c, cost):
        return False
    summary = {
        "lines": [*why_lines, "The old hardware is sold for about $%s. The rack is offline for %d hours at the end of the work." % (
            "{:,.0f}".format(refund / 100), cfg.MAINTENANCE_DOWNTIME_TICKS)],
        "items": _count_items(design["add"], by_code), "adds": {}, "revenue_cents_per_tick": 0,
        "removes": [{"name": n, "count": k} for n, k in _group_names(removed)],
    }
    plan = {"type": "rebuild_rack", "dc_id": dc["id"], "rack_id": rack["id"], "slot": rack["slot"], "reason": reason,
            "remove": [i["id"] for i in removed], "layout": design["add"]}
    _insert_proposal(c["db"], c["world"], c["company"], c["admin"], c["tick"], "rebuild_rack", kind_title, plan, summary, cost,
                     _ticks_rebuild(len(removed) + len(design["add"])))
    return True


def _group_names(items):
    counts = {}
    for i in items:
        counts[i["name"]] = counts.get(i["name"], 0) + 1
    return list(counts.items())


def _propose_restyle(c):
    if c["policy"]["rack_style"] != "pure" or c["admin"]["skill"] < 2:
        return False
    for dc, rack in _racks(c):
        design = design_restyle(rack, c["hws"], c["admin"]["skill"], c["policy"]["redundancy"])
        if not design:
            continue
        label = RESOURCE_LABEL[design["resource"]]
        why = ["%s mixes different kinds of servers. Your rack style is one kind per rack." % rack["name"],
               "Removes %d servers of the other kinds and fills the space with %s servers." % (len(design["remove"]), label.lower())]
        if _rebuild_proposal(c, dc, rack, "Rebuild %s as a %s rack (%s)" % (rack["name"], label.lower(), dc["name"]), why, design, "restyle"):
            return True
    return False


def _propose_power_fix(c):
    if c["admin"]["skill"] < 2:
        return False
    for dc, rack in _racks(c):
        design = design_power_fix(rack, c["hws"])
        if not design:
            continue
        why = ["%s has PDUs that are too small for its %.1f kW load: it %s." % (
            rack["name"], rack["stats"]["load_w"] / 1000, "trips its breaker" if rack["stats"]["overload"] else "cannot survive the loss of a PDU"),
            "Replaces %d PDU(s) with a bigger model." % len(design["remove"])]
        if _rebuild_proposal(c, dc, rack, "Replace small PDUs in %s (%s)" % (rack["name"], dc["name"]), why, design, "power"):
            return True
    return False


def _propose_modernize(c):
    if c["admin"]["skill"] < 3:
        return False
    for dc, rack in _racks(c):
        design = design_modernize(rack, c["hws"], c["admin"]["skill"], c["policy"]["redundancy"])
        if not design:
            continue
        old = sum(i["attrs"].get(CAT_RESOURCE[i["category"]], 0) for i in design["remove"])
        by_code = {h["code"]: h for h in c["hws"]}
        new = sum(by_code[a["code"]]["attrs"][CAT_RESOURCE[by_code[a["code"]]["category"]]] for a in design["add"])
        why = ["%s runs old servers. Denser models fit into the same space and power budget." % rack["name"],
               "Replaces %d servers: capacity goes from %s to %s." % (len(design["remove"]), "{:,.0f}".format(old), "{:,.0f}".format(new))]
        if _rebuild_proposal(c, dc, rack, "Modernize servers in %s (%s)" % (rack["name"], dc["name"]), why, design, "modernize"):
            return True
    return False


def _propose_datacenter(c):
    admin, dcs, keys, regions, info = c["admin"], c["dcs"], c["keys"], c["regions"], c["info"]
    if admin["skill"] < 3:
        return False
    full = all(len(dc["racks"]) >= dc["max_racks"] - 2 for dc in dcs)
    cash = _cash(c["db"], c["company"]["id"])
    if not full and not (cash > 6 * cfg.DC_BUILD_BASE_CENTS and c["rng"].random() < 0.3):
        return False
    best = None
    for rid, region in regions.items():
        mine = sum(1 for dc in dcs if dc["region_id"] == rid)
        cost = builder.dc_cost(region)
        if mine >= cfg.DC_MAX_PER_REGION or ("new_datacenter", rid) in keys or cost * 1.3 > cash or not _affordable(c, cost):
            continue
        d = info[rid]
        score = (d["free"] / max(1.0, d["demand"])) * region["demand_index"] / region["land_cost_index"] * (0.5 if mine else 1.0)
        if best is None or score > best[0]:
            best = (score, rid, region, cost, mine, d)
    if best is None:
        return False
    _, rid, region, cost, mine, d = best
    summary = {
        "lines": ["Why: %s units of customer demand in %s are unserved (%d %% of the market)." % (
            "{:,.0f}".format(d["free"]), region["name"], 100 * d["free"] / max(1.0, d["demand"])),
            "A new datacenter has 20 rack slots, base cooling 60 kW and one aggregation switch.",
            "Electricity: %.0f c/kWh, climate %.0f degrees C." % (region["power_price_cents_kwh"], region["avg_temp_c"])],
        "items": [], "adds": {}, "revenue_cents_per_tick": 0,
    }
    _insert_proposal(c["db"], c["world"], c["company"], admin, c["tick"], "new_datacenter", "New datacenter in %s" % region["name"],
                     {"type": "new_datacenter", "region_id": rid, "name": "%s DC %d" % (region["name"], mine + 1)}, summary, cost, cfg.BUILD_TICKS_DC)
    return True


GENERATORS = {
    "capacity": lambda c: _propose_extend(c) or _propose_rack(c),
    "reliability": lambda c: _propose_redundancy(c) or _propose_power_fix(c),
    "infrastructure": _propose_upgrade,
    "expansion": _propose_datacenter,
    "cleanup": _propose_restyle,
    "modernize": _propose_modernize,
}


def _ordered_categories(policy, rng):
    """Random order of the categories, weighted by the player's priorities (Off = never)."""
    pool = [(cat, PRIORITY_WEIGHT[policy["priorities"][cat]]) for cat in CATEGORIES if PRIORITY_WEIGHT[policy["priorities"][cat]] > 0]
    order = []
    while pool:
        pick = rng.choices(pool, [w for _, w in pool])[0]
        order.append(pick[0])
        pool.remove(pick)
    return order


def _admin_ready(db, admin, tick):
    """Every admin suggests at most one plan per PROPOSAL_INTERVAL_TICKS; newcomers need a first delay."""
    last = db.execute("SELECT MAX(created_tick) FROM proposals WHERE admin_id = ?", (admin["id"],)).fetchone()[0]
    due = last + cfg.PROPOSAL_INTERVAL_TICKS if last is not None else admin["hired_tick"] + cfg.FIRST_PROPOSAL_DELAY_TICKS
    return tick >= due


def generate_proposals(db, world, company, tick, rng, admins):
    import sim   # local import: sim imports this module
    ready = [a for a in admins if _admin_ready(db, a, tick)]
    open_n = db.execute("SELECT COUNT(*) FROM proposals WHERE company_id = ? AND status = 'open'", (company["id"],)).fetchone()[0]
    room = cfg.MAX_OPEN_PROPOSALS - open_n
    if room <= 0 or not ready:
        return 0
    dcs = sim.load_assets(db, company["id"])
    if not dcs:
        return 0
    for dc in dcs:
        dc["max_racks"] = cfg.DC_MAX_RACKS
        for rack in dc["racks"]:
            rack["stats"] = rk.rack_stats(rack["items"])
    done = research.done_set(db, company["id"])
    hws = [h for h in (rk.hardware_from_row(r) for r in db.execute("SELECT * FROM hardware_types")) if research.hw_allowed(h["code"], done)]
    contracts = db.execute("SELECT * FROM contracts WHERE company_id = ? AND status = 'active'", (company["id"],)).fetchall()
    c = {
        "db": db, "world": world, "company": company, "tick": tick, "rng": rng, "dcs": dcs, "hws": hws,
        "cap": capacity.region_capacity(dcs, contracts), "policy": get_policy(db, company["id"]),
        "regions": {r["id"]: r for r in db.execute("SELECT * FROM regions WHERE world_id = ?", (world["id"],))},
        "info": market.compute_market(db, world["id"], tick, persist=False), "keys": _planned_keys(db, company["id"]),
    }
    created = 0
    rng.shuffle(ready)
    for admin in ready:
        if created >= room:
            break
        c["admin"] = admin
        for cat in _ordered_categories(c["policy"], rng):
            if GENERATORS[cat](c):
                created += 1
                c["keys"] = _planned_keys(db, company["id"])
                break
    return created


def approve(db, world, company, proposal_id):
    p = db.execute("SELECT * FROM proposals WHERE id = ? AND company_id = ? AND status = 'open'", (proposal_id, company["id"])).fetchone()
    if p is None:
        raise StaffError("Proposal is no longer open")
    if p["expires_tick"] < world["tick"]:
        db.execute("UPDATE proposals SET status = 'expired' WHERE id = ?", (p["id"],))
        raise StaffError("Proposal has expired")
    plan = json.loads(p["plan_json"])
    _validate_plan(db, company, plan)
    category = "construction" if plan["type"] == "new_datacenter" else "hardware"
    _pay(db, world, company, p["cost_cents"], category, p["title"])
    cur = db.execute(
        "INSERT INTO work_orders (company_id, proposal_id, kind, title, plan_json, cost_cents, total_ticks, created_tick)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (company["id"], p["id"], p["kind"], p["title"], p["plan_json"], p["cost_cents"], p["est_ticks"], world["tick"]))
    db.execute("UPDATE proposals SET status = 'approved' WHERE id = ?", (p["id"],))
    return cur.lastrowid


def reject(db, company, proposal_id):
    cur = db.execute("UPDATE proposals SET status = 'rejected' WHERE id = ? AND company_id = ? AND status = 'open'", (proposal_id, company["id"]))
    if cur.rowcount == 0:
        raise StaffError("Proposal is no longer open")


def _validate_plan(db, company, plan):
    if plan["type"] in ("extend_rack", "add_redundancy", "rebuild_rack"):
        rack = db.execute("SELECT r.id FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE r.id = ? AND d.company_id = ?",
                          (plan["rack_id"], company["id"])).fetchone()
        if rack is None:
            raise StaffError("The rack no longer exists")
    if plan["type"] in ("new_rack", "upgrade"):
        dc = db.execute("SELECT id FROM datacenters WHERE id = ? AND company_id = ? AND status = 'active'", (plan["dc_id"], company["id"])).fetchone()
        if dc is None:
            raise StaffError("The datacenter no longer exists")
        if plan["type"] == "new_rack" and builder.free_slot(db, plan["dc_id"]) is None:
            raise StaffError("The datacenter is full")


# ---------------------------------------------------------------- work orders (technicians)

def _execute_plan(db, world, company, plan):
    if plan["type"] == "new_rack":
        dc = db.execute("SELECT * FROM datacenters WHERE id = ? AND company_id = ?", (plan["dc_id"], company["id"])).fetchone()
        if dc is None:
            raise builder.BuildError("The datacenter no longer exists")
        slot = builder.free_slot(db, dc["id"])
        if slot is None:
            raise builder.BuildError("The datacenter is full")
        builder.insert_rack(db, world, dc["id"], "Rack %d" % (slot + 1), slot, plan["layout"])
    elif plan["type"] in ("extend_rack", "add_redundancy", "rebuild_rack"):
        rack = db.execute("SELECT r.id FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE r.id = ? AND d.company_id = ?",
                          (plan["rack_id"], company["id"])).fetchone()
        if rack is None:
            raise builder.BuildError("The rack no longer exists")
        if plan["type"] == "rebuild_rack":
            refund = builder.rebuild(db, rack["id"], plan["remove"], plan["layout"])
            db.execute("UPDATE racks SET status = 'down', down_until_tick = ?, down_reason = 'maintenance' WHERE id = ? AND status = 'ok'",
                       (world["tick"] + cfg.MAINTENANCE_DOWNTIME_TICKS, rack["id"]))
            if refund:
                change_cash(db, company["id"], refund)
                book(db, world["id"], company["id"], world["tick"], "refund", refund, "Sold old hardware")
        else:
            builder.append_layout(db, rack["id"], plan["layout"])
    elif plan["type"] == "upgrade":
        dc = db.execute("SELECT id FROM datacenters WHERE id = ? AND company_id = ?", (plan["dc_id"], company["id"])).fetchone()
        if dc is None:
            raise builder.BuildError("The datacenter no longer exists")
        builder.add_dc_equipment(db, dc["id"], plan["code"], plan.get("qty", 1))
    else:
        region = db.execute("SELECT * FROM regions WHERE id = ? AND world_id = ?", (plan["region_id"], world["id"])).fetchone()
        if region is None:
            raise builder.BuildError("Region not found")
        builder.insert_datacenter(db, world, company["id"], region, plan["name"], builder.dc_cost(region))


def process_orders(db, world, company, tick, speed_bonus=0.0):
    """Assign queued orders to idle technicians and advance the work in progress."""
    cid = company["id"]
    world = dict(world, tick=tick)   # catch-up passes the world row of the first tick; use the current one
    orders = db.execute("SELECT * FROM work_orders WHERE company_id = ? AND status IN ('queued', 'in_progress') ORDER BY id", (cid,)).fetchall()
    if not orders:
        return
    techs = db.execute("SELECT * FROM employees WHERE company_id = ? AND role = 'technician' ORDER BY skill DESC, id", (cid,)).fetchall()
    busy = {o["employee_id"] for o in orders if o["status"] == "in_progress" and o["employee_id"]}
    idle = [t for t in techs if t["id"] not in busy]
    for o in orders:
        if o["status"] == "queued" and idle:
            t = idle.pop(0)
            db.execute("UPDATE work_orders SET status = 'in_progress', employee_id = ? WHERE id = ?", (t["id"], o["id"]))
            db.execute("UPDATE employees SET status = 'working', order_id = ? WHERE id = ?", (o["id"], t["id"]))
    working = db.execute(
        "SELECT o.*, e.skill AS e_skill, e.name AS e_name FROM work_orders o JOIN employees e ON e.id = o.employee_id"
        " WHERE o.company_id = ? AND o.status = 'in_progress'", (cid,)).fetchall()
    for o in working:
        progress = o["progress"] + (1.0 + cfg.TECH_SPEED_PER_SKILL * (o["e_skill"] - 1)) * (1.0 + speed_bonus)
        if progress < o["total_ticks"]:
            db.execute("UPDATE work_orders SET progress = ? WHERE id = ?", (progress, o["id"]))
            continue
        db.execute("SAVEPOINT plan")
        try:
            _execute_plan(db, world, company, json.loads(o["plan_json"]))
            db.execute("RELEASE plan")
        except builder.BuildError as exc:
            db.execute("ROLLBACK TO plan")
            db.execute("RELEASE plan")
            db.execute("UPDATE work_orders SET status = 'failed', progress = ? WHERE id = ?", (o["total_ticks"], o["id"]))
            change_cash(db, cid, o["cost_cents"])
            book(db, world["id"], cid, tick, "refund", o["cost_cents"], "Failed: " + o["title"])
            add_event(db, world["id"], tick, "work_failed", "%s could not finish '%s': %s. Money refunded." % (o["e_name"], o["title"], exc), company_id=cid)
        else:
            db.execute("UPDATE work_orders SET status = 'done', progress = ? WHERE id = ?", (o["total_ticks"], o["id"]))
            add_event(db, world["id"], tick, "work_done", "%s finished: %s" % (o["e_name"], o["title"]), company_id=cid)
            _gain_xp(db, world, company, o["employee_id"], tick)
        db.execute("UPDATE employees SET status = 'idle', order_id = NULL WHERE id = ?", (o["employee_id"],))


def auto_accept_enabled(db, company_id):
    row = db.execute("SELECT auto_accept FROM company_settings WHERE company_id = ?", (company_id,)).fetchone()
    return True if row is None else bool(row["auto_accept"])


def set_auto_accept(db, company_id, enabled):
    db.execute("INSERT INTO company_settings (company_id, auto_accept) VALUES (?, ?)"
               " ON CONFLICT(company_id) DO UPDATE SET auto_accept = excluded.auto_accept", (company_id, 1 if enabled else 0))


def sales_accept(db, world, company, tick):
    """Sales staff signs open offers the company can really serve (never overbooks), best price per unit first."""
    import sim   # local import: sim imports this module
    sales = db.execute("SELECT * FROM employees WHERE company_id = ? AND role = 'sales' ORDER BY id", (company["id"],)).fetchall()
    if not sales or not auto_accept_enabled(db, company["id"]):
        return 0
    budget = sum(e["skill"] for e in sales)
    dcs = sim.load_assets(db, company["id"])
    if not dcs:
        return 0
    for dc in dcs:
        for rack in dc["racks"]:
            rack["stats"] = rk.rack_stats(rack["items"])
    active = db.execute("SELECT * FROM contracts WHERE company_id = ? AND status = 'active'", (company["id"],)).fetchall()
    cap = capacity.region_capacity(dcs, active)
    active_n = len(active)
    offers = db.execute("SELECT * FROM contracts WHERE world_id = ? AND status = 'offered' ORDER BY revenue_cents_per_tick * 1.0 / units_eq DESC, id",
                        (world["id"],)).fetchall()
    signed = 0
    for o in offers:
        if signed >= budget or active_n >= cfg.MAX_ACTIVE_CONTRACTS:
            break
        c = cap.get(o["region_id"])
        if c is None or c[o["resource"]]["red_free" if o["premium"] else "free"] < o["units"]:
            continue
        seller = sales[signed % len(sales)]
        rate = int(o["revenue_cents_per_tick"] * (1.0 + cfg.SALES_RATE_BONUS_PER_SKILL * seller["skill"]))
        db.execute("UPDATE contracts SET company_id = ?, status = 'active', start_tick = ?, end_tick = ?, sla_fail_streak = 0,"
                   " revenue_cents_per_tick = ? WHERE id = ?", (company["id"], tick, tick + o["duration_ticks"], rate, o["id"]))
        c[o["resource"]]["free"] -= o["units"]
        if o["premium"]:
            c[o["resource"]]["red_free"] -= o["units"]
        else:
            c[o["resource"]]["red_free"] = min(c[o["resource"]]["red_free"], c[o["resource"]]["free"])
        signed += 1
        active_n += 1
        add_event(db, world["id"], tick, "sales_signed", "%s signed '%s' (%s/h)" % (seller["name"], o["name"], "{:,.2f}".format(rate / 100)),
                  company_id=company["id"], region_id=o["region_id"])
        _gain_xp(db, world, company, seller["id"], tick)
    if signed:
        market.compute_market(db, world["id"], tick, persist=True)
    return signed


def run_auto_approve(db, world, company, tick=None):
    """Approve open plans automatically as the player's policy allows (cash and validity are still checked)."""
    policy = get_policy(db, company["id"])
    mode = policy["auto_approve"]
    if mode == "off":
        return 0
    world = dict(world, tick=world["tick"] if tick is None else tick)
    approved = 0
    for p in db.execute("SELECT * FROM proposals WHERE company_id = ? AND status = 'open' ORDER BY id", (company["id"],)).fetchall():
        cash = _cash(db, company["id"])
        if mode == "cheap":
            allowed = p["cost_cents"] <= 0.10 * cash and p["kind"] != "new_datacenter"
        else:
            allowed = p["cost_cents"] <= cash * policy["budget_pct"] / 100.0
        if not allowed:
            continue
        try:
            approve(db, world, company, p["id"])
        except StaffError:
            continue
        add_event(db, world["id"], world["tick"], "auto_approved", "Auto-approved: %s ($%s)" % (p["title"], "{:,.0f}".format(p["cost_cents"] / 100)),
                  company_id=company["id"])
        approved += 1
    return approved


def daily(db, world, company, tick, rng):
    ensure_candidates(db, company["id"], tick, rng)
    run_auto_hire(db, world, company, tick)
    sales_accept(db, world, company, tick)
    db.execute("UPDATE proposals SET status = 'expired' WHERE company_id = ? AND status = 'open' AND expires_tick < ?", (company["id"], tick))
    db.execute("DELETE FROM work_orders WHERE company_id = ? AND status IN ('done', 'failed') AND created_tick < ?", (company["id"], tick - 24 * 10))
    admins = db.execute("SELECT * FROM employees WHERE company_id = ? AND role = 'admin'", (company["id"],)).fetchall()
    generate_proposals(db, world, company, tick, rng, admins)
    run_auto_approve(db, world, company, tick)


# ---------------------------------------------------------------- client state

def team_state(db, company, tick):
    emps = db.execute("SELECT e.*, o.title AS order_title, o.plan_json AS order_plan, o.kind AS order_kind FROM employees e LEFT JOIN work_orders o ON o.id = e.order_id"
                      " WHERE e.company_id = ? ORDER BY e.role, e.skill DESC, e.id", (company["id"],)).fetchall()
    cands = db.execute("SELECT * FROM candidates WHERE company_id = ? AND expires_tick >= ? ORDER BY role, skill DESC", (company["id"], tick)).fetchall()
    props = db.execute("SELECT p.*, e.name AS admin_name FROM proposals p LEFT JOIN employees e ON e.id = p.admin_id"
                       " WHERE p.company_id = ? AND p.status = 'open' ORDER BY p.id DESC", (company["id"],)).fetchall()
    orders = db.execute("SELECT o.*, e.name AS e_name FROM work_orders o LEFT JOIN employees e ON e.id = o.employee_id"
                        " WHERE o.company_id = ? AND o.status IN ('queued', 'in_progress') ORDER BY o.id", (company["id"],)).fetchall()
    eff = effects(db, company["id"])
    return {
        "salary_cents_per_tick": salary_total(db, company["id"]),
        "effects": eff,
        "employees": [{"id": e["id"], "name": e["name"], "role": e["role"], "skill": e["skill"], "xp": e["xp"],
                       "xp_needed": cfg.XP_PER_LEVEL * e["skill"], "salary_cents_per_tick": e["salary_cents_per_tick"],
                       "status": e["status"], "task": e["order_title"], "order_kind": e["order_kind"],
                       "dc_id": json.loads(e["order_plan"]).get("dc_id") if e["order_plan"] else None,
                       "slot": json.loads(e["order_plan"]).get("slot") if e["order_plan"] else None} for e in emps],
        "candidates": [{"id": c["id"], "name": c["name"], "role": c["role"], "skill": c["skill"],
                        "salary_cents_per_tick": c["salary_cents_per_tick"], "hire_cost_cents": c["hire_cost_cents"],
                        "expires_tick": c["expires_tick"]} for c in cands],
        "proposals": [{"id": p["id"], "kind": p["kind"], "title": p["title"], "admin": p["admin_name"], "cost_cents": p["cost_cents"],
                       "est_ticks": p["est_ticks"], "expires_tick": p["expires_tick"], **json.loads(p["summary_json"])} for p in props],
        "orders": [{"id": o["id"], "title": o["title"], "status": o["status"], "progress": o["progress"], "kind": o["kind"],
                    "dc_id": json.loads(o["plan_json"]).get("dc_id"), "total_ticks": o["total_ticks"], "employee": o["e_name"]} for o in orders],
        "max_employees": max_employees(db, company["id"]),
        "targets": staff_targets(db, company["id"]),
        "auto_accept": auto_accept_enabled(db, company["id"]),
        "policy": get_policy(db, company["id"]),
        "proposal_interval_days": cfg.PROPOSAL_INTERVAL_TICKS // 24,
        "sales_per_day": sum(e["skill"] for e in emps if e["role"] == "sales"),
    }
