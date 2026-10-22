"""World model: creation and state serialization for the client."""
import json
import random
import time

import ai
import market
import racks as rk
import sim
from data import game_config as cfg
from data.world_seed import AI_RIVALS, REGIONS

PLAYER_COLOR = "#4ea1ff"


def create_world(db, user_id, world_name, company_name, ai_count):
    """Create a singleplayer world with one human company and AI rivals.

    Returns the new world id. The whole creation is one transaction.
    """
    ai_count = max(cfg.MIN_AI_RIVALS, min(cfg.MAX_AI_RIVALS, ai_count))
    now = time.time()
    seed = random.randrange(2**31)
    rng = random.Random(seed)
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = db.execute(
            "INSERT INTO worlds (name, owner_user_id, mode, seed, speed, last_update_ts) VALUES (?, ?, 'singleplayer', ?, 0, ?)",
            (world_name, user_id, seed, now),
        )
        world_id = cur.lastrowid

        for code, name, lat, lon, demand, power, temp, land in REGIONS:
            db.execute(
                "INSERT INTO regions (world_id, code, name, lat, lon, demand_index, power_price_cents_kwh,"
                " avg_temp_c, land_cost_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (world_id, code, name, lat, lon, demand, power, temp, land),
            )
        regions = db.execute("SELECT * FROM regions WHERE world_id = ? ORDER BY id", (world_id,)).fetchall()

        company_ids = [_insert_company(db, world_id, user_id, company_name, PLAYER_COLOR, cfg.START_CASH_CENTS, None)]
        homes = rng.sample(regions, min(ai_count, len(regions)))
        for (name, color, strategy), home in zip(AI_RIVALS[:ai_count], homes):
            cid = _insert_company(db, world_id, None, name, color, cfg.AI_START_CASH_CENTS, strategy)
            company_ids.append(cid)
            ai.init_rival(db, cid, regions, home["id"])

        # Rows exist for every company and region so the simulation can just UPDATE them.
        for r in regions:
            for cid in company_ids:
                db.execute("INSERT INTO market_share (world_id, region_id, company_id, share) VALUES (?, ?, ?, 0)",
                           (world_id, r["id"], cid))
        market.compute_market(db, world_id, 0, persist=True)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return world_id


def _insert_company(db, world_id, user_id, name, color, cash_cents, strategy):
    cur = db.execute(
        "INSERT INTO companies (world_id, user_id, name, is_ai, ai_strategy, color, cash_cents)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (world_id, user_id, name, 0 if user_id else 1, strategy, color, cash_cents),
    )
    return cur.lastrowid


def get_user_company(db, world_id, user_id):
    """The company a user controls in a world, or None if they are not a member."""
    return db.execute(
        "SELECT * FROM companies WHERE world_id = ? AND user_id = ?", (world_id, user_id)
    ).fetchone()


def world_summary(world):
    return {
        "id": world["id"], "name": world["name"], "mode": world["mode"], "tick": world["tick"],
        "speed": world["speed"], "tick_progress": world["tick_progress"],
        "seconds_per_tick": cfg.SECONDS_PER_TICK_1X,
    }


def hardware_catalog(db):
    rows = db.execute("SELECT * FROM hardware_types ORDER BY id").fetchall()
    return {
        "hardware": [
            {k: v for k, v in rk.hardware_from_row(r).items()} for r in rows
        ],
        "rules": {
            "rack_u": cfg.RACK_U, "rack_shell_cents": cfg.RACK_SHELL_CENTS, "sell_back_ratio": cfg.SELL_BACK_RATIO,
            "feed_limit_w": cfg.RACK_FEED_LIMIT_W, "max_per_rack": cfg.MAX_PER_RACK,
            "dc_max_racks": cfg.DC_MAX_RACKS, "repair_cost_cents": cfg.REPAIR_COST_CENTS,
        },
    }


def _net_worth(db, company):
    """Cash plus half the purchase value of hardware and buildings."""
    items = db.execute(
        "SELECT COALESCE(SUM(h.price_cents), 0) FROM rack_items i JOIN hardware_types h ON h.id = i.hardware_type_id"
        " JOIN racks r ON r.id = i.rack_id JOIN datacenters d ON d.id = r.datacenter_id WHERE d.company_id = ?",
        (company["id"],)).fetchone()[0]
    dcs = db.execute("SELECT COALESCE(SUM(build_cost_cents), 0) FROM datacenters WHERE company_id = ?",
                     (company["id"],)).fetchone()[0]
    return int(company["cash_cents"] + (items + dcs) * cfg.SELL_BACK_RATIO)


def _rack_json(rack):
    stats = rack["stats"]
    keep = ("used_u", "free_u", "load_w", "heat_w", "limit_w", "pdu_count", "pdu_cap_w", "tor_count", "ports_total",
            "ports_used", "server_count", "connected_ids", "cpu", "storage_tb", "gpu", "power_redundant",
            "net_redundant", "redundant", "overload", "has_ups", "warnings", "uplinks_needed", "ups_w")
    return {
        "id": rack["id"], "name": rack["name"], "slot": rack["slot"], "status": rack["status"],
        "online": bool(rack["online"]), "offline_reason": rack["offline_reason"],
        "offline_text": sim.OFFLINE_TEXT.get(rack["offline_reason"]),
        "down_until_tick": rack["down_until_tick"],
        "items": [{"id": i["id"], "code": i["code"], "u_start": i["u_start"]} for i in rack["items"]],
        "stats": {k: stats[k] for k in keep},
    }


def _contract_json(c):
    return {
        "id": c["id"], "kind": c["kind"], "name": c["name"], "region_id": c["region_id"], "resource": c["resource"],
        "units": c["units"], "units_eq": c["units_eq"], "premium": bool(c["premium"]),
        "revenue_cents_per_tick": c["revenue_cents_per_tick"], "penalty_cents": c["penalty_cents"],
        "duration_ticks": c["duration_ticks"], "end_tick": c["end_tick"], "status": c["status"],
        "sla_fail_streak": c["sla_fail_streak"], "offer_expires_tick": c["offer_expires_tick"],
    }


def world_state(db, world, company, since_event=None):
    """Full state snapshot for the client of `company`."""
    wid, tick = world["id"], world["tick"]
    dcs = sim.load_assets(db, company["id"])
    for dc in dcs:
        for rack in dc["racks"]:
            rack["stats"] = rk.rack_stats(rack["items"])

    regions = db.execute("SELECT * FROM regions WHERE world_id = ? ORDER BY id", (wid,)).fetchall()
    info = market.compute_market(db, wid, tick, persist=False)
    region_events = sim.active_region_events(db, wid, tick)

    companies = db.execute("SELECT * FROM companies WHERE world_id = ? ORDER BY id", (wid,)).fetchall()
    ai_units = {}
    for rid, d in info.items():
        for cid, units in d["ai"].items():
            ai_units[cid] = ai_units.get(cid, 0.0) + units
    rivals = []
    for c in companies:
        if c["id"] == company["id"]:
            continue
        # Rival cash is hidden on purpose; only an approximate net worth is shown.
        worth = int(c["cash_cents"] + ai_units.get(c["id"], 0.0) * cfg.AI_CAPEX_CENTS_PER_UNIT * cfg.SELL_BACK_RATIO)
        rivals.append({"id": c["id"], "name": c["name"], "color": c["color"], "is_ai": bool(c["is_ai"]),
                       "net_worth_cents": worth})

    shares = db.execute("SELECT region_id, company_id, share FROM market_share WHERE world_id = ? AND share > 0",
                        (wid,)).fetchall()

    contracts = db.execute(
        "SELECT * FROM contracts WHERE world_id = ? AND (company_id = ? OR status = 'offered')"
        " AND status IN ('offered', 'active') ORDER BY status, id", (wid, company["id"])).fetchall()
    own = [c for c in contracts if c["company_id"] == company["id"]]
    offers = [c for c in contracts if c["status"] == "offered"]

    if since_event is None:
        ev_rows = db.execute(
            "SELECT * FROM (SELECT * FROM events WHERE world_id = ? AND (company_id IS NULL OR company_id = ?)"
            " ORDER BY id DESC LIMIT 30) ORDER BY id", (wid, company["id"])).fetchall()
    else:
        ev_rows = db.execute(
            "SELECT * FROM events WHERE world_id = ? AND (company_id IS NULL OR company_id = ?) AND id > ?"
            " ORDER BY id LIMIT 100", (wid, company["id"], since_event)).fetchall()
    latest = db.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE world_id = ?", (wid,)).fetchone()[0]

    templates = db.execute("SELECT id, name, layout_json FROM rack_templates WHERE company_id = ? ORDER BY id",
                           (company["id"],)).fetchall()
    milestones = db.execute("SELECT code, reached_tick FROM milestones WHERE company_id = ?", (company["id"],)).fetchall()

    return {
        "world": world_summary(world),
        "company": {
            "id": company["id"], "name": company["name"], "color": company["color"],
            "cash_cents": company["cash_cents"], "revenue_cents_per_tick": company["last_revenue_cents"],
            "expense_cents_per_tick": company["last_expense_cents"], "net_worth_cents": _net_worth(db, company),
            # Last settled tick split by category (negative = cost), shown in the HUD.
            "breakdown": {r["category"]: r["s"] for r in db.execute(
                "SELECT category, SUM(amount_cents) AS s FROM ledger WHERE company_id = ? AND tick = ?"
                " AND category IN ('revenue', 'power', 'rent', 'staff') GROUP BY category", (company["id"], tick))},
        },
        "rivals": rivals,
        "regions": [
            {
                "id": r["id"], "code": r["code"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                "demand_index": r["demand_index"], "power_price_cents_kwh": r["power_price_cents_kwh"],
                "avg_temp_c": r["avg_temp_c"], "land_cost_index": r["land_cost_index"],
                "build_cost_cents": int(cfg.DC_BUILD_BASE_CENTS * r["land_cost_index"]),
                "demand_units": info[r["id"]]["demand"], "free_units": info[r["id"]]["free"],
                "events": sorted(region_events.get(r["id"], [])),
            }
            for r in regions
        ],
        "datacenters": [
            {
                "id": dc["id"], "name": dc["name"], "region_id": dc["region_id"],
                "power_capacity_kw": dc["power_capacity_kw"] + sum(
                    e["qty"] * e["attrs"].get("power_kw", 0) for e in dc["equip"].values()),
                "cooling_kw": dc["cooling_kw"] + sum(
                    e["qty"] * e["attrs"].get("cooling_kw", 0) for e in dc["equip"].values()),
                "cooling_cap_kw": dc["cooling_cap_kw"], "heat_kw": dc["heat_kw"], "facility_kw": dc["facility_kw"],
                "perf": dc["perf"], "util": dc["util"],
                "uplink_ports": sum(e["qty"] * e["ports"] for e in dc["equip"].values() if e["category"] == "dc_agg"),
                "equipment": {code: e["qty"] for code, e in dc["equip"].items()},
                "max_racks": cfg.DC_MAX_RACKS,
                "racks": [_rack_json(r) for r in dc["racks"]],
            }
            for dc in dcs
        ],
        "contracts": [_contract_json(c) for c in own],
        "offers": [_contract_json(c) for c in offers],
        "market_share": [{"region_id": s["region_id"], "company_id": s["company_id"], "share": s["share"]}
                         for s in shares],
        "templates": [{"id": t["id"], "name": t["name"], "layout": json.loads(t["layout_json"])} for t in templates],
        "milestones": {m["code"]: m["reached_tick"] for m in milestones},
        "milestone_defs": {code: {"name": name, "reward_cents": reward} for code, (name, reward) in cfg.MILESTONES.items()},
        "events": [
            {"id": e["id"], "tick": e["tick"], "kind": e["kind"], "region_id": e["region_id"],
             "ends_tick": e["ends_tick"], **json.loads(e["payload_json"])}
            for e in ev_rows
        ],
        "latest_event_id": latest,
    }
