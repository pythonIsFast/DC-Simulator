"""Central tunable game constants. All values are rough estimates for balancing.

Money values are in integer cents. Hardware stats live in data/hardware.py.
"""

# --- Time ---
# Real seconds that one in-game hour (tick) takes at speed 1x.
SECONDS_PER_TICK_1X = 4.0
ALLOWED_SPEEDS = (0, 1, 2, 5)
# Upper bound of ticks simulated in one catch-up (offline progress), 30 days.
MAX_CATCHUP_TICKS = 24 * 30

# --- Start ---
START_CASH_CENTS = 250_000_00
AI_START_CASH_CENTS = 5_000_000_00
MIN_AI_RIVALS = 0
MAX_AI_RIVALS = 5

# --- Validation ---
USERNAME_MIN, USERNAME_MAX = 3, 32
PASSWORD_MIN = 8
NAME_MAX = 40

# --- Rack rules ---
RACK_U = 42
RACK_SHELL_CENTS = 600_00
SELL_BACK_RATIO = 0.5                 # refund when removing hardware
RACK_FEED_LIMIT_W = 12_000            # hard ceiling per rack, whatever the PDUs say
MAX_PER_RACK = {"pdu": 2, "switch_tor": 2, "ups": 1}
EMPTY_U_HEAT_PENALTY = 0.004          # extra heat per empty U without blanking panel (if rack has servers)
MAX_TEMPLATES = 20

# --- Datacenter ---
DC_MAX_RACKS = 20
DC_MAX_PER_REGION = 3
DC_BUILD_BASE_CENTS = 60_000_00       # multiplied by the region land cost index
DC_BASE_POWER_KW = 120
DC_BASE_COOLING_KW = 60
DC_MAX_EQUIPMENT_QTY = 20             # per equipment type and datacenter
PUE_BASE = 1.10                       # facility power / IT power at cool climate
PUE_PER_DEGREE = 0.012                # added per degree C above PUE_REF_TEMP
PUE_REF_TEMP_C = 5.0
HEATWAVE_COOLING_FACTOR = 0.8
THERMAL_SOFT_LIMIT = 1.3              # heat up to 1.3x cooling degrades perf to 50%, above = shutdown
POWER_SPIKE_FACTOR = 1.5

# --- Running costs (cents per tick) ---
DC_RENT_CENTS_PER_TICK = 450          # multiplied by land cost index
STAFF_CENTS_PER_RACK_TICK = 60
REPAIR_COST_CENTS = 200_00

# --- Incidents (probability per rack and tick) ---
P_PDU_FAILURE = 0.0002
P_SWITCH_FAILURE = 0.00015
P_CABLE_FAULT = 0.0003
INCIDENT_DURATION_TICKS = (4, 10)
# Region events (probability per region with a human datacenter and tick)
P_GRID_OUTAGE = 0.0015
P_HEATWAVE = 0.002
P_POWER_SPIKE = 0.0015
P_MARKET_BOOM = 0.0012
GRID_OUTAGE_TICKS = (3, 8)
HEATWAVE_TICKS = (12, 48)
POWER_SPIKE_TICKS = (24, 72)
MARKET_BOOM_TICKS = (48, 96)
MARKET_BOOM_FACTOR = 1.25

# --- Market and contracts ---
REGION_DEMAND_BASE_UNITS = 15_000     # normalized units per demand_index point
DEMAND_GROWTH_PER_TICK = 0.004 / 24   # linear growth, +0.4 % per day
BASE_RATE_CENTS = 10                  # revenue per normalized unit and tick
UNIT_WEIGHT = {"cpu": 1.0, "storage_tb": 1 / 6, "gpu": 3.0}
KIND_RESOURCE = {"web": "cpu", "compute": "cpu", "storage": "storage_tb", "ai": "gpu"}
KIND_RATE_MULT = {"web": 1.0, "compute": 1.1, "storage": 1.0, "ai": 2.0}
KIND_WEIGHTS = {"web": 0.4, "compute": 0.2, "storage": 0.25, "ai": 0.15}
KIND_SIZE_RANGE = {"web": (8, 120), "compute": (40, 400), "storage": (50, 1500), "ai": (10, 120)}
PREMIUM_CHANCE = 0.25
PREMIUM_RATE_MULT = 1.35
OFFERS_PER_DAY_MAX = 3.0              # per region when the market is empty
MAX_OPEN_OFFERS_PER_REGION = 8
OFFER_LIFETIME_TICKS = 5 * 24
CONTRACT_DAYS = (7, 45)
MAX_ACTIVE_CONTRACTS = 40
SLA_BREACH_TICKS = 48                 # consecutive unserved ticks until breach
CANCEL_PENALTY_RATIO = 0.5            # of the contract's penalty

# --- AI rivals (abstract capacity model) ---
AI_RATE_FACTOR = 0.9
AI_COST_CENTS_PER_UNIT_TICK = 4
AI_CAPEX_CENTS_PER_UNIT = 14_000
AI_START_SHARE = 0.06
AI_TOTAL_MAX_SHARE = 0.6              # AIs together never expand beyond this share of a region
AI_STRATEGIES = {
    "aggressive": {"target_share": 0.35, "growth": 0.04, "invest_frac": 0.25, "expand_prob": 0.25},
    "balanced": {"target_share": 0.28, "growth": 0.025, "invest_frac": 0.15, "expand_prob": 0.12},
    "frugal": {"target_share": 0.20, "growth": 0.015, "invest_frac": 0.08, "expand_prob": 0.05},
}

# --- Milestones: code -> (name, reward in cents) ---
MILESTONES = {
    "first_datacenter": ("First datacenter built", 5_000_00),
    "first_rack_full": ("First fully mounted rack", 10_000_00),
    "first_redundant_rack": ("First fully redundant rack", 8_000_00),
    "first_contract": ("First customer contract", 5_000_00),
    "first_new_region": ("Expanded to a second region", 25_000_00),
    "ten_racks": ("Ten racks online", 20_000_00),
    "cash_1m": ("Reached 1,000,000 cash", 50_000_00),
}

# --- Retention (ticks) ---
LEDGER_KEEP_TICKS = 24 * 90
EVENTS_KEEP_TICKS = 24 * 60
OFFER_NAMES_A = ["Blue", "Rapid", "Nimbus", "Quantum", "Pixel", "Atlas", "Nova", "Cobalt", "Lumen", "Vertex",
                 "Orbit", "Delta", "Pioneer", "Helix", "Summit", "Zephyr"]
OFFER_NAMES_B = ["Games", "Shop", "Media", "Bank", "Labs", "Mobility", "Health", "Analytics", "Stream",
                 "Logistics", "Robotics", "Learning", "Travel", "Foods", "Energy", "Social"]
