"""World clock: converts real time into ticks and runs catch-up.

The world stores its tick counter and the timestamp of the last update.
Whenever the world is read or a command arrives, `catch_up` advances it by the
elapsed real time (also covers offline progress after login).
"""
import time

from data.game_config import CATCHUP_TICKS_PER_REQUEST, MAX_CATCHUP_TICKS, SECONDS_PER_TICK_1X

# Simulation steps executed once per tick: callables fn(db, world_row, tick).
# Later phases register economy, power/heat, contracts and AI here.
TICK_HANDLERS = []


def catch_up(db, world_id, now=None):
    """Advance a world to the current time. Returns the fresh world row.

    Runs inside one IMMEDIATE transaction so concurrent requests cannot
    double-count elapsed time.
    """
    now = time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        world = db.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
        if world is None:
            db.execute("ROLLBACK")
            return None

        elapsed = max(0.0, now - world["last_update_ts"])
        progress = world["tick_progress"] + elapsed * world["speed"] / SECONDS_PER_TICK_1X
        ticks = int(progress)
        progress -= ticks
        if ticks > MAX_CATCHUP_TICKS:
            # Offline gap too long: drop the excess instead of simulating it.
            ticks = MAX_CATCHUP_TICKS
            progress = 0.0
        # Only part of the gap is simulated now; the remaining ticks stay in tick_progress
        # (integer part) and are simulated by the following requests.
        run = min(ticks, CATCHUP_TICKS_PER_REQUEST)
        progress += ticks - run

        tick = world["tick"]
        for _ in range(run):
            tick += 1
            for handler in TICK_HANDLERS:
                handler(db, world, tick)

        db.execute(
            "UPDATE worlds SET tick = ?, tick_progress = ?, last_update_ts = ? WHERE id = ?",
            (tick, progress, now, world_id),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return db.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
