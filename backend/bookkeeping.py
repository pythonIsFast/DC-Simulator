"""Small helpers to write ledger entries and events."""
import json


def book(db, world_id, company_id, tick, category, cents, description=""):
    """Add a ledger entry. Does NOT change cash, callers update cash themselves."""
    if cents:
        db.execute(
            "INSERT INTO ledger (world_id, company_id, tick, category, amount_cents, description) VALUES (?, ?, ?, ?, ?, ?)",
            (world_id, company_id, tick, category, int(cents), description),
        )


def add_event(db, world_id, tick, kind, message, company_id=None, region_id=None, ends_tick=None, **payload):
    """Add an event. company_id NULL means visible to everyone in the world."""
    payload["message"] = message
    cur = db.execute(
        "INSERT INTO events (world_id, tick, kind, company_id, region_id, ends_tick, payload_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (world_id, tick, kind, company_id, region_id, ends_tick, json.dumps(payload)),
    )
    return cur.lastrowid


def change_cash(db, company_id, cents):
    db.execute("UPDATE companies SET cash_cents = cash_cents + ? WHERE id = ?", (int(cents), company_id))
