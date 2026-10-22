"""Command registry. Every player action is a command validated server side.

A handler has the signature handler(db, world, company, payload) -> dict and
raises CommandError for invalid input. It runs inside a transaction together
with the command_log entry, so state changes and audit trail stay consistent.
"""
import json

from data.game_config import ALLOWED_SPEEDS, NAME_MAX

HANDLERS = {}


class CommandError(Exception):
    pass


def command(name):
    def register(fn):
        HANDLERS[name] = fn
        return fn

    return register


@command("set_speed")
def set_speed(db, world, company, payload):
    speed = payload.get("speed")
    if speed not in ALLOWED_SPEEDS or isinstance(speed, bool):
        raise CommandError("speed must be one of %s" % (ALLOWED_SPEEDS,))
    # Multiplayer later: replace by a vote or host-only control.
    if world["mode"] != "singleplayer":
        raise CommandError("speed can only be changed in singleplayer worlds")
    db.execute("UPDATE worlds SET speed = ? WHERE id = ?", (speed, world["id"]))
    return {"speed": speed}


@command("rename_company")
def rename_company(db, world, company, payload):
    name = payload.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= NAME_MAX):
        raise CommandError("name must be 1-%d characters" % NAME_MAX)
    name = name.strip()
    taken = db.execute(
        "SELECT 1 FROM companies WHERE world_id = ? AND name = ? AND id != ?",
        (world["id"], name, company["id"]),
    ).fetchone()
    if taken:
        raise CommandError("name already taken in this world")
    db.execute("UPDATE companies SET name = ? WHERE id = ?", (name, company["id"]))
    return {"name": name}


def execute_command(db, world, company, cmd_type, payload):
    """Run a command and log it. Returns (ok, result_or_error)."""
    handler = HANDLERS.get(cmd_type)
    if handler is None:
        return False, "unknown command type"

    db.execute("BEGIN IMMEDIATE")
    try:
        try:
            result = handler(db, world, company, payload)
            ok, error = True, None
        except CommandError as exc:
            # Roll back partial changes of the failed handler, keep only the log entry.
            db.execute("ROLLBACK")
            db.execute("BEGIN IMMEDIATE")
            result, ok, error = None, False, str(exc)
        db.execute(
            "INSERT INTO command_log (world_id, company_id, tick, type, payload_json, ok, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (world["id"], company["id"], world["tick"], cmd_type, json.dumps(payload), 1 if ok else 0, error),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return ok, (result if ok else error)
