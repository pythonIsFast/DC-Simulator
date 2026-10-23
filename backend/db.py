import json
import os
import sqlite3
import time

from flask import current_app, g

from data.hardware import HARDWARE

SCHEMA_PATH = os.environ.get(
    "DC_SCHEMA_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"),
)
SCHEMA_VERSION = 2  # keep in sync with PRAGMA user_version in schema.sql


def _connect(path):
    # isolation_level=None: transactions are controlled explicitly (BEGIN IMMEDIATE).
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _backup_if_outdated(path):
    """Dev stage: an older schema is moved aside and a fresh database is created."""
    if not os.path.exists(path):
        return
    conn = _connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version < SCHEMA_VERSION:
        backup = "%s.bak-%d" % (path, int(time.time()))
        os.replace(path, backup)
        print("Old database schema (v%d) moved to %s" % (version, backup))


def seed_hardware(conn):
    """Insert or update the hardware catalog from data/hardware.py (tunable file)."""
    for hw in HARDWARE:
        conn.execute(
            "INSERT INTO hardware_types (code, category, name, u_height, power_w, heat_w, ports, price_cents, attrs_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(code) DO UPDATE SET category = excluded.category, name = excluded.name,"
            " u_height = excluded.u_height, power_w = excluded.power_w, heat_w = excluded.heat_w,"
            " ports = excluded.ports, price_cents = excluded.price_cents, attrs_json = excluded.attrs_json",
            (hw["code"], hw["category"], hw["name"], hw["u_height"], hw["power_w"], hw["heat_w"],
             hw["ports"], hw["price_cents"], json.dumps(hw["attrs"])),
        )


def apply_schema(conn):
    """Create missing tables and refresh the hardware catalog (also after a save file was imported)."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    seed_hardware(conn)


def init_db(app):
    """Create the database file and all tables (idempotent) and seed the catalog."""
    path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _backup_if_outdated(path)
    conn = _connect(path)
    try:
        apply_schema(conn)
    finally:
        conn.close()
    app.teardown_appcontext(close_db)
