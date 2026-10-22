"""Central tunable game constants. All values are rough estimates for balancing."""

# --- Time ---
# Real seconds that one in-game hour (tick) takes at speed 1x.
SECONDS_PER_TICK_1X = 10.0
ALLOWED_SPEEDS = (0, 1, 2, 5)
# Upper bound of ticks simulated in one catch-up (offline progress), 30 days.
MAX_CATCHUP_TICKS = 24 * 30

# --- Economy ---
START_CASH_CENTS = 250_000_00        # 250,000 in game currency
AI_START_CASH_CENTS = 5_000_000_00   # AIs start bigger so they act as real competition
MIN_AI_RIVALS = 0
MAX_AI_RIVALS = 5

# --- Validation ---
USERNAME_MIN, USERNAME_MAX = 3, 32
PASSWORD_MIN = 8
NAME_MAX = 40
