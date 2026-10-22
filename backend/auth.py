import datetime as dt
import functools

import jwt
from flask import current_app, g, jsonify, request

from config import JWT_ALGORITHM, JWT_EXPIRES_HOURS


def create_token(user_id, username):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + dt.timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm=JWT_ALGORITHM)


def _decode(token):
    return jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=[JWT_ALGORITHM])


def login_required(fn):
    """Require a valid 'Authorization: Bearer <jwt>' header; sets g.user_id."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Missing bearer token"), 401
        try:
            payload = _decode(header[7:])
            g.user_id = int(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError):
            return jsonify(error="Invalid or expired token"), 401
        return fn(*args, **kwargs)

    return wrapper
