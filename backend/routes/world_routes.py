from flask import Blueprint, g, jsonify, request

from auth import login_required
from clock import catch_up
from commands import execute_command
from data.game_config import MAX_AI_RIVALS, NAME_MAX
from db import get_db
from world import create_world, get_user_company, hardware_catalog, world_state, world_summary

bp = Blueprint("worlds", __name__, url_prefix="/api/worlds")


def _clean_name(value, default):
    if value is None:
        return default
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= NAME_MAX):
        return None
    return value.strip()


@bp.get("")
@login_required
def list_worlds():
    rows = get_db().execute(
        "SELECT w.* FROM worlds w JOIN companies c ON c.world_id = w.id"
        " WHERE c.user_id = ? ORDER BY w.id DESC",
        (g.user_id,),
    ).fetchall()
    return jsonify(worlds=[world_summary(w) for w in rows])


@bp.post("")
@login_required
def new_world():
    data = request.get_json(silent=True) or {}
    world_name = _clean_name(data.get("name"), "My World")
    company_name = _clean_name(data.get("company_name"), "My Hosting Startup")
    ai_count = data.get("ai_count", 3)
    if world_name is None or company_name is None:
        return jsonify(error="Names must be 1-%d characters" % NAME_MAX), 400
    if not isinstance(ai_count, int) or isinstance(ai_count, bool) or not (0 <= ai_count <= MAX_AI_RIVALS):
        return jsonify(error="ai_count must be an integer from 0 to %d" % MAX_AI_RIVALS), 400

    db = get_db()
    world_id = create_world(db, g.user_id, world_name, company_name, ai_count)
    return jsonify(world_id=world_id), 201


def _load(world_id):
    """Catch the world up, then return (world, company) or an error response."""
    db = get_db()
    company = get_user_company(db, world_id, g.user_id)
    if company is None:
        # Same answer for "does not exist" and "not yours".
        return None, None, (jsonify(error="World not found"), 404)
    world = catch_up(db, world_id)
    # Re-read: catch-up may have changed company data in later phases.
    company = get_user_company(db, world_id, g.user_id)
    return world, company, None


@bp.get("/<int:world_id>")
@login_required
def get_world(world_id):
    world, company, err = _load(world_id)
    if err:
        return err
    return jsonify(world_state(get_db(), world, company, _since_event()))


@bp.post("/<int:world_id>/commands")
@login_required
def post_command(world_id):
    world, company, err = _load(world_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    cmd_type, payload = data.get("type"), data.get("payload", {})
    if not isinstance(cmd_type, str) or not isinstance(payload, dict):
        return jsonify(error="Body must be {type: str, payload: object}"), 400

    db = get_db()
    ok, result = execute_command(db, world, company, cmd_type, payload)
    if not ok:
        return jsonify(error=result), 400
    # Return the fresh state so the client never has to guess the outcome.
    world = db.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
    company = get_user_company(db, world_id, g.user_id)
    return jsonify(result=result, state=world_state(db, world, company, _since_event()))


def _since_event():
    """Optional ?since_event=<id>: only events newer than the client's cursor."""
    return request.args.get("since_event", type=int)


@bp.get("/hardware")
@login_required
def get_hardware():
    return jsonify(hardware_catalog(get_db()))
