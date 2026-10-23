"""Cloud save without an own server: the whole database is stored in a private GitHub gist.

Each device runs its own local server. "Upload" writes a compressed snapshot of the local database into
the gist, "Download" replaces the local database with it. The user's personal access token (scope: gist)
is kept in instance/cloud.json on the device.
"""
import base64
import gzip
import json
import os
import shutil
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request

from config import INSTANCE_DIR

API = "https://api.github.com"
GIST_DESCRIPTION = "Datacenter Tycoon save"
META_FILE = "meta.json"
DATA_FILE = "save.gz.b64"
FORMAT = 1
TIMEOUT_S = 40


class CloudError(Exception):
    pass


# ---------------------------------------------------------------- local config

def _config_path():
    return os.path.join(INSTANCE_DIR, "cloud.json")


def load_config():
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(_config_path(), 0o600)
    except OSError:
        pass


def clear_config():
    try:
        os.remove(_config_path())
    except OSError:
        pass


# ---------------------------------------------------------------- GitHub API

def _call(method, path, token, body=None, absolute=False):
    url = path if absolute else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "datacenter-tycoon",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CloudError("GitHub rejected the token (401). Create a new token with the 'gist' scope.")
        if exc.code == 403:
            raise CloudError("GitHub refused the request (403). The token needs the 'gist' scope, or the rate limit is hit.")
        if exc.code == 404:
            raise CloudError("Not found on GitHub (404).")
        raise CloudError("GitHub error %d" % exc.code)
    except (urllib.error.URLError, OSError):
        raise CloudError("No connection to GitHub. Check your internet connection.")
    return raw


def _json(method, path, token, body=None):
    raw = _call(method, path, token, body)
    return json.loads(raw.decode("utf-8")) if raw else {}


def check_token(token):
    """Returns the GitHub login name of the token owner."""
    return _json("GET", "/user", token).get("login", "")


def find_gist(token):
    for page in range(1, 6):
        gists = _json("GET", "/gists?per_page=100&page=%d" % page, token)
        for g in gists:
            if g.get("description") == GIST_DESCRIPTION and META_FILE in g.get("files", {}):
                return g["id"]
        if len(gists) < 100:
            break
    return None


def remote_meta(token, gist_id):
    """Small info block about the stored save, or None if there is none."""
    g = _json("GET", "/gists/" + gist_id, token)
    f = g.get("files", {}).get(META_FILE)
    if not f:
        return None
    content = f.get("content")
    if content is None or f.get("truncated"):
        content = _call("GET", f["raw_url"], token, absolute=True).decode("utf-8")
    return json.loads(content)


# ---------------------------------------------------------------- snapshots

def worlds_of(db_path):
    """[{id, name, tick}] of a database file (read only)."""
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        return [{"id": r[0], "name": r[1], "tick": r[2]} for r in conn.execute("SELECT id, name, tick FROM worlds ORDER BY id")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _snapshot(db_path, dest_path):
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")
    finally:
        dst.close()
        src.close()


def upload(db_path, token, device, schema_version):
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap.sqlite3")
        _snapshot(db_path, snap)
        worlds = worlds_of(snap)
        with open(snap, "rb") as f:
            blob = base64.b64encode(gzip.compress(f.read(), 9)).decode("ascii")
    meta = {"format": FORMAT, "saved_at": int(time.time()), "device": device,
            "schema_version": schema_version, "worlds": worlds, "size_bytes": len(blob)}
    files = {META_FILE: {"content": json.dumps(meta)}, DATA_FILE: {"content": blob}}
    cfg = load_config()
    gist_id = cfg.get("gist_id") or find_gist(token)
    if gist_id:
        _json("PATCH", "/gists/" + gist_id, token, {"files": files})
    else:
        gist_id = _json("POST", "/gists", token, {"description": GIST_DESCRIPTION, "public": False, "files": files})["id"]
    cfg["gist_id"] = gist_id
    save_config(cfg)
    return meta


def download(token, gist_id, db_path, schema_version, apply_schema):
    """Replace the local database with the cloud save. The old database is kept as a backup file."""
    g = _json("GET", "/gists/" + gist_id, token)
    f = g.get("files", {}).get(DATA_FILE)
    if not f:
        raise CloudError("There is no save in the cloud yet.")
    content = f.get("content")
    if content is None or f.get("truncated"):
        content = _call("GET", f["raw_url"], token, absolute=True).decode("ascii")
    try:
        raw = gzip.decompress(base64.b64decode(content))
    except (ValueError, OSError):
        raise CloudError("The cloud save is damaged.")
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "cloud.sqlite3")
        with open(snap, "wb") as out:
            out.write(raw)
        src = sqlite3.connect(snap)
        try:
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CloudError("The cloud save is damaged.")
            if src.execute("PRAGMA user_version").fetchone()[0] > schema_version:
                raise CloudError("The cloud save is from a newer version of the game. Update the app first.")
            if os.path.exists(db_path):
                shutil.copyfile(db_path, "%s.bak-%d" % (db_path, int(time.time())))
            dst = sqlite3.connect(db_path, timeout=30)
            try:
                src.backup(dst)
                apply_schema(dst)
            finally:
                dst.close()
        except sqlite3.Error as exc:
            raise CloudError("Could not restore the save: %s" % exc)
        finally:
            src.close()
    return worlds_of(db_path)
