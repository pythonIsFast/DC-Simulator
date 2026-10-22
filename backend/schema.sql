-- Datacenter Tycoon schema. Money is stored as integer cents.
-- All game data hangs off a world (world_id) to allow multiplayer later.

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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id    INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_ai       INTEGER NOT NULL DEFAULT 0,
    ai_strategy TEXT,                                    -- e.g. aggressive | balanced | frugal
    color       TEXT NOT NULL DEFAULT '#4ea1ff',
    cash_cents  INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
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
    avg_temp_c            REAL NOT NULL,                 -- drives cooling cost
    land_cost_index       REAL NOT NULL,
    unlocked              INTEGER NOT NULL DEFAULT 0,    -- region available for building
    UNIQUE (world_id, code)
);

CREATE TABLE IF NOT EXISTS datacenters (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id          INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    region_id         INTEGER NOT NULL REFERENCES regions(id),
    name              TEXT NOT NULL,
    power_capacity_kw REAL NOT NULL,
    cooling_kw        REAL NOT NULL,
    built_tick        INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_dc_company ON datacenters(company_id);

-- Global hardware catalog, seeded from a tunable data file (Phase 3).
CREATE TABLE IF NOT EXISTS hardware_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,   -- server_cpu | server_storage | server_gpu | switch_tor | switch_agg | pdu | ups | patch_panel | cable_mgmt | blank
    name        TEXT NOT NULL,
    u_height    INTEGER NOT NULL,
    power_w     REAL NOT NULL DEFAULT 0,
    heat_w      REAL NOT NULL DEFAULT 0,
    ports       INTEGER NOT NULL DEFAULT 0,
    price_cents INTEGER NOT NULL,
    attrs_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS racks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    datacenter_id INTEGER NOT NULL REFERENCES datacenters(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    u_total       INTEGER NOT NULL DEFAULT 42,
    slot          INTEGER NOT NULL DEFAULT 0,            -- position in the room
    created_tick  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_racks_dc ON racks(datacenter_id);

CREATE TABLE IF NOT EXISTS rack_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rack_id          INTEGER NOT NULL REFERENCES racks(id) ON DELETE CASCADE,
    hardware_type_id INTEGER NOT NULL REFERENCES hardware_types(id),
    u_start          INTEGER NOT NULL,                   -- lowest occupied U (1-based)
    meta_json        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_rack_items_rack ON rack_items(rack_id);

CREATE TABLE IF NOT EXISTS rack_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Customer services/contracts. company_id IS NULL means open offer on the market.
CREATE TABLE IF NOT EXISTS contracts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id               INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id             INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    region_id              INTEGER REFERENCES regions(id),
    kind                   TEXT NOT NULL,                -- web | storage | compute | ai
    name                   TEXT NOT NULL,
    requirements_json      TEXT NOT NULL DEFAULT '{}',
    revenue_cents_per_tick INTEGER NOT NULL,
    penalty_cents          INTEGER NOT NULL DEFAULT 0,
    offered_tick           INTEGER NOT NULL,
    start_tick             INTEGER,
    end_tick               INTEGER,
    status                 TEXT NOT NULL DEFAULT 'offered' -- offered | active | completed | breached | expired
);
CREATE INDEX IF NOT EXISTS idx_contracts_world ON contracts(world_id, status);

CREATE TABLE IF NOT EXISTS research (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tech_code     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'locked',        -- locked | researching | done
    progress      REAL NOT NULL DEFAULT 0,
    done_tick     INTEGER,
    UNIQUE (company_id, tech_code)
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id     INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    tick         INTEGER NOT NULL,
    kind         TEXT NOT NULL,                          -- e.g. power_outage | heatwave | market_boom
    company_id   INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    region_id    INTEGER REFERENCES regions(id),
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_world ON events(world_id, tick);

CREATE TABLE IF NOT EXISTS ledger (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id     INTEGER NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tick         INTEGER NOT NULL,
    category     TEXT NOT NULL,                          -- revenue | power | hardware | rent | penalty | reward ...
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
