"""Central tunable game constants. All values are rough estimates for balancing.

Money values are in integer cents. Hardware stats live in data/hardware.py.
"""

# --- Time ---
# Real seconds that one in-game hour (tick) takes at speed 1x.
SECONDS_PER_TICK_1X = 2.0
ALLOWED_SPEEDS = (0, 1, 2, 5)
# Upper bound of ticks simulated in one catch-up (offline progress), 30 days.
MAX_CATCHUP_TICKS = 24 * 30

# --- Start ---
START_CASH_CENTS = 250_000_00
AI_START_CASH_CENTS = 2_000_000_00
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
MAX_PER_RACK = {"pdu": 2, "switch_tor": 2, "ups": 1, "fan_panel": 2}
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
STAFF_CENTS_PER_RACK_TICK = 0         # replaced by individual salaries (see staff.py)
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
BASE_RATE_CENTS = 25                  # revenue per normalized unit and tick
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
AI_COST_CENTS_PER_UNIT_TICK = 12
AI_CAPEX_CENTS_PER_UNIT = 14_000
AI_START_SHARE = 0.04
AI_TOTAL_MAX_SHARE = 0.6              # AIs together never expand beyond this share of a region
AI_STRATEGIES = {
    # growth = share of the regional demand a rival may add per in-game day (kept small: the player has to keep up)
    "aggressive": {"target_share": 0.30, "growth": 0.003, "invest_frac": 0.25, "expand_prob": 0.15},
    "balanced": {"target_share": 0.24, "growth": 0.0018, "invest_frac": 0.15, "expand_prob": 0.08},
    "frugal": {"target_share": 0.16, "growth": 0.001, "invest_frac": 0.08, "expand_prob": 0.04},
}

# --- Company market: startups appear, rivals can be bought ---
MAX_ACTIVE_RIVALS = 8                 # independent AI companies at the same time (founded ones included)
P_NEW_RIVAL_PER_DAY = 0.03            # chance per in-game day that a startup is founded
NEW_RIVAL_MIN_TICK = 24 * 14          # no startups during the first two weeks
STARTUP_CASH_CENTS = 500_000_00
STARTUP_START_SHARE = 0.015           # of the home region demand
STARTUP_NAME_A = ["Nebula", "Quanta", "Stratus", "Vertex", "Helix", "Orbit", "Pylon", "Cobalt", "Zephyr", "Ionic",
                  "Aether", "Kilo", "Tessera", "Lumio", "Strata", "Hexa"]
STARTUP_NAME_B = ["Hosting", "Cloud", "Systems", "Data", "Net", "Compute", "Racks", "Stack", "Works", "Grid"]
STARTUP_COLORS = ["#8b5cf6", "#14b8a6", "#ec4899", "#84cc16", "#06b6d4", "#f97316", "#a3e635", "#e879f9"]
ACQUISITION_PREMIUM = 1.0             # price = installed capacity * AI capex * premium; the rival's cash stays with the sellers
FEW_RIVALS = 3                        # below this many rivals new startups appear faster
FEW_RIVALS_BOOST = 3.0

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

# --- Staff (technicians build approved plans and repair faster, admins plan and prevent incidents) ---
ROLES = ("technician", "admin", "sales")
ROLE_BASE_SALARY_CENTS = {"technician": 1_400, "admin": 2_000, "sales": 1_700}   # per tick at skill 1
SALARY_PER_SKILL = 0.3                  # salary = base * (0.7 + 0.3 * skill)
HIRE_COST_TICKS = 40                    # signing cost = salary * this
MAX_SKILL = 5
XP_PER_LEVEL = 8                        # work orders / proposals needed per skill level (times current skill)
CANDIDATE_POOL = 5
SALES_RATE_BONUS_PER_SKILL = 0.03        # better prices negotiated by skilled sales staff
CANDIDATE_LIFETIME_TICKS = 5 * 24
MAX_EMPLOYEES = 200                     # absolute upper bound; the real limit grows with the company (staff.max_employees)
EMPLOYEES_BASE = 5
EMPLOYEES_PER_DC = 3
EMPLOYEES_PER_RACK = 1
TECH_SPEED_PER_SKILL = 0.35             # work speed = 1 + 0.35 * (skill - 1)
NO_TECH_REPAIR_FACTOR = 2.0             # incident duration multiplier without any technician
ADMIN_INCIDENT_REDUCTION = 0.06         # per admin skill point, at most 60 %
MAX_OPEN_PROPOSALS = 5
PROPOSALS_PER_ADMIN_PER_DAY = 2
PROPOSAL_LIFETIME_TICKS = 4 * 24
FIRST_NAMES = ["Alex", "Maria", "Jonas", "Lena", "Tobias", "Sofia", "Daniel", "Mia", "Lukas", "Emma", "Noah", "Hannah",
               "Felix", "Clara", "Jan", "Nina", "Paul", "Sara", "Max", "Eva"]
LAST_NAMES = ["Becker", "Fischer", "Weber", "Hoffmann", "Keller", "Schulz", "Wagner", "Richter", "Klein", "Wolf", "Neumann",
              "Braun", "Krueger", "Hartmann", "Lang", "Vogel", "Roth", "Frank", "Berger", "Winter"]

# --- Admin pace and build times (ticks = in-game hours) ---
PROPOSAL_INTERVAL_TICKS = 5 * 24         # each admin suggests at most one plan every 5 days
FIRST_PROPOSAL_DELAY_TICKS = 2 * 24      # a new admin needs two days to get going
BUILD_TICKS_RACK_BASE = 24
BUILD_TICKS_PER_ITEM = 1.0
BUILD_TICKS_EXTEND_BASE = 12
BUILD_TICKS_REBUILD_BASE = 18
BUILD_TICKS_REBUILD_PER_ITEM = 1.5
BUILD_TICKS_DC = 5 * 24
BUILD_TICKS_UPGRADE = {"dc_agg": 24, "dc_agg_big": 36, "dc_crac_small": 24, "dc_crac": 36, "dc_chiller": 72, "dc_feed": 48, "dc_feed_big": 72}
MAINTENANCE_DOWNTIME_TICKS = 6           # a rack that is rebuilt is offline for a short time
