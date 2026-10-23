"""Rule-based AI rivals using an abstract capacity model (no real racks).

Once per in-game day every rival earns money from the demand it serves,
pays running costs for its capacity and invests part of its cash into more
capacity, following its strategy. Humans have priority in the market, so
growing players push rival shares down (see market.compute_market).
"""
from bookkeeping import add_event
from data import game_config as cfg
import market


def init_rival(db, company_id, regions, home_region_id):
    """Give a new rival a small starting capacity in its home region."""
    for r in regions:
        capacity = 0.0
        if r["id"] == home_region_id:
            capacity = market.region_demand(r, 0) * cfg.AI_START_SHARE
        db.execute("INSERT INTO ai_state (company_id, region_id, capacity) VALUES (?, ?, ?)",
                   (company_id, r["id"], capacity))


def _capacity_values(db, world_id, tick, info=None):
    """Per AI company: build value of the capacity it actually serves (half the capex, like selling hardware)."""
    if info is None:
        info = market.compute_market(db, world_id, tick, persist=False)
    units = {}
    for d in info.values():
        for cid, u in d["ai"].items():
            units[cid] = units.get(cid, 0.0) + u
    return {cid: int(u * cfg.AI_CAPEX_CENTS_PER_UNIT * cfg.SELL_BACK_RATIO) for cid, u in units.items()}


def worth_by_company(db, world_id, tick, info=None):
    """Approximate net worth of every AI company: cash plus the value of its served capacity."""
    values = _capacity_values(db, world_id, tick, info)
    return {
        c["id"]: int(c["cash_cents"] + values.get(c["id"], 0))
        for c in db.execute("SELECT id, cash_cents FROM companies WHERE world_id = ? AND is_ai = 1", (world_id,))
    }


def installed_units(db, world_id):
    """Installed (abstract) capacity per AI company and region: {company_id: {region_id: units}}."""
    out = {}
    for r in db.execute(
        "SELECT a.company_id, a.region_id, a.capacity FROM ai_state a JOIN companies c ON c.id = a.company_id"
        " WHERE c.world_id = ? AND c.is_ai = 1 AND a.capacity > 0", (world_id,)):
        out.setdefault(r["company_id"], {})[r["region_id"]] = r["capacity"]
    return out


def acquisition_price(units_by_region):
    """What a rival costs: its installed capacity at (new-build) capex times the premium. Its cash stays with the sellers."""
    return int(sum(units_by_region.values()) * cfg.AI_CAPEX_CENTS_PER_UNIT * cfg.ACQUISITION_PREMIUM)


def prices_by_company(db, world_id):
    units = installed_units(db, world_id)
    return {
        c["id"]: acquisition_price(units.get(c["id"], {}))
        for c in db.execute("SELECT id FROM companies WHERE world_id = ? AND is_ai = 1", (world_id,))
    }


def _startup_name(db, wid, rng):
    taken = {r["name"] for r in db.execute("SELECT name FROM companies WHERE world_id = ?", (wid,))}
    for _ in range(40):
        name = "%s %s" % (rng.choice(cfg.STARTUP_NAME_A), rng.choice(cfg.STARTUP_NAME_B))
        if name not in taken:
            return name
    n = 2
    while "Nebula Hosting %d" % n in taken:
        n += 1
    return "Nebula Hosting %d" % n


def found_rival(db, world, tick, rng):
    """Create a small startup rival in a random region."""
    wid = world["id"]
    regions = db.execute("SELECT * FROM regions WHERE world_id = ? ORDER BY id", (wid,)).fetchall()
    home = rng.choices(regions, [r["demand_index"] for r in regions])[0]
    name = _startup_name(db, wid, rng)
    strategy = rng.choice(sorted(cfg.AI_STRATEGIES))
    cur = db.execute(
        "INSERT INTO companies (world_id, user_id, name, is_ai, ai_strategy, color, cash_cents)"
        " VALUES (?, NULL, ?, 1, ?, ?, ?)",
        (wid, name, strategy, rng.choice(cfg.STARTUP_COLORS), cfg.STARTUP_CASH_CENTS))
    cid = cur.lastrowid
    for r in regions:
        capacity = market.region_demand(r, tick) * cfg.STARTUP_START_SHARE if r["id"] == home["id"] else 0.0
        db.execute("INSERT INTO ai_state (company_id, region_id, capacity) VALUES (?, ?, ?)", (cid, r["id"], capacity))
        db.execute("INSERT INTO market_share (world_id, region_id, company_id, share) VALUES (?, ?, ?, 0)",
                   (wid, r["id"], cid))
    add_event(db, wid, tick, "rival_founded", "New competitor %s enters the market in %s" % (name, home["name"]),
              region_id=home["id"])
    return cid


def maybe_found_rival(db, world, tick, rng):
    """Once per day a startup may enter the market; more likely while there are few rivals."""
    wid = world["id"]
    if tick < cfg.NEW_RIVAL_MIN_TICK:
        return
    ai_total = db.execute("SELECT COUNT(*) FROM companies WHERE world_id = ? AND is_ai = 1", (wid,)).fetchone()[0]
    if ai_total == 0 or ai_total >= cfg.MAX_ACTIVE_RIVALS:
        return  # worlds created without rivals stay that way (buying the last one founds a replacement at once)
    chance = cfg.P_NEW_RIVAL_PER_DAY * (cfg.FEW_RIVALS_BOOST if ai_total < cfg.FEW_RIVALS else 1.0)
    if rng.random() < chance:
        found_rival(db, world, tick, rng)


def run_ai_day(db, world, tick, rng):
    wid = world["id"]
    maybe_found_rival(db, world, tick, rng)
    info = market.compute_market(db, wid, tick, persist=False)
    rivals = db.execute("SELECT * FROM companies WHERE world_id = ? AND is_ai = 1 ORDER BY id", (wid,)).fetchall()
    if not rivals:
        return
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM regions WHERE world_id = ?", (wid,))}
    cash = {c["id"]: c["cash_cents"] for c in rivals}

    # Daily income and running costs.
    for c in rivals:
        revenue = cost = 0.0
        for d in info.values():
            revenue += d["ai"].get(c["id"], 0.0) * cfg.BASE_RATE_CENTS * cfg.AI_RATE_FACTOR
            cost += d["ai_cap"].get(c["id"], 0.0) * cfg.AI_COST_CENTS_PER_UNIT_TICK
        cash[c["id"]] += int((revenue - cost) * 24)

    caps = {rid: dict(d["ai_cap"]) for rid, d in info.items()}
    order = list(rivals)
    rng.shuffle(order)
    for c in order:
        p = cfg.AI_STRATEGIES.get(c["ai_strategy"] or "balanced", cfg.AI_STRATEGIES["balanced"])
        candidates = []
        for rid, d in info.items():
            demand = d["demand"]
            if demand <= 0:
                continue
            total_ai = sum(caps[rid].values())
            own = caps[rid].get(c["id"], 0.0)
            if total_ai / demand >= cfg.AI_TOTAL_MAX_SHARE or own / demand >= p["target_share"]:
                continue
            if own <= 0 and rng.random() > p["expand_prob"]:
                continue  # expanding into a new region is a rare decision
            taken = (sum(d["human"].values()) + total_ai) / demand
            candidates.append((1.0 - taken + (0.3 if own > 0 else 0.0), rid))
        if not candidates:
            continue
        _, rid = max(candidates)
        d = info[rid]
        demand = d["demand"]
        total_ai = sum(caps[rid].values())
        own = caps[rid].get(c["id"], 0.0)
        budget = cash[c["id"]] * p["invest_frac"]
        units = min(
            budget / cfg.AI_CAPEX_CENTS_PER_UNIT,
            p["growth"] * demand,
            p["target_share"] * demand - own,
            cfg.AI_TOTAL_MAX_SHARE * demand - total_ai,
        )
        if units < 1:
            continue
        caps[rid][c["id"]] = own + units
        cash[c["id"]] -= int(units * cfg.AI_CAPEX_CENTS_PER_UNIT)
        db.execute(
            "INSERT INTO ai_state (company_id, region_id, capacity) VALUES (?, ?, ?)"
            " ON CONFLICT(company_id, region_id) DO UPDATE SET capacity = capacity + excluded.capacity",
            (c["id"], rid, units),
        )
        if own <= 0:
            add_event(db, wid, tick, "rival_expansion", "%s expands into %s" % (c["name"], names[rid]), region_id=rid)

    for cid, value in cash.items():
        db.execute("UPDATE companies SET cash_cents = ? WHERE id = ?", (value, cid))
