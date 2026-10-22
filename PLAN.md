# Datacenter Tycoon (working title) - Project Plan

## Vision

A 3D datacenter tycoon. The player starts as a small hosting startup, builds
datacenters at locations around the world (3D globe), fills them with
self-built racks, acquires customer services/contracts, manages money, and
competes against AI rivals.

- Rivals use **parody names only** (e.g. "Googol", "Microsoftie"). Never real
  brand names, because the game may be released commercially.
- Singleplayer first, multiplayer later.
- Game feel is a core requirement, not polish.

## Stack

- Backend: Python 3, Flask, SQLite, JWT
- Frontend: vanilla HTML/JS (ES modules), vanilla CSS, Three.js stored locally
  (no build step)
- Metric units everywhere.

## Architecture requirements

- Server-authoritative simulation in ticks (1 tick = 1 in-game hour). The
  client only renders and sends commands.
- Every game belongs to a `world_id`. All actions are commands via the API.
  Singleplayer = world with one human + AI rivals. Multiplayer later = world
  with multiple humans. Nothing may block this (companies are linked to a
  world, `companies.user_id` is NULL for AI).
- Offline progress is recalculated from timestamps on login (catch-up).
- Rival AI: rule-based, server side, own money, expansion strategy, market
  share per region.
- Tables: users, worlds, companies (player + AI), regions, datacenters,
  racks, rack_items, rack_templates, hardware_types, contracts, research,
  events, ledger, market_share, milestones, command_log.
- Money is stored as integer cents (no floating point money).

## Core feature: Rack builder

A rack is an empty shell with 42 U. The player buys and places everything:

- Servers (1-4 U; types: CPU, storage, GPU/AI)
- Switches (ToR per rack; aggregation/spine at datacenter level)
- PDUs (two per rack for redundancy, with power limit)
- Optional: patch panels, cable management, UPS, blanking panels

Rules:

- Power per rack is limited; overload trips the breaker.
- Every server needs a network port; too few switch ports means wasted
  capacity.
- Heat per rack vs. cooling capacity per room must match.
- Missing redundancy (single PDU/switch) is cheaper but raises outage risk
  during events.
- Rack templates: save and clone racks.

Hardware values (power, heat, ports, prices) are rough estimates and live in
one easily tunable data file for balancing.

## Game feel (planned from the start)

- Drag & drop mounting with snap, sound and small animation
- Visible cabling, LEDs that blink according to load
- Money ticks up live, small popups for income
- Heatmap, fan noise scaling with load
- Milestones with rewards (first full rack, first contract, first new region)
- Time control: pause, 1x, 2x, 5x
- Audio via Web Audio API (synthesized sounds or royalty-free samples)
- Instancing for many 3D objects (performance)

## Phases (rough estimates, ~8 h total)

1. Project structure, auth (JWT), DB schema, world model (~1 h)
2. Globe, locations, UI frame (~1.5 h). Procedural globe if no earth texture.
3. Rack builder with server/switch/PDU rules (~2 h)
4. Economy, power, heat, tick engine (~1.5 h)
5. Contracts, AI rivals, events (~1.5 h)
6. Game feel, sound, polish

Cut first if time runs short: research tree and datacenter interior view.

## Release considerations

- Parody names only. Check licenses for all textures, sounds, fonts
  (Three.js is MIT).
- Server-authoritative logic to prevent cheating on leaderboards
  (`command_log` gives an audit trail).

## Phase 1 status

Implemented: project structure, SQLite schema, JWT auth, world model
(creation with regions, player company, AI rivals, market share rows),
command endpoint with registry, tick clock with offline catch-up, minimal
test frontend.
