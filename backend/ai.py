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


def run_ai_day(db, world, tick, rng):
    wid = world["id"]
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
