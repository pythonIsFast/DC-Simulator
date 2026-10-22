# CLAUDE.md

## Communication
- Answer SHORT. A few lines, no long summaries, no repeated explanations.
- Chat in German, informal ("du"). Code comments, file names, commit messages and UI text in English.
- Mark uncertainty explicitly. Do not state numbers or file states from memory when they can be checked.

## Working rules
- Do the work yourself. NEVER start sub-agents.
- NEVER start Flask, npm or any other server. The user tests.
- NEVER run Python scripts unless explicitly asked. Syntax checks only (`py_compile`, `node --check`).
- NEVER read `.env` files.
- NEVER open your own browser.
- Use the shell only when necessary (moving files, syntax checks, git).
- Work on `main`, no pull requests.
- Commits under the user's account, NEVER add `Co-Authored-By` lines.

## Project
- Stack: Python 3, Flask, SQLite, JWT; vanilla HTML/JS (ES modules), vanilla CSS, Three.js stored locally. No build step.
- Server-authoritative simulation in ticks (1 tick = 1 in-game hour). The client only renders and sends commands.
- Everything belongs to a `world_id` (multiplayer must stay possible). Money is integer cents. Metric units.
- Balancing values live in `backend/data/` (`game_config.py`, `hardware.py`, `world_seed.py`).
- Rival names are parodies, never real brands. Check licenses of any asset.
- See `PLAN.md` and `README.md` for details.
