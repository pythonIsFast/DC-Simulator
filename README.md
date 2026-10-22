# Datacenter Tycoon (working title)

A 3D datacenter tycoon: build datacenters worldwide, fill self-built racks,
win customer contracts and compete against AI rivals. See [PLAN.md](PLAN.md).

## Structure

```
backend/            Flask API, SQLite, JWT
  app.py            entry point (create_app)
  config.py         paths, secret key (DC_SECRET_KEY or generated instance/secret.key)
  db.py, schema.sql database access and schema
  auth.py           JWT helpers
  clock.py          tick clock and offline catch-up
  commands.py       command registry (all player actions)
  world.py          world creation and state serialization
  routes/           HTTP blueprints (auth, worlds)
  data/             tunable game data (game_config.py, world_seed.py)
frontend/           vanilla HTML/JS/CSS (ES modules, no build step)
```

## Setup

```
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

The SQLite database is created automatically in `backend/instance/`.

## API (Phase 1)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | create user, returns JWT |
| POST | `/api/auth/login` | returns JWT |
| GET | `/api/worlds` | worlds of the current user |
| POST | `/api/worlds` | create world (`name`, `company_name`, `ai_count`) |
| GET | `/api/worlds/<id>` | catch up the clock, return full state |
| POST | `/api/worlds/<id>/commands` | `{type, payload}`; commands: `set_speed`, `rename_company` |

Authenticated routes need `Authorization: Bearer <token>`.

## Notes

- 1 tick = 1 in-game hour. At 1x one tick takes 10 real seconds
  (`data/game_config.py`).
- Money is stored as integer cents.
- Rival names are parodies; never use real brand names.
