import os
import sqlite3

from flask import current_app, g

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


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


def init_db(app):
    """Create the database file and all tables (idempotent)."""
    path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = _connect(path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    finally:
        conn.close()
    app.teardown_appcontext(close_db)
