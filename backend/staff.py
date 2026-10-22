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


def hire(db, world, company, candidate_id):
    cand = db.execute("SELECT * FROM candidates WHERE id = ? AND company_id = ?", (candidate_id, company["id"])).fetchone()
    if cand is None:
        raise StaffError("Candidate is no longer available")
    count = db.execute("SELECT COUNT(*) FROM employees WHERE company_id = ?", (company["id"],)).fetchone()[0]
    if count >= cfg.MAX_EMPLOYEES:
        raise StaffError("Maximum %d employees" % cfg.MAX_EMPLOYEES)
    _pay(db, world, company, cand["hire_cost_cents"], "hiring", "Hired " + cand["name"])
    cur = db.execute(
        "INSERT INTO employees (company_id, name, role, skill, salary_cents_per_tick, hired_tick) VALUES (?, ?, ?, ?, ?, ?)",
        (company["id"], cand["name"], cand["role"], cand["skill"], cand["salary_cents_per_tick"], world["tick"]))
    db.execute("DELETE FROM candidates WHERE id = ?", (cand["id"],))
    emp_id = cur.lastrowid
    if cand["role"] == "admin":   # a new admin has a first idea right away
        emp = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
        generate_proposals(db, world, company, world["tick"], random.Random(emp_id * 31 + world["tick"]), [emp], per_admin=1)
    return emp_id


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


# ---------------------------------------------------------------- rack design (what admins propose)

def _pick_server(servers, resource, skill):
    if skill >= 4:
        return max(servers, key=lambda h: h["attrs"][resource] / max(1, h["power_w"]))
    if skill == 3:
        return max(servers, key=lambda h: h["attrs"][resource] / h["price_cents"])
    return servers[len(servers) // 2]


def design_extension(rack, hws, resource, skill):
    """Servers for the free space of an existing rack, as long as power, ports and (if present) redundancy hold."""
    servers = sorted((h for h in hws if h["category"] == RESOURCE_CATEGORY[resource]), key=lambda h: h["price_cents"])
    if not servers:
        return None
    server = _pick_server(servers, resource, skill)
    items = list(rack["items"])
    keep_redundant = rk.rack_stats(items)["redundant"] and skill >= 3
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


def design_rack(hws, resource, skill):
    """Rule-based rack layout. Higher skill = better server choice, redundancy, fans and cabling.

    Returns a layout [{code, u_start}] or None. Gear sits at the top, servers fill from the bottom.
    """
    by_code = {h["code"]: h for h in hws}
    servers = sorted((h for h in hws if h["category"] == RESOURCE_CATEGORY[resource]), key=lambda h: h["price_cents"])
    if not servers or "pdu_7k2" not in by_code:
        return None
    server = _pick_server(servers, resource, skill)
    redundant = skill >= 3
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
            elif plan["type"] == "extend_rack":
                keys.add(("extend_rack", plan["rack_id"]))
            elif plan["type"] == "add_redundancy":
                keys.add(("redundancy", plan["rack_id"]))
            else:
                keys.add(("new_datacenter", plan["region_id"]))
    return keys


def _propose_upgrade(db, world, company, admin, tick, dcs, hws, keys):
    by_code = {h["code"]: h for h in hws}
    threshold = 1.0 if admin["skill"] == 1 else 0.9
    for dc in dcs:
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
            if ("upgrade", dc["id"], code) in keys:
                continue
            hw = by_code.get(code) or by_code.get({"dc_chiller": "dc_crac", "dc_feed_big": "dc_feed"}.get(code))   # locked? use the basic variant
            if hw is None or hw["price_cents"] > _cash(db, company["id"]):
                continue
            code = hw["code"]
            if ("upgrade", dc["id"], code) in keys:
                continue
            plan = {"type": "upgrade", "dc_id": dc["id"], "code": code, "qty": 1}
            summary = {"lines": [why, "Installs: 1x %s" % hw["name"]], "items": [], "adds": {}, "revenue_cents_per_tick": 0}
            _insert_proposal(db, world, company, admin, tick, "upgrade", "Add %s to %s" % (hw["name"], dc["name"]),
                             plan, summary, hw["price_cents"], 8)
            return True
    return False


def _cash(db, company_id):
    return db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company_id,)).fetchone()[0]


def _gaps(db, world, dcs, cap):
    """Regions and resources where open customer offers exceed what we can serve, biggest gap first."""
    gaps = []
    for row in db.execute("SELECT region_id, resource, SUM(units) AS u, COUNT(*) AS n FROM contracts"
                          " WHERE world_id = ? AND status = 'offered' GROUP BY region_id, resource", (world["id"],)):
        rid = row["region_id"]
        if not any(dc["region_id"] == rid for dc in dcs):
            continue
        free = max(0.0, cap.get(rid, {}).get(row["resource"], {}).get("free", 0.0))
        gap = row["u"] - free
        gap_eq = gap * cfg.UNIT_WEIGHT[row["resource"]]
        if gap_eq >= 20:
            gaps.append((gap_eq, rid, row["resource"], row["n"], row["u"], free))
    gaps.sort(reverse=True)
    return gaps


def _propose_extend(db, world, company, admin, tick, rng, dcs, cap, hws, keys, regions):
    for _, rid, res, n_offers, units, free in _gaps(db, world, dcs, cap):
        racks = [(dc, r) for dc in dcs if dc["region_id"] == rid for r in dc["racks"]
                 if r["status"] == "ok" and ("extend_rack", r["id"]) not in keys and r["stats"]["pdu_count"] and r["stats"]["tor_count"] and r["stats"]["free_u"] >= 1]
        racks.sort(key=lambda x: -x[1]["stats"]["free_u"])
        for dc, rack in racks:
            add = design_extension(rack, hws, res, admin["skill"])
            if not add:
                continue
            by_code = {h["code"]: h for h in hws}
            cost = sum(by_code[a["code"]]["price_cents"] for a in add)
            if cost > _cash(db, company["id"]) * 0.9:
                continue
            server = by_code[add[0]["code"]]
            gained = len(add) * server["attrs"][res]
            rate = {"cpu": 1.0, "storage_tb": 1.0, "gpu": cfg.KIND_RATE_MULT["ai"]}[res]
            summary = {
                "lines": ["Why: %d open offers ask for %s %s, you have %s free." % (n_offers, "{:,.0f}".format(units), RESOURCE_UNIT[res], "{:,.0f}".format(free)),
                          "%s has free space: add %d more servers without touching the existing setup." % (rack["name"], len(add)),
                          "Adds %s %s." % ("{:,.0f}".format(gained), RESOURCE_UNIT[res])],
                "items": [{"code": server["code"], "name": server["name"], "count": len(add)}], "adds": {res: gained},
                "revenue_cents_per_tick": int(gained * cfg.UNIT_WEIGHT[res] * cfg.BASE_RATE_CENTS * rate),
            }
            plan = {"type": "extend_rack", "dc_id": dc["id"], "rack_id": rack["id"], "slot": rack["slot"], "layout": add}
            _insert_proposal(db, world, company, admin, tick, "extend_rack", "Add %d x %s to %s (%s)" % (len(add), server["name"], rack["name"], dc["name"]),
                             plan, summary, cost, int(2 + 0.5 * len(add)))
            return True
    return False


def _propose_redundancy(db, world, company, admin, tick, rng, dcs, hws, keys):
    if admin["skill"] < 3:
        return False
    by_code = {h["code"]: h for h in hws}
    for dc in dcs:
        for rack in dc["racks"]:
            st = rack["stats"]
            if rack["status"] != "ok" or st["server_count"] == 0 or st["redundant"] or ("redundancy", rack["id"]) in keys:
                continue
            add = design_redundancy(rack, hws)
            if not add:
                continue
            cost = sum(by_code[a["code"]]["price_cents"] for a in add)
            if cost > _cash(db, company["id"]) * 0.9:
                continue
            counts = {}
            for a in add:
                counts[a["code"]] = counts.get(a["code"], 0) + 1
            what = []
            if st["pdu_count"] < 2:
                what.append("a second PDU")
            if st["tor_count"] < 2:
                what.append("a second ToR switch")
            summary = {
                "lines": ["%s has no redundancy: if its PDU or switch fails, the whole rack goes offline." % rack["name"],
                          "Adds %s. Redundant racks absorb failures and can serve premium contracts." % " and ".join(what)],
                "items": [{"code": c, "name": by_code[c]["name"], "count": n} for c, n in counts.items()], "adds": {}, "revenue_cents_per_tick": 0,
            }
            plan = {"type": "add_redundancy", "dc_id": dc["id"], "rack_id": rack["id"], "slot": rack["slot"], "layout": add}
            _insert_proposal(db, world, company, admin, tick, "add_redundancy", "Add redundancy to %s (%s)" % (rack["name"], dc["name"]),
                             plan, summary, cost, int(2 + 0.5 * len(add)))
            return True
    return False


def _propose_rack(db, world, company, admin, tick, rng, dcs, cap, hws, keys, regions):
    gaps = _gaps(db, world, dcs, cap)
    if not gaps:
        return False
    for _, rid, res, n_offers, units, free in gaps:
        candidates = [dc for dc in dcs if dc["region_id"] == rid and len(dc["racks"]) < dc["max_racks"] and ("new_rack", dc["id"]) not in keys]
        if not candidates:
            continue
        dc = max(candidates, key=lambda d: d["max_racks"] - len(d["racks"]))
        layout = design_rack(hws, res, admin["skill"])
        if not layout:
            continue
        items, stats, items_cost = _layout_summary(layout, hws)
        cost = cfg.RACK_SHELL_CENTS + items_cost
        if cost > _cash(db, company["id"]) * 0.9:
            continue
        weight = cfg.UNIT_WEIGHT[res]
        rate = {"cpu": 1.0, "storage_tb": 1.0, "gpu": cfg.KIND_RATE_MULT["ai"]}[res]
        revenue = int(stats[res] * weight * cfg.BASE_RATE_CENTS * rate)
        region = regions[rid]
        summary = {
            "lines": [
                "Why: %d open offers ask for %s %s, you have %s free." % (n_offers, "{:,.0f}".format(units), RESOURCE_UNIT[res], "{:,.0f}".format(free)),
                "Adds %s %s and uses %.1f kW." % ("{:,.0f}".format(stats[res]), RESOURCE_UNIT[res], stats["load_w"] / 1000),
                "Redundant power and network: %s." % ("yes" if stats["redundant"] else "no (cheaper, riskier)"),
            ],
            "items": items, "adds": {res: stats[res]}, "revenue_cents_per_tick": revenue,
        }
        plan = {"type": "new_rack", "dc_id": dc["id"], "layout": layout}
        est = int(4 + 0.5 * len(layout))
        _insert_proposal(db, world, company, admin, tick, "new_rack", "%s rack for %s (%s)" % (RESOURCE_LABEL[res], region["name"], dc["name"]),
                         plan, summary, cost, est)
        return True
    return False


def _propose_datacenter(db, world, company, admin, tick, rng, dcs, keys, regions, info):
    if admin["skill"] < 3:
        return False
    full = all(len(dc["racks"]) >= dc["max_racks"] - 2 for dc in dcs)
    cash = _cash(db, company["id"])
    if not full and not (cash > 6 * cfg.DC_BUILD_BASE_CENTS and rng.random() < 0.15):
        return False
    best = None
    for rid, region in regions.items():
        mine = sum(1 for dc in dcs if dc["region_id"] == rid)
        cost = builder.dc_cost(region)
        if mine >= cfg.DC_MAX_PER_REGION or ("new_datacenter", rid) in keys or cost * 1.3 > cash:
            continue
        d = info[rid]
        score = (d["free"] / max(1.0, d["demand"])) * region["demand_index"] / region["land_cost_index"] * (0.5 if mine else 1.0)
        if best is None or score > best[0]:
            best = (score, rid, region, cost, mine, d)
    if best is None:
        return False
    _, rid, region, cost, mine, d = best
    name = "%s DC %d" % (region["name"], mine + 1)
    summary = {
        "lines": ["Why: %s units of customer demand in %s are unserved (%d %% of the market)." % (
            "{:,.0f}".format(d["free"]), region["name"], 100 * d["free"] / max(1.0, d["demand"])),
            "A new datacenter has 20 rack slots, base cooling 60 kW and one aggregation switch.",
            "Electricity: %.0f c/kWh, climate %.0f degrees C." % (region["power_price_cents_kwh"], region["avg_temp_c"])],
        "items": [], "adds": {}, "revenue_cents_per_tick": 0,
    }
    _insert_proposal(db, world, company, admin, tick, "new_datacenter", "New datacenter in %s" % region["name"],
                     {"type": "new_datacenter", "region_id": rid, "name": name}, summary, cost, 48)
    return True


def generate_proposals(db, world, company, tick, rng, admins, per_admin=None):
    import sim   # local import: sim imports this module
    open_n = db.execute("SELECT COUNT(*) FROM proposals WHERE company_id = ? AND status = 'open'", (company["id"],)).fetchone()[0]
    room = cfg.MAX_OPEN_PROPOSALS - open_n
    if room <= 0 or not admins:
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
    cap = capacity.region_capacity(dcs, contracts)
    regions = {r["id"]: r for r in db.execute("SELECT * FROM regions WHERE world_id = ?", (world["id"],))}
    info = market.compute_market(db, world["id"], tick, persist=False)
    keys = _planned_keys(db, company["id"])
    created = 0
    admins = list(admins)
    rng.shuffle(admins)
    for admin in admins:
        for _ in range(per_admin or cfg.PROPOSALS_PER_ADMIN_PER_DAY):
            if created >= room:
                return created
            before = _planned_keys(db, company["id"])
            ok = (_propose_upgrade(db, world, company, admin, tick, dcs, hws, keys)
                  or _propose_redundancy(db, world, company, admin, tick, rng, dcs, hws, keys)
                  or _propose_extend(db, world, company, admin, tick, rng, dcs, cap, hws, keys, regions)
                  or _propose_rack(db, world, company, admin, tick, rng, dcs, cap, hws, keys, regions)
                  or _propose_datacenter(db, world, company, admin, tick, rng, dcs, keys, regions, info))
            if not ok:
                break
            keys = _planned_keys(db, company["id"])
            created += 1 if keys != before else 0
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
    if plan["type"] in ("extend_rack", "add_redundancy"):
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
    elif plan["type"] in ("extend_rack", "add_redundancy"):
        rack = db.execute("SELECT r.id FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE r.id = ? AND d.company_id = ?",
                          (plan["rack_id"], company["id"])).fetchone()
        if rack is None:
            raise builder.BuildError("The rack no longer exists")
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
        try:
            _execute_plan(db, world, company, json.loads(o["plan_json"]))
        except builder.BuildError as exc:
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


def daily(db, world, company, tick, rng):
    ensure_candidates(db, company["id"], tick, rng)
    sales_accept(db, world, company, tick)
    db.execute("UPDATE proposals SET status = 'expired' WHERE company_id = ? AND status = 'open' AND expires_tick < ?", (company["id"], tick))
    db.execute("DELETE FROM work_orders WHERE company_id = ? AND status IN ('done', 'failed') AND created_tick < ?", (company["id"], tick - 24 * 10))
    admins = db.execute("SELECT * FROM employees WHERE company_id = ? AND role = 'admin'", (company["id"],)).fetchall()
    generate_proposals(db, world, company, tick, rng, admins)


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
        "max_employees": cfg.MAX_EMPLOYEES,
        "auto_accept": auto_accept_enabled(db, company["id"]),
        "sales_per_day": sum(e["skill"] for e in emps if e["role"] == "sales"),
    }
