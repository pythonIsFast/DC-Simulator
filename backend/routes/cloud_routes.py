"""Cloud save endpoints (single-player local mode only, see cloudsave.py)."""
from flask import Blueprint, current_app, jsonify, request

import cloudsave
from auth import login_required
from db import SCHEMA_VERSION, apply_schema

bp = Blueprint("cloud", __name__, url_prefix="/api/cloud")


@bp.before_request
def local_mode_only():
    if not current_app.config["LOCAL_MODE"]:
        return jsonify(error="Cloud save is only available in local mode"), 403


def _status(token=None):
    cfg = cloudsave.load_config()
    token = token or cfg.get("token")
    out = {"connected": bool(token), "login": cfg.get("login"), "remote": None,
           "local": cloudsave.worlds_of(current_app.config["DATABASE"])}
    if token:
        gist_id = cfg.get("gist_id") or cloudsave.find_gist(token)
        if gist_id:
            out["remote"] = cloudsave.remote_meta(token, gist_id)
    return out


def _guard(fn):
    try:
        return fn()
    except cloudsave.CloudError as exc:
        return jsonify(error=str(exc)), 400


@bp.get("/status")
@login_required
def status():
    return _guard(lambda: jsonify(_status()))


@bp.post("/connect")
@login_required
def connect():
    token = ((request.get_json(silent=True) or {}).get("token") or "").strip()
    if not token:
        return jsonify(error="Paste your GitHub token first"), 400

    def run():
        login = cloudsave.check_token(token)
        gist_id = cloudsave.find_gist(token)
        cloudsave.save_config({"token": token, "login": login, "gist_id": gist_id})
        return jsonify(_status(token))

    return _guard(run)


@bp.post("/disconnect")
@login_required
def disconnect():
    cloudsave.clear_config()
    return jsonify(connected=False)


def _device():
    value = ((request.get_json(silent=True) or {}).get("device") or "device")
    return str(value)[:30]


@bp.post("/upload")
@login_required
def upload():
    cfg = cloudsave.load_config()
    if not cfg.get("token"):
        return jsonify(error="Not connected to GitHub"), 400
    return _guard(lambda: (cloudsave.upload(current_app.config["DATABASE"], cfg["token"], _device(), SCHEMA_VERSION),
                           jsonify(_status()))[1])


@bp.post("/download")
@login_required
def download():
    cfg = cloudsave.load_config()
    if not cfg.get("token"):
        return jsonify(error="Not connected to GitHub"), 400
    gist_id = cfg.get("gist_id") or cloudsave.find_gist(cfg["token"])
    if not gist_id:
        return jsonify(error="There is no save in the cloud yet."), 400
    return _guard(lambda: jsonify(worlds=cloudsave.download(
        cfg["token"], gist_id, current_app.config["DATABASE"], SCHEMA_VERSION, apply_schema)))
