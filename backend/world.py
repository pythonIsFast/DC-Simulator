"""World model: creation and serialization."""
import random
import time

from data.game_config import AI_START_CASH_CENTS, MAX_AI_RIVALS, MIN_AI_RIVALS, START_CASH_CENTS
from data.world_seed import AI_RIVALS, REGIONS, STARTER_REGION_CODES

PLAYER_COLOR = "#4ea1ff"


def create_world(db, user_id, world_name, company_name, ai_count):
    """Create a singleplayer world with one human company and AI rivals.

    Returns the new world id. The whole creation is one transaction.
    """
    ai_count = max(MIN_AI_RIVALS, min(MAX_AI_RIVALS, ai_count))
    now = time.time()
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = db.execute(
            "INSERT INTO worlds (name, owner_user_id, mode, seed, last_update_ts) VALUES (?, ?, 'singleplayer', ?, ?)",
            (world_name, user_id, random.randrange(2**31), now),
        )
        world_id = cur.lastrowid

        region_ids = {}
        for code, name, lat, lon, demand, power, temp, land in REGIONS:
            cur = db.execute(
                "INSERT INTO regions (world_id, code, name, lat, lon, demand_index, power_price_cents_kwh,"
                " avg_temp_c, land_cost_index, unlocked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (world_id, code, name, lat, lon, demand, power, temp, land,
                 1 if code in STARTER_REGION_CODES else 0),
            )
            region_ids[code] = cur.lastrowid

        company_ids = [_insert_company(db, world_id, user_id, company_name, PLAYER_COLOR, START_CASH_CENTS, None)]
        for name, color, strategy in AI_RIVALS[:ai_count]:
            company_ids.append(_insert_company(db, world_id, None, name, color, AI_START_CASH_CENTS, strategy))

        # Empty market: nobody has customers yet. Rows exist so later phases can just UPDATE.
        for region_id in region_ids.values():
            for company_id in company_ids:
                db.execute(
                    "INSERT INTO market_share (world_id, region_id, company_id, share) VALUES (?, ?, ?, 0)",
                    (world_id, region_id, company_id),
                )
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
        "id": world["id"],
        "name": world["name"],
        "mode": world["mode"],
        "tick": world["tick"],
        "speed": world["speed"],
        "tick_progress": world["tick_progress"],
    }


def company_public(company):
    return {
        "id": company["id"],
        "name": company["name"],
        "is_ai": bool(company["is_ai"]),
        "color": company["color"],
    }


def world_state(db, world, company):
    """Full state snapshot for the client of `company`."""
    rivals = db.execute(
        "SELECT * FROM companies WHERE world_id = ? AND id != ? ORDER BY id", (world["id"], company["id"])
    ).fetchall()
    regions = db.execute("SELECT * FROM regions WHERE world_id = ? ORDER BY id", (world["id"],)).fetchall()
    shares = db.execute(
        "SELECT region_id, company_id, share FROM market_share WHERE world_id = ?", (world["id"],)
    ).fetchall()
    return {
        "world": world_summary(world),
        "company": {**company_public(company), "cash_cents": company["cash_cents"]},
        # Rival cash is hidden from the client on purpose (information advantage).
        "rivals": [company_public(r) for r in rivals],
        "regions": [
            {
                "id": r["id"], "code": r["code"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                "demand_index": r["demand_index"], "power_price_cents_kwh": r["power_price_cents_kwh"],
                "avg_temp_c": r["avg_temp_c"], "land_cost_index": r["land_cost_index"],
                "unlocked": bool(r["unlocked"]),
            }
            for r in regions
        ],
        "market_share": [
            {"region_id": s["region_id"], "company_id": s["company_id"], "share": s["share"]} for s in shares
        ],
    }
