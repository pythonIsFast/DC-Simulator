"""Market model: regional demand, market share and customer contract offers."""
import random

from data import game_config as cfg


def boom_factors(db, world_id, tick):
    rows = db.execute(
        "SELECT DISTINCT region_id FROM events WHERE world_id = ? AND kind = 'market_boom' AND ends_tick >= ?",
        (world_id, tick),
    ).fetchall()
    return {r["region_id"]: cfg.MARKET_BOOM_FACTOR for r in rows}


def region_demand(region, tick, boom=1.0):
    growth = 1.0 + cfg.DEMAND_GROWTH_PER_TICK * tick
    return cfg.REGION_DEMAND_BASE_UNITS * region["demand_index"] * growth * boom


def compute_market(db, world_id, tick, persist=True):
    """Per region: demand, units served by humans and AIs, free demand.

    Humans have priority: AI capacity is scaled down when human contracts
    take the demand. Returns {region_id: {...}}.
    """
    regions = db.execute("SELECT * FROM regions WHERE world_id = ?", (world_id,)).fetchall()
    boom = boom_factors(db, world_id, tick)
    info = {}
    for r in regions:
        info[r["id"]] = {
            "demand": region_demand(r, tick, boom.get(r["id"], 1.0)),
            "human": {}, "ai": {}, "ai_cap": {}, "free": 0.0,
        }
    for row in db.execute(
        "SELECT company_id, region_id, SUM(units_eq) AS u FROM contracts"
        " WHERE world_id = ? AND status = 'active' GROUP BY company_id, region_id", (world_id,)
    ):
        info[row["region_id"]]["human"][row["company_id"]] = row["u"]
    for row in db.execute(
        "SELECT a.company_id, a.region_id, a.capacity FROM ai_state a"
        " JOIN companies c ON c.id = a.company_id WHERE c.world_id = ?", (world_id,)
    ):
        if row["capacity"] > 0:
            info[row["region_id"]]["ai_cap"][row["company_id"]] = row["capacity"]

    shares = []
    for rid, d in info.items():
        human_total = sum(d["human"].values())
        remaining = max(0.0, d["demand"] - human_total)
        cap_total = sum(d["ai_cap"].values())
        scale = 1.0 if cap_total <= remaining or cap_total == 0 else remaining / cap_total
        d["ai"] = {cid: cap * scale for cid, cap in d["ai_cap"].items()}
        d["free"] = max(0.0, remaining - sum(d["ai"].values()))
        denom = max(d["demand"], human_total) or 1.0
        for cid, units in d["human"].items():
            shares.append((units / denom, rid, cid))
        for cid, units in d["ai"].items():
            shares.append((units / denom, rid, cid))
    if persist:
        db.execute("UPDATE market_share SET share = 0 WHERE world_id = ?", (world_id,))
        db.executemany("UPDATE market_share SET share = ? WHERE region_id = ? AND company_id = ?", shares)
    return info


def _make_offer(rng, region, tick, free_units):
    kinds, weights = zip(*cfg.KIND_WEIGHTS.items())
    kind = rng.choices(kinds, weights)[0]
    resource = cfg.KIND_RESOURCE[kind]
    lo, hi = cfg.KIND_SIZE_RANGE[kind]
    growth = 1.0 + tick / (24 * 90) * 0.5
    units = max(1, round(rng.uniform(lo, hi) * growth))
    units_eq = units * cfg.UNIT_WEIGHT[resource]
    if units_eq > free_units:
        return None
    premium = 1 if rng.random() < cfg.PREMIUM_CHANCE else 0
    rate = units_eq * cfg.BASE_RATE_CENTS * cfg.KIND_RATE_MULT[kind] * rng.uniform(0.9, 1.15)
    if premium:
        rate *= cfg.PREMIUM_RATE_MULT
    rate = max(1, int(rate))
    days = rng.randint(*cfg.CONTRACT_DAYS)
    name = "%s %s" % (rng.choice(cfg.OFFER_NAMES_A), rng.choice(cfg.OFFER_NAMES_B))
    return {
        "kind": kind, "name": name, "resource": resource, "units": units, "units_eq": units_eq,
        "premium": premium, "rate": rate, "penalty": rate * 24, "duration": days * 24,
    }


def generate_offers(db, world, tick, rng, human_regions, info, minimum=0):
    """Daily: create new open offers where the market still has free demand."""
    world_id = world["id"]
    db.execute(
        "UPDATE contracts SET status = 'expired' WHERE world_id = ? AND status = 'offered' AND offer_expires_tick < ?",
        (world_id, tick),
    )
    for rid in human_regions:
        d = info[rid]
        if d["demand"] <= 0:
            continue
        open_n = db.execute(
            "SELECT COUNT(*) FROM contracts WHERE world_id = ? AND region_id = ? AND status = 'offered'",
            (world_id, rid),
        ).fetchone()[0]
        expected = cfg.OFFERS_PER_DAY_MAX * d["free"] / d["demand"]
        n = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        n = min(max(n, minimum), cfg.MAX_OPEN_OFFERS_PER_REGION - open_n)
        region = db.execute("SELECT * FROM regions WHERE id = ?", (rid,)).fetchone()
        for _ in range(n):
            offer = _make_offer(rng, region, tick, d["free"])
            if offer is None:
                continue
            db.execute(
                "INSERT INTO contracts (world_id, region_id, kind, name, resource, units, units_eq, premium,"
                " revenue_cents_per_tick, penalty_cents, duration_ticks, offered_tick, offer_expires_tick)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (world_id, rid, offer["kind"], offer["name"], offer["resource"], offer["units"],
                 offer["units_eq"], offer["premium"], offer["rate"], offer["penalty"], offer["duration"],
                 tick, tick + cfg.OFFER_LIFETIME_TICKS),
            )


def seed_offers(db, world, tick, region_id, count=3):
    """Create a few offers right away (e.g. after the first datacenter in a region is built)."""
    rng = random.Random(world["seed"] * 7919 + tick * 31 + region_id)
    info = compute_market(db, world["id"], tick, persist=False)
    generate_offers(db, world, tick, rng, {region_id}, info, minimum=count)
