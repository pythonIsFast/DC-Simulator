-- Datacenter Tycoon schema (version 2). Money is stored as integer cents.
-- All game data hangs off a world (world_id) to allow multiplayer later.
-- Bump SCHEMA_VERSION in db.py when changing this file (dev DBs are backed up and recreated).

PRAGMA user_version = 2;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS worlds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    owner_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode           TEXT NOT NULL DEFAULT 'singleplayer', -- singleplayer | multiplayer
    seed           INTEGER NOT NULL,
    tick           INTEGER NOT NULL DEFAULT 0,           -- 1 tick = 1 in-game hour
    tick_progress  REAL NOT NULL DEFAULT 0,              -- fractional tick carry-over
    speed          INTEGER NOT NULL DEFAULT 1,           -- 0 = paused, 1, 2, 5
    last_update_ts REAL NOT NULL,                        -- unix time of last catch-up
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_worlds_owner ON worlds(owner_user_id);

-- Player and AI companies. user_id IS NULL means AI rival.
CREATE TABLE IF NOT EXISTS companies (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id           INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    is_ai              INTEGER NOT NULL DEFAULT 0,
    ai_strategy        TEXT,                             -- aggressive | balanced | frugal
    color              TEXT NOT NULL DEFAULT '#4ea1ff',
    cash_cents         INTEGER NOT NULL,
    last_revenue_cents INTEGER NOT NULL DEFAULT 0,       -- of the latest tick
    last_expense_cents INTEGER NOT NULL DEFAULT 0,       -- of the latest tick
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (world_id, name)
);
CREATE INDEX IF NOT EXISTS idx_companies_world ON companies(world_id);
CREATE INDEX IF NOT EXISTS idx_companies_user ON companies(user_id);

CREATE TABLE IF NOT EXISTS regions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id              INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    code                  TEXT NOT NULL,
    name                  TEXT NOT NULL,
    lat                   REAL NOT NULL,
    lon                   REAL NOT NULL,
    demand_index          REAL NOT NULL,                 -- relative customer demand
    power_price_cents_kwh REAL NOT NULL,
    avg_temp_c            REAL NOT NULL,                 -- drives cooling overhead (PUE)
    land_cost_index       REAL NOT NULL,
    UNIQUE (world_id, code)
);

CREATE TABLE IF NOT EXISTS datacenters (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id          INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    region_id         INTEGER NOT NULL REFERENCES regions(id),
    name              TEXT NOT NULL,
    power_capacity_kw REAL NOT NULL,                     -- base grid connection
    cooling_kw        REAL NOT NULL,                     -- base room cooling
    build_cost_cents  INTEGER NOT NULL DEFAULT 0,
    built_tick        INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active',
    -- runtime values written by the simulation
    perf              REAL NOT NULL DEFAULT 1,           -- 0..1 thermal/power throttle
    heat_kw           REAL NOT NULL DEFAULT 0,
    cooling_cap_kw    REAL NOT NULL DEFAULT 0,
    facility_kw       REAL NOT NULL DEFAULT 0,           -- IT power incl. cooling overhead
    util              REAL NOT NULL DEFAULT 0            -- 0..1 sold share of capacity
);
CREATE INDEX IF NOT EXISTS idx_dc_company ON datacenters(company_id);

-- Datacenter-level equipment: aggregation switches, cooling units, power feeds.
CREATE TABLE IF NOT EXISTS dc_equipment (
    datacenter_id    INTEGER NOT NULL REFERENCES datacenters(id) ON DELETE CASCADE,
    hardware_type_id INTEGER NOT NULL REFERENCES hardware_types(id),
    qty              INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (datacenter_id, hardware_type_id)
);

-- Global hardware catalog, seeded from data/hardware.py on startup.
CREATE TABLE IF NOT EXISTS hardware_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    u_height    INTEGER NOT NULL,
    power_w     REAL NOT NULL DEFAULT 0,
    heat_w      REAL NOT NULL DEFAULT 0,
    ports       INTEGER NOT NULL DEFAULT 0,
    price_cents INTEGER NOT NULL,
    attrs_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS racks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    datacenter_id    INTEGER NOT NULL REFERENCES datacenters(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    u_total          INTEGER NOT NULL DEFAULT 42,
    slot             INTEGER NOT NULL DEFAULT 0,         -- position in the room
    created_tick     INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ok',         -- ok | down (timed) | tripped (breaker)
    down_until_tick  INTEGER,
    down_reason      TEXT,
    -- runtime values written by the simulation
    online           INTEGER NOT NULL DEFAULT 0,
    offline_reason   TEXT,
    load_w           REAL NOT NULL DEFAULT 0,
    heat_w           REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_racks_dc ON racks(datacenter_id);

CREATE TABLE IF NOT EXISTS rack_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rack_id          INTEGER NOT NULL REFERENCES racks(id) ON DELETE CASCADE,
    hardware_type_id INTEGER NOT NULL REFERENCES hardware_types(id),
    u_start          INTEGER NOT NULL,                   -- lowest occupied U (1 = bottom)
    meta_json        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_rack_items_rack ON rack_items(rack_id);

CREATE TABLE IF NOT EXISTS rack_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    layout_json TEXT NOT NULL,                           -- [{"code": ..., "u_start": ...}]
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Customer services/contracts. company_id IS NULL means open offer on the market.
CREATE TABLE IF NOT EXISTS contracts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id               INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id             INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    region_id              INTEGER NOT NULL REFERENCES regions(id),
    kind                   TEXT NOT NULL,                -- web | compute | storage | ai
    name                   TEXT NOT NULL,
    resource               TEXT NOT NULL,                -- cpu | storage_tb | gpu
    units                  REAL NOT NULL,                -- amount of the resource
    units_eq               REAL NOT NULL,                -- normalized size for market share
    premium                INTEGER NOT NULL DEFAULT 0,   -- 1 = needs redundant racks
    revenue_cents_per_tick INTEGER NOT NULL,
    penalty_cents          INTEGER NOT NULL DEFAULT 0,
    duration_ticks         INTEGER NOT NULL,
    offered_tick           INTEGER NOT NULL,
    offer_expires_tick     INTEGER NOT NULL,
    start_tick             INTEGER,
    end_tick               INTEGER,
    sla_fail_streak        INTEGER NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL DEFAULT 'offered' -- offered | active | completed | breached | cancelled | expired
);
CREATE INDEX IF NOT EXISTS idx_contracts_world ON contracts(world_id, status);
CREATE INDEX IF NOT EXISTS idx_contracts_company ON contracts(company_id, status);

-- Reserved for the research tree (cut from the first release).
CREATE TABLE IF NOT EXISTS research (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tech_code     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'locked',        -- locked | researching | done
    progress      REAL NOT NULL DEFAULT 0,
    done_tick     INTEGER,
    UNIQUE (company_id, tech_code)
);

-- Abstract capacity of AI rivals per region (they do not build real racks).
CREATE TABLE IF NOT EXISTS ai_state (
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    region_id  INTEGER NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    capacity   REAL NOT NULL DEFAULT 0,                  -- in normalized units
    PRIMARY KEY (company_id, region_id)
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id     INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    tick         INTEGER NOT NULL,
    kind         TEXT NOT NULL,                          -- grid_outage | heatwave | power_spike | market_boom | milestone | ...
    company_id   INTEGER REFERENCES companies(id) ON DELETE CASCADE, -- NULL = visible to everyone
    region_id    INTEGER REFERENCES regions(id),
    ends_tick    INTEGER,                                -- for region events with a duration
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_world ON events(world_id, id);

CREATE TABLE IF NOT EXISTS ledger (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id     INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tick         INTEGER NOT NULL,
    category     TEXT NOT NULL,                          -- revenue | power | rent | staff | hardware | penalty | reward ...
    amount_cents INTEGER NOT NULL,                       -- positive = income, negative = expense
    description  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ledger_company ON ledger(company_id, tick);

CREATE TABLE IF NOT EXISTS market_share (
    world_id   INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    region_id  INTEGER NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    share      REAL NOT NULL DEFAULT 0,                  -- 0..1
    PRIMARY KEY (region_id, company_id)
);

CREATE TABLE IF NOT EXISTS milestones (
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    code         TEXT NOT NULL,
    reached_tick INTEGER NOT NULL,
    PRIMARY KEY (company_id, code)
);

-- Audit trail of every client command (cheat analysis, replays, debugging).
CREATE TABLE IF NOT EXISTS command_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id     INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tick         INTEGER NOT NULL,
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ok           INTEGER NOT NULL,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cmdlog_world ON command_log(world_id, id);

-- ---------------------------------------------------------------- staff (added without a schema bump: new tables only)
CREATE TABLE IF NOT EXISTS employees (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id            INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    role                  TEXT NOT NULL,                 -- technician | admin
    skill                 INTEGER NOT NULL DEFAULT 1,    -- 1..5
    xp                    INTEGER NOT NULL DEFAULT 0,
    salary_cents_per_tick INTEGER NOT NULL,
    hired_tick            INTEGER NOT NULL,
    status                TEXT NOT NULL DEFAULT 'idle',  -- idle | working
    order_id              INTEGER
);
CREATE INDEX IF NOT EXISTS idx_employees_company ON employees(company_id);

-- Job market: people the company could hire.
CREATE TABLE IF NOT EXISTS candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id            INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    role                  TEXT NOT NULL,
    skill                 INTEGER NOT NULL,
    salary_cents_per_tick INTEGER NOT NULL,
    hire_cost_cents       INTEGER NOT NULL,
    expires_tick          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_company ON candidates(company_id);

-- Plans suggested by admins; the player approves or rejects them.
CREATE TABLE IF NOT EXISTS proposals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    admin_id     INTEGER,
    kind         TEXT NOT NULL,                          -- new_rack | new_datacenter | upgrade
    title        TEXT NOT NULL,
    plan_json    TEXT NOT NULL,
    summary_json TEXT NOT NULL,                          -- human readable preview for the client
    cost_cents   INTEGER NOT NULL,
    est_ticks    INTEGER NOT NULL,
    created_tick INTEGER NOT NULL,
    expires_tick INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open'            -- open | approved | rejected | expired
);
CREATE INDEX IF NOT EXISTS idx_proposals_company ON proposals(company_id, status);

-- Approved plans waiting for or being worked on by a technician.
CREATE TABLE IF NOT EXISTS work_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    proposal_id  INTEGER,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    plan_json    TEXT NOT NULL,
    cost_cents   INTEGER NOT NULL,                       -- already paid, refunded if the plan fails
    total_ticks  REAL NOT NULL,
    progress     REAL NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'queued',         -- queued | in_progress | done | failed
    employee_id  INTEGER,
    created_tick INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_company ON work_orders(company_id, status);
