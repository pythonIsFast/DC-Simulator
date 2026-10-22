import re
import sqlite3

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth import create_token
from data.game_config import PASSWORD_MIN, USERNAME_MAX, USERNAME_MIN
from db import get_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _credentials():
    data = request.get_json(silent=True) or {}
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return None, None
    return username.strip(), password


@bp.post("/register")
def register():
    username, password = _credentials()
    if not username or not (USERNAME_MIN <= len(username) <= USERNAME_MAX) or not USERNAME_RE.match(username):
        return jsonify(error="Username must be %d-%d characters (letters, digits, _ and -)" % (USERNAME_MIN, USERNAME_MAX)), 400
    if len(password) < PASSWORD_MIN:
        return jsonify(error="Password must be at least %d characters" % PASSWORD_MIN), 400

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
    except sqlite3.IntegrityError:
        return jsonify(error="Username already taken"), 409
    return jsonify(token=create_token(cur.lastrowid, username), username=username), 201


@bp.post("/login")
def login():
    username, password = _credentials()
    if not username or password is None:
        return jsonify(error="Username and password required"), 400
    user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    # Same error for unknown user and wrong password (no user enumeration).
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Invalid username or password"), 401
    return jsonify(token=create_token(user["id"], user["username"]), username=user["username"])
