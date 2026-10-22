import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

JWT_ALGORITHM = "HS256"
JWT_EXPIRES_HOURS = 12


def _load_secret_key():
    """Use DC_SECRET_KEY from the environment, else a persisted random key."""
    env_key = os.environ.get("DC_SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    path = os.path.join(INSTANCE_DIR, "secret.key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


class Config:
    DATABASE = os.environ.get("DC_DATABASE", os.path.join(INSTANCE_DIR, "dc.sqlite3"))
    SECRET_KEY = _load_secret_key()
