# Datacenter Tycoon (working title)

A 3D datacenter tycoon: build datacenters worldwide, fill self-built racks,
win customer contracts and compete against AI rivals. See [PLAN.md](PLAN.md).

## Structure

```
backend/            Flask API, SQLite, JWT
  app.py            entry point (create_app)
  config.py         paths, secret key (DC_SECRET_KEY or generated instance/secret.key)
  db.py, schema.sql database access, schema (versioned) and hardware seeding
  auth.py           JWT helpers
  clock.py          tick clock and offline catch-up
  sim.py            tick simulation (incidents, power/heat, contracts, costs, milestones)
  racks.py          rack rules and statistics
  market.py         regional demand, market share, customer offers
  ai.py             rule-based AI rivals
  staff.py          employees: hiring, admin proposals, technician work orders, sales
  research.py       research tree (data in data/research.py)
  decisions.py      big events with decisions
  builder.py        shared construction helpers, capacity.py sellable capacity per region
  commands.py       command registry (all player actions)
  world.py          world creation and state serialization
  routes/           HTTP blueprints (auth, worlds)
  data/             tunable game data: game_config.py, hardware.py, world_seed.py
frontend/           vanilla HTML/JS/CSS (ES modules, no build step)
  js/               main, stage (renderer), globe, room, rack, panels, drawers, audio, ...
  vendor/           Three.js r160 + RoomEnvironment (MIT) and Natural Earth land data (public domain)
```

## Setup

```
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

The SQLite database is created automatically in `backend/instance/`. If the
schema version changes, the old database is moved to `dc.sqlite3.bak-<time>`
and a fresh one is created (development stage, no migrations).

## Android: signing key (one-time setup)

Android only installs an update over an existing app if both APKs are signed with the same key.
Without a fixed key every CI build gets a random one and the app must be uninstalled first (all saves lost).

```bash
keytool -genkeypair -keystore dc-simulator.jks -storetype PKCS12 -alias dcsimulator -keyalg RSA -keysize 2048 -validity 36500
base64 -w0 dc-simulator.jks > dc-simulator.jks.b64     # macOS: base64 -i dc-simulator.jks
```

Then add two repository secrets (GitHub: Settings > Secrets and variables > Actions):
`ANDROID_KEYSTORE_BASE64` (content of `dc-simulator.jks.b64`) and `ANDROID_KEY_PASSWORD` (the password you chose;
the alias must stay `dcsimulator`). Keep the `.jks` file safe and never commit it. If it is lost, players have to
uninstall once more. The first build with the new key still needs one uninstall.

## How to play

1. Click a region on the globe and build a datacenter.
2. Open it, click an empty slot to install a rack.
3. Open the rack and drag equipment into it. Mounting rules:
   - 42 U, every rack needs a PDU (max 2) and a ToR switch (max 2) for servers
   - every server NIC needs a free switch port
   - power per rack is limited, overload trips the breaker (reset it after removing load)
   - 2 PDUs + 2 ToR switches = redundant, needed for premium contracts and
     absorbs random incidents
   - UPS keeps a rack alive during grid outages; blanking panels, cable
     management and patch panels reduce heat/incident risk
4. Check the datacenter: heat must stay below the cooling capacity, the grid
   connection must carry the load, the aggregation switch needs uplink ports.
5. Open **Contracts**, accept offers you have capacity for. Unserved contracts
   are breached after 48 h.

Controls: `Space` pause, `1`/`2`/`3` speed 1x/2x/5x, `Esc` back, `Del` remove
the selected device, `M` mute. Click a mounted device to select it, drag it to
move it.

## Team

Hire admins and technicians in the **Team** drawer. Admins propose racks (with an exact
layout), new datacenters and upgrades every day; you approve, the cost is paid and a
technician builds it over game time. Technicians also shorten failures, admins lower the
failure chance. Higher skill gives better plans, faster work and higher salary. Salaries
replace the old flat staff cost.

## Research, decisions, living world

- **Research** (top bar): 20 technologies unlock hardware (GPU nodes, 100G, liquid cooling, ...)
  and permanent bonuses (power overhead, failures, technician speed, revenue). Two projects at a
  time, admins speed it up. Locked hardware shows a lock in the rack builder.
- **Decisions**: every few days a big event asks for a choice (fire, cyber attack, big customer,
  audit, energy crisis, poaching, ...). Options have costs and risks; if you do not decide in
  time, the default option happens. The game pauses when one arrives.
- **Living room**: employees walk around the datacenter room, technicians build approved plans
  (a growing construction site shows progress) and repair failed racks, admins and sales sit at
  the ops desk. Offline racks get an alarm beacon, fires and tripped breakers smoke.

## Login

By default (`DC_LOCAL_MODE` unset or `1`) there is no login: the frontend gets
a token for a reserved `local` user via `POST /api/auth/local`. For
multiplayer deployments start the server with `DC_LOCAL_MODE=0`; then the
endpoint returns 403 and the login/register form is shown.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/local` | JWT |
| GET | `/api/worlds` | worlds of the current user |
| POST | `/api/worlds` | create world (`name`, `company_name`, `ai_count`) |
| GET | `/api/worlds/hardware` | hardware catalog and rack rules |
| GET | `/api/worlds/<id>?since_event=<n>` | catch up the clock, return full state |
| POST | `/api/worlds/<id>/commands` | `{type, payload}`, returns result and fresh state |

Commands: `set_speed`, `rename_company`, `build_datacenter`, `buy_dc_equipment`,
`buy_rack` (optionally `template_id`, `clone_rack_id`, `slot`), `install_item`,
`move_item`, `remove_item`, `sell_rack`, `rename_rack`, `repair_rack`,
`save_template`, `delete_template`, `accept_contract`, `cancel_contract`,
`hire_candidate`, `fire_employee`, `approve_proposal`, `reject_proposal`, `set_auto_accept`,
`start_research`, `resolve_decision`.
Every command is validated server side and written to `command_log`.

## Notes

- 1 tick = 1 in-game hour; at 1x one tick takes 2 real seconds
  (`data/game_config.py`). All balance numbers are untested estimates.
- Money is stored as integer cents.
- Rival names are parodies; never use real brand names.
- Sounds are synthesized with the Web Audio API (no audio files).
- Licenses: Three.js MIT (`frontend/vendor/LICENSE-three.txt`), Natural Earth
  land polygons (via `world-atlas`) public domain. No fonts or textures are
  bundled.
