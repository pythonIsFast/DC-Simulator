"""Tick simulation: incidents, power/heat evaluation, contracts, economy, milestones.

`evaluate` computes the live status of every rack and datacenter of a company
and writes it to the database. It runs every tick and also after each player
command (`refresh_company`), so the client sees consistent statuses even
while the game is paused. Economics (revenue, costs) only run in `tick_world`.
"""
import json
import random

import ai
import market
import racks as rk
from bookkeeping import add_event, book, change_cash
from data import game_config as cfg

OFFLINE_TEXT = {
    "tripped": "Breaker tripped",
    "overload": "Overloaded (breaker will trip)",
    "no_pdu": "No PDU installed",
    "no_uplink": "No uplink capacity",
    "grid_outage": "Grid outage",
    "pdu_failure": "PDU failure",
    "switch_failure": "Switch failure",
    "cable_fault": "Cable fault",
}


# ---------------------------------------------------------------- asset loading

def _rows_in(db, sql, ids):
    if not ids:
        return []
    return db.execute(sql.format(ph=",".join("?" * len(ids))), list(ids)).fetchall()


def load_assets(db, company_id):
    """Datacenters with equipment, racks and items of a company, as plain dicts."""
    dcs = [dict(r) for r in db.execute(
        "SELECT d.*, r.avg_temp_c, r.power_price_cents_kwh, r.land_cost_index, r.code AS region_code"
        " FROM datacenters d JOIN regions r ON r.id = d.region_id"
        " WHERE d.company_id = ? AND d.status = 'active' ORDER BY d.id", (company_id,))]
    dc_ids = [d["id"] for d in dcs]
    by_dc = {d["id"]: d for d in dcs}
    for d in dcs:
        d["equip"] = {}
        d["racks"] = []
    for row in _rows_in(
        db, "SELECT e.datacenter_id, e.qty, h.code, h.category, h.ports, h.attrs_json FROM dc_equipment e"
            " JOIN hardware_types h ON h.id = e.hardware_type_id WHERE e.datacenter_id IN ({ph})", dc_ids):
        by_dc[row["datacenter_id"]]["equip"][row["code"]] = {
            "qty": row["qty"], "category": row["category"], "ports": row["ports"],
            "attrs": json.loads(row["attrs_json"]),
        }
    rack_rows = [dict(r) for r in _rows_in(
        db, "SELECT * FROM racks WHERE datacenter_id IN ({ph}) ORDER BY slot, id", dc_ids)]
    by_rack = {}
    for r in rack_rows:
        r["items"] = []
        by_rack[r["id"]] = r
        by_dc[r["datacenter_id"]]["racks"].append(r)
    for row in _rows_in(
        db, "SELECT i.id, i.rack_id, i.u_start, h.code, h.category, h.name, h.u_height, h.power_w, h.heat_w,"
            " h.ports, h.price_cents, h.attrs_json FROM rack_items i"
            " JOIN hardware_types h ON h.id = i.hardware_type_id WHERE i.rack_id IN ({ph}) ORDER BY i.u_start",
        list(by_rack)):
        by_rack[row["rack_id"]]["items"].append(rk.item_from_row(row))
    return dcs


def active_region_events(db, world_id, tick):
    """{region_id: set(kind)} for region events that are currently active."""
    out = {}
    for row in db.execute(
        "SELECT region_id, kind FROM events WHERE world_id = ? AND ends_tick >= ? AND region_id IS NOT NULL",
        (world_id, tick),
    ):
        out.setdefault(row["region_id"], set()).add(row["kind"])
    return out


# ---------------------------------------------------------------- evaluation

def _empty_pool():
    return {"cpu": 0.0, "storage_tb": 0.0, "gpu": 0.0}


def evaluate(db, world_id, company_id, tick, dcs, region_events, allow_trip):
    """Compute live status of racks/datacenters and persist it. Returns an evaluation dict."""
    pools = {}
    energy_cents = rent_cents = staff_cents = 0
    rack_count = redundant_racks = max_used_u = 0

    for dc in dcs:
        rid = dc["region_id"]
        kinds = region_events.get(rid, set())
        agg_ports = sum(e["qty"] * e["ports"] for e in dc["equip"].values() if e["category"] == "dc_agg")
        crac_kw = sum(e["qty"] * e["attrs"].get("cooling_kw", 0) for e in dc["equip"].values() if e["category"] == "dc_crac")
        feed_kw = sum(e["qty"] * e["attrs"].get("power_kw", 0) for e in dc["equip"].values() if e["category"] == "dc_feed")
        uplinks_left = agg_ports

        online = []  # (rack, stats)
        for rack in dc["racks"]:
            stats = rk.rack_stats(rack["items"])
            rack["stats"] = stats
            rack_count += 1
            max_used_u = max(max_used_u, stats["used_u"])
            if stats["redundant"] and stats["server_count"] > 0:
                redundant_racks += 1

            if rack["status"] == "down" and rack["down_until_tick"] is not None and tick >= rack["down_until_tick"]:
                rack["status"], rack["down_until_tick"], rack["down_reason"] = "ok", None, None
                db.execute("UPDATE racks SET status='ok', down_until_tick=NULL, down_reason=NULL WHERE id=?", (rack["id"],))
                add_event(db, world_id, tick, "rack_recovered", "%s is back online" % rack["name"],
                          company_id=company_id, region_id=rid)

            reason = None
            if rack["status"] == "tripped":
                reason = "tripped"
            elif rack["status"] == "down":
                reason = rack["down_reason"] or "pdu_failure"
            elif stats["pdu_count"] == 0:
                reason = "no_pdu"
            elif stats["overload"]:
                if allow_trip:
                    rack["status"] = "tripped"
                    db.execute("UPDATE racks SET status='tripped', down_reason='breaker' WHERE id=?", (rack["id"],))
                    add_event(db, world_id, tick, "breaker_trip",
                              "Breaker tripped on %s (%.1f kW > %.1f kW)" % (
                                  rack["name"], stats["load_w"] / 1000, stats["limit_w"] / 1000),
                              company_id=company_id, region_id=rid)
                reason = "tripped" if allow_trip else "overload"
            if reason is None and stats["tor_count"] > 0:
                if stats["uplinks_needed"] > uplinks_left:
                    reason = "no_uplink"
                else:
                    uplinks_left -= stats["uplinks_needed"]
            if reason is None and "grid_outage" in kinds and not stats["has_ups"]:
                reason = "grid_outage"
            rack["_reason"] = reason
            if reason is None:
                online.append((rack, stats))

        it_kw = sum(s["load_w"] for _, s in online) / 1000.0
        heat_kw = sum(s["heat_w"] for _, s in online) / 1000.0
        cooling_cap = (dc["cooling_kw"] + crac_kw) * (cfg.HEATWAVE_COOLING_FACTOR if "heatwave" in kinds else 1.0)
        if heat_kw <= 0 or heat_kw <= cooling_cap:
            perf_thermal = 1.0
        elif heat_kw <= cooling_cap * cfg.THERMAL_SOFT_LIMIT:
            perf_thermal = 1.0 - 0.5 * (heat_kw / cooling_cap - 1.0) / (cfg.THERMAL_SOFT_LIMIT - 1.0)
        else:
            perf_thermal = 0.0
            recent = db.execute(
                "SELECT 1 FROM events WHERE world_id = ? AND kind = 'thermal_shutdown' AND company_id = ?"
                " AND region_id = ? AND tick > ?", (world_id, company_id, rid, tick - 12)).fetchone()
            if allow_trip and not recent:
                add_event(db, world_id, tick, "thermal_shutdown",
                          "Thermal shutdown in %s: not enough cooling!" % dc["name"],
                          company_id=company_id, region_id=rid)
        pue = cfg.PUE_BASE + cfg.PUE_PER_DEGREE * max(0.0, dc["avg_temp_c"] - cfg.PUE_REF_TEMP_C)
        facility_kw = it_kw * pue
        power_cap = dc["power_capacity_kw"] + feed_kw
        perf_power = 1.0 if facility_kw <= power_cap or facility_kw <= 0 else power_cap / facility_kw
        perf = min(perf_thermal, perf_power)

        for rack, stats in online:
            pool = pools.setdefault(rid, {"all": _empty_pool(), "red": _empty_pool()})
            for key in ("cpu", "storage_tb", "gpu"):
                pool["all"][key] += stats[key] * perf
                if stats["redundant"]:
                    pool["red"][key] += stats[key] * perf

        price = dc["power_price_cents_kwh"] * (cfg.POWER_SPIKE_FACTOR if "power_spike" in kinds else 1.0)
        energy_cents += facility_kw * price
        rent_cents += cfg.DC_RENT_CENTS_PER_TICK * dc["land_cost_index"]
        staff_cents += cfg.STAFF_CENTS_PER_RACK_TICK * len(dc["racks"])

        # Persist runtime state (only changed values).
        for rack in dc["racks"]:
            stats = rack["stats"]
            is_online = 1 if rack["_reason"] is None else 0
            load = stats["load_w"] if is_online else 0.0
            heat = stats["heat_w"] if is_online else 0.0
            if (rack["online"], rack["offline_reason"], rack["load_w"], rack["heat_w"]) != (
                    is_online, rack["_reason"], load, heat):
                db.execute("UPDATE racks SET online=?, offline_reason=?, load_w=?, heat_w=? WHERE id=?",
                           (is_online, rack["_reason"], load, heat, rack["id"]))
                rack["online"], rack["offline_reason"], rack["load_w"], rack["heat_w"] = (
                    is_online, rack["_reason"], load, heat)
        db.execute("UPDATE datacenters SET perf=?, heat_kw=?, cooling_cap_kw=?, facility_kw=? WHERE id=?",
                   (perf, heat_kw, cooling_cap, facility_kw, dc["id"]))
        dc["perf"] = perf

    return {
        "pools": pools, "energy_cents": int(energy_cents), "rent_cents": int(rent_cents),
        "staff_cents": int(staff_cents), "rack_count": rack_count, "redundant_racks": redundant_racks,
        "max_used_u": max_used_u,
    }


# ---------------------------------------------------------------- incidents and events

def roll_incidents(db, world_id, company_id, tick, rng, dcs):
    """Random equipment failures. Redundant hardware absorbs them."""
    for dc in dcs:
        for rack in dc["racks"]:
            if rack["status"] != "ok" or not rack["items"]:
                continue
            stats = rk.rack_stats(rack["items"])
            for kind, p, absorbed, label in (
                ("pdu_failure", cfg.P_PDU_FAILURE, stats["power_redundant"], "PDU failure"),
                ("switch_failure", cfg.P_SWITCH_FAILURE, stats["net_redundant"], "Switch failure"),
                ("cable_fault", cfg.P_CABLE_FAULT * stats["incident_mult"], stats["net_redundant"], "Cable fault"),
            ):
                if rng.random() >= p:
                    continue
                if absorbed:
                    add_event(db, world_id, tick, "incident_absorbed",
                              "%s on %s absorbed by redundancy" % (label, rack["name"]),
                              company_id=company_id, region_id=dc["region_id"])
                    continue
                until = tick + rng.randint(*cfg.INCIDENT_DURATION_TICKS)
                rack["status"], rack["down_until_tick"], rack["down_reason"] = "down", until, kind
                db.execute("UPDATE racks SET status='down', down_until_tick=?, down_reason=? WHERE id=?",
                           (until, kind, rack["id"]))
                add_event(db, world_id, tick, "incident",
                          "%s on %s: offline until repaired (%d h)" % (label, rack["name"], until - tick),
                          company_id=company_id, region_id=dc["region_id"])
                break


def roll_region_events(db, world, tick, rng, human_regions):
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM regions WHERE world_id = ?", (world["id"],))}
    active = active_region_events(db, world["id"], tick)
    table = (
        ("grid_outage", cfg.P_GRID_OUTAGE, cfg.GRID_OUTAGE_TICKS, "Grid outage in %s"),
        ("heatwave", cfg.P_HEATWAVE, cfg.HEATWAVE_TICKS, "Heatwave in %s: cooling capacity reduced"),
        ("power_spike", cfg.P_POWER_SPIKE, cfg.POWER_SPIKE_TICKS, "Power prices spike in %s"),
        ("market_boom", cfg.P_MARKET_BOOM, cfg.MARKET_BOOM_TICKS, "Demand boom in %s: more customers"),
    )
    for rid in sorted(human_regions):
        for kind, p, (lo, hi), text in table:
            if kind in active.get(rid, set()) or rng.random() >= p:
                continue
            add_event(db, world["id"], tick, kind, text % names[rid], region_id=rid, ends_tick=tick + rng.randint(lo, hi))


# ---------------------------------------------------------------- contracts and economy

def settle_contracts(db, world_id, company, tick, ev, dcs):
    """Allocate pooled capacity to active contracts. Returns revenue in cents."""
    pools = ev["pools"]
    cap_eq, used_eq = {}, {}
    for rid, pool in pools.items():
        cap_eq[rid] = sum(pool["all"][res] * cfg.UNIT_WEIGHT[res] for res in pool["all"])
    revenue = 0
    contracts = db.execute(
        "SELECT * FROM contracts WHERE company_id = ? AND status = 'active' ORDER BY premium DESC, id",
        (company["id"],)).fetchall()
    for c in contracts:
        rid = c["region_id"]
        if tick >= c["end_tick"]:
            db.execute("UPDATE contracts SET status='completed' WHERE id=?", (c["id"],))
            add_event(db, world_id, tick, "contract_completed", "Contract '%s' completed" % c["name"],
                      company_id=company["id"], region_id=rid)
            continue
        pool = pools.get(rid)
        res = c["resource"]
        src = pool["red"] if (pool and c["premium"]) else (pool["all"] if pool else None)
        served = src is not None and src[res] >= c["units"]
        if served:
            src[res] -= c["units"]
            if c["premium"]:
                pool["all"][res] -= c["units"]
            revenue += c["revenue_cents_per_tick"]
            used_eq[rid] = used_eq.get(rid, 0.0) + c["units_eq"]
            if c["sla_fail_streak"]:
                db.execute("UPDATE contracts SET sla_fail_streak=0 WHERE id=?", (c["id"],))
        else:
            streak = c["sla_fail_streak"] + 1
            if streak >= cfg.SLA_BREACH_TICKS:
                db.execute("UPDATE contracts SET status='breached', sla_fail_streak=? WHERE id=?", (streak, c["id"]))
                book(db, world_id, company["id"], tick, "penalty", -c["penalty_cents"], "SLA breach: " + c["name"])
                change_cash(db, company["id"], -c["penalty_cents"])
                add_event(db, world_id, tick, "contract_breached",
                          "Contract '%s' breached! Penalty paid." % c["name"],
                          company_id=company["id"], region_id=rid)
            else:
                db.execute("UPDATE contracts SET sla_fail_streak=? WHERE id=?", (streak, c["id"]))
                if streak == 6:
                    add_event(db, world_id, tick, "sla_warning",
                              "'%s' is not served: add capacity or repair racks!" % c["name"],
                              company_id=company["id"], region_id=rid)
    for dc in dcs:
        rid = dc["region_id"]
        util = used_eq.get(rid, 0.0) / cap_eq[rid] if cap_eq.get(rid) else 0.0
        db.execute("UPDATE datacenters SET util=? WHERE id=?", (min(1.0, util), dc["id"]))
    return revenue


def check_milestones(db, world_id, company, tick, ev, dcs):
    have = {r["code"] for r in db.execute("SELECT code FROM milestones WHERE company_id = ?", (company["id"],))}
    reached = []
    if dcs:
        reached.append("first_datacenter")
    if len({d["region_id"] for d in dcs}) >= 2:
        reached.append("first_new_region")
    if ev["max_used_u"] >= cfg.RACK_U:
        reached.append("first_rack_full")
    if ev["redundant_racks"] >= 1:
        reached.append("first_redundant_rack")
    if ev["rack_count"] >= 10:
        reached.append("ten_racks")
    if db.execute("SELECT 1 FROM contracts WHERE company_id = ? AND status != 'cancelled' LIMIT 1",
                  (company["id"],)).fetchone():
        reached.append("first_contract")
    cash = db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company["id"],)).fetchone()[0]
    if cash >= 1_000_000_00:
        reached.append("cash_1m")
    for code in reached:
        if code in have:
            continue
        name, reward = cfg.MILESTONES[code]
        db.execute("INSERT INTO milestones (company_id, code, reached_tick) VALUES (?, ?, ?)",
                   (company["id"], code, tick))
        book(db, world_id, company["id"], tick, "reward", reward, "Milestone: " + name)
        change_cash(db, company["id"], reward)
        add_event(db, world_id, tick, "milestone", "Milestone: %s" % name, company_id=company["id"],
                  code=code, reward_cents=reward)


def refresh_company(db, world, company_id, tick):
    """Re-evaluate a company's live state without running economics (after commands)."""
    company = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    dcs = load_assets(db, company_id)
    events = active_region_events(db, world["id"], tick)
    ev = evaluate(db, world["id"], company_id, tick, dcs, events, allow_trip=False)
    check_milestones(db, world["id"], company, tick, ev, dcs)


def _run_company_tick(db, world, company, tick, rng, dcs, region_events):
    roll_incidents(db, world["id"], company["id"], tick, rng, dcs)
    ev = evaluate(db, world["id"], company["id"], tick, dcs, region_events, allow_trip=True)
    revenue = settle_contracts(db, world["id"], company, tick, ev, dcs)
    expenses = {"power": ev["energy_cents"], "rent": ev["rent_cents"], "staff": ev["staff_cents"]}
    book(db, world["id"], company["id"], tick, "revenue", revenue, "Customer contracts")
    for category, cents in expenses.items():
        book(db, world["id"], company["id"], tick, category, -cents)
    total_expense = sum(expenses.values())
    change_cash(db, company["id"], revenue - total_expense)
    db.execute("UPDATE companies SET last_revenue_cents = ?, last_expense_cents = ? WHERE id = ?",
               (revenue, total_expense, company["id"]))
    check_milestones(db, world["id"], company, tick, ev, dcs)


def tick_world(db, world, tick):
    """Advance the whole world by one tick (registered in clock.TICK_HANDLERS)."""
    wid = world["id"]
    rng = random.Random(world["seed"] * 1_000_003 + tick)
    humans = db.execute("SELECT * FROM companies WHERE world_id = ? AND is_ai = 0 ORDER BY id", (wid,)).fetchall()
    assets = {c["id"]: load_assets(db, c["id"]) for c in humans}
    human_regions = {dc["region_id"] for dcs in assets.values() for dc in dcs}
    roll_region_events(db, world, tick, rng, human_regions)
    region_events = active_region_events(db, wid, tick)
    for company in humans:
        _run_company_tick(db, world, company, tick, rng, assets[company["id"]], region_events)
    if tick % 24 == 0:
        info = market.compute_market(db, wid, tick, persist=False)
        market.generate_offers(db, world, tick, rng, human_regions, info)
        ai.run_ai_day(db, world, tick, rng)
        market.compute_market(db, wid, tick, persist=True)
        db.execute("DELETE FROM ledger WHERE world_id = ? AND tick < ?", (wid, tick - cfg.LEDGER_KEEP_TICKS))
        db.execute("DELETE FROM events WHERE world_id = ? AND tick < ? AND (ends_tick IS NULL OR ends_tick < ?)",
                   (wid, tick - cfg.EVENTS_KEEP_TICKS, tick))
