"""Save file export/import (single-player local mode only, see savetransfer.py)."""
import time

from flask import Blueprint, Response, current_app, jsonify, request

import savetransfer
from auth import login_required
from db import SCHEMA_VERSION, apply_schema

bp = Blueprint("save", __name__, url_prefix="/api/save")


@bp.before_request
def local_mode_only():
    if not current_app.config["LOCAL_MODE"]:
        return jsonify(error="Moving saves is only available in local mode"), 403


@bp.get("/info")
@login_required
def info():
    return jsonify(worlds=savetransfer.worlds_of(current_app.config["DATABASE"]))


@bp.get("/export")
@login_required
def export():
    data = savetransfer.export_bytes(current_app.config["DATABASE"])
    name = "datacenter-tycoon-%s.dcsave" % time.strftime("%Y%m%d-%H%M")
    return Response(data, mimetype="application/octet-stream", headers={
        "Content-Disposition": 'attachment; filename="%s"' % name, "X-Filename": name})


@bp.post("/inspect")
@login_required
def inspect():
    try:
        return jsonify(worlds=savetransfer.inspect(request.get_data(cache=False), SCHEMA_VERSION))
    except savetransfer.TransferError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/import")
@login_required
def import_save():
    try:
        worlds = savetransfer.restore(request.get_data(cache=False), current_app.config["DATABASE"], SCHEMA_VERSION, apply_schema)
    except savetransfer.TransferError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(worlds=worlds)
