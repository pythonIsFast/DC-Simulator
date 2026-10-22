"""Command registry. Every player action is a command validated server side.

A handler has the signature handler(db, world, company, payload) -> dict and
raises CommandError for invalid input. It runs inside a transaction together
with the command_log entry, so state changes and audit trail stay consistent.
After a successful command the company is re-evaluated (sim.refresh_company).
"""
import json

import builder
import decisions
import market
import racks as rk
import research
import sim
import staff
from bookkeeping import book, change_cash
from data import game_config as cfg
from data.hardware import DC_CATEGORIES, STARTER_DC_EQUIPMENT

HANDLERS = {}


class CommandError(Exception):
    pass


def command(name):
    def register(fn):
        HANDLERS[name] = fn
        return fn

    return register


# ---------------------------------------------------------------- helpers

def _money(cents):
    return "{:,.0f}".format(cents / 100)


def _int(payload, key):
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CommandError("%s must be an integer" % key)
    return value


def _name(payload, key="name", default=None):
    value = payload.get(key, default)
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= cfg.NAME_MAX):
        raise CommandError("%s must be 1-%d characters" % (key, cfg.NAME_MAX))
    return value.strip()


def _spend(db, world, company, cents, category, description):
    """Pay `cents` or raise. Writes the ledger entry."""
    cash = db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company["id"],)).fetchone()[0]
    if cents > cash:
        raise CommandError("Not enough cash (need %s, have %s)" % (_money(cents), _money(cash)))
    change_cash(db, company["id"], -cents)
    book(db, world["id"], company["id"], world["tick"], category, -cents, description)


def _refund(db, world, company, cents, description):
    change_cash(db, company["id"], cents)
    book(db, world["id"], company["id"], world["tick"], "refund", cents, description)


def _require_unlocked(db, company, code):
    try:
        research.require_hw(db, company["id"], code)
    except research.ResearchError as exc:
        raise CommandError(str(exc))


def _hw_by_code(db, code):
    row = db.execute("SELECT * FROM hardware_types WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise CommandError("Unknown hardware")
    return rk.hardware_from_row(row)


def _own_dc(db, company, dc_id):
    dc = db.execute("SELECT * FROM datacenters WHERE id = ? AND company_id = ? AND status = 'active'",
                    (dc_id, company["id"])).fetchone()
    if dc is None:
        raise CommandError("Datacenter not found")
    return dc


def _own_rack(db, company, rack_id):
    rack = db.execute(
        "SELECT r.* FROM racks r JOIN datacenters d ON d.id = r.datacenter_id WHERE r.id = ? AND d.company_id = ?",
        (rack_id, company["id"])).fetchone()
    if rack is None:
        raise CommandError("Rack not found")
    return rack


def _rack_items(db, rack_id):
    rows = db.execute(
        "SELECT i.id, i.rack_id, i.u_start, h.code, h.category, h.name, h.u_height, h.power_w, h.heat_w,"
        " h.ports, h.price_cents, h.attrs_json FROM rack_items i"
        " JOIN hardware_types h ON h.id = i.hardware_type_id WHERE i.rack_id = ? ORDER BY i.u_start", (rack_id,))
    return [rk.item_from_row(r) for r in rows]


def _layout_of(items):
    return [{"code": i["code"], "u_start": i["u_start"]} for i in items]


def _place_layout(db, rack_id, layout):
    """Validate and insert a template layout into an empty rack. Returns total price in cents."""
    try:
        return builder.place_layout(db, rack_id, layout)
    except builder.BuildError as exc:
        raise CommandError("Layout invalid: %s" % exc)


# ---------------------------------------------------------------- general

@command("set_speed")
def set_speed(db, world, company, payload):
    speed = payload.get("speed")
    if speed not in cfg.ALLOWED_SPEEDS or isinstance(speed, bool):
        raise CommandError("speed must be one of %s" % (cfg.ALLOWED_SPEEDS,))
    # Multiplayer later: replace by a vote or host-only control.
    if world["mode"] != "singleplayer":
        raise CommandError("speed can only be changed in singleplayer worlds")
    db.execute("UPDATE worlds SET speed = ? WHERE id = ?", (speed, world["id"]))
    return {"speed": speed}


@command("rename_company")
def rename_company(db, world, company, payload):
    name = _name(payload)
    taken = db.execute("SELECT 1 FROM companies WHERE world_id = ? AND name = ? AND id != ?",
                       (world["id"], name, company["id"])).fetchone()
    if taken:
        raise CommandError("name already taken in this world")
    db.execute("UPDATE companies SET name = ? WHERE id = ?", (name, company["id"]))
    return {"name": name}


# ---------------------------------------------------------------- datacenters

@command("build_datacenter")
def build_datacenter(db, world, company, payload):
    region = db.execute("SELECT * FROM regions WHERE id = ? AND world_id = ?",
                        (_int(payload, "region_id"), world["id"])).fetchone()
    if region is None:
        raise CommandError("Region not found")
    count = db.execute("SELECT COUNT(*) FROM datacenters WHERE company_id = ? AND region_id = ?",
                       (company["id"], region["id"])).fetchone()[0]
    if count >= cfg.DC_MAX_PER_REGION:
        raise CommandError("Maximum %d datacenters per region" % cfg.DC_MAX_PER_REGION)
    name = _name(payload, default="%s DC %d" % (region["name"], count + 1))
    cost = int(cfg.DC_BUILD_BASE_CENTS * region["land_cost_index"])
    _spend(db, world, company, cost, "construction", "Datacenter in " + region["name"])
    try:
        dc_id = builder.insert_datacenter(db, world, company["id"], region, name, cost)
    except builder.BuildError as exc:
        raise CommandError(str(exc))
    return {"datacenter_id": dc_id, "cost_cents": cost}


@command("buy_dc_equipment")
def buy_dc_equipment(db, world, company, payload):
    dc = _own_dc(db, company, _int(payload, "datacenter_id"))
    hw = _hw_by_code(db, payload.get("code"))
    _require_unlocked(db, company, hw["code"])
    qty = _int(payload, "qty")
    if hw["category"] not in DC_CATEGORIES or not (1 <= qty <= 10):
        raise CommandError("Invalid equipment or quantity")
    row = db.execute("SELECT qty FROM dc_equipment WHERE datacenter_id = ? AND hardware_type_id = ?",
                     (dc["id"], hw["id"])).fetchone()
    have = row["qty"] if row else 0
    if have + qty > cfg.DC_MAX_EQUIPMENT_QTY:
        raise CommandError("Maximum %d x %s per datacenter" % (cfg.DC_MAX_EQUIPMENT_QTY, hw["name"]))
    _spend(db, world, company, hw["price_cents"] * qty, "hardware", "%d x %s" % (qty, hw["name"]))
    db.execute(
        "INSERT INTO dc_equipment (datacenter_id, hardware_type_id, qty) VALUES (?, ?, ?)"
        " ON CONFLICT(datacenter_id, hardware_type_id) DO UPDATE SET qty = qty + excluded.qty",
        (dc["id"], hw["id"], qty))
    return {"qty": have + qty}


# ---------------------------------------------------------------- racks

@command("buy_rack")
def buy_rack(db, world, company, payload):
    dc = _own_dc(db, company, _int(payload, "datacenter_id"))
    used = {r["slot"] for r in db.execute("SELECT slot FROM racks WHERE datacenter_id = ?", (dc["id"],))}
    if len(used) >= cfg.DC_MAX_RACKS:
        raise CommandError("Datacenter is full (%d racks)" % cfg.DC_MAX_RACKS)
    layout = []
    if payload.get("template_id") is not None:
        tpl = db.execute("SELECT * FROM rack_templates WHERE id = ? AND company_id = ?",
                         (_int(payload, "template_id"), company["id"])).fetchone()
        if tpl is None:
            raise CommandError("Template not found")
        layout = json.loads(tpl["layout_json"])
    elif payload.get("clone_rack_id") is not None:
        src = _own_rack(db, company, _int(payload, "clone_rack_id"))
        layout = _layout_of(_rack_items(db, src["id"]))
    for entry in layout:
        _require_unlocked(db, company, entry.get("code"))
    slot = payload.get("slot")
    if slot is None:
        slot = next(s for s in range(cfg.DC_MAX_RACKS) if s not in used)
    elif not isinstance(slot, int) or isinstance(slot, bool) or not (0 <= slot < cfg.DC_MAX_RACKS) or slot in used:
        raise CommandError("Slot not available")
    cur = db.execute("INSERT INTO racks (datacenter_id, name, slot, created_tick) VALUES (?, ?, ?, ?)",
                     (dc["id"], "Rack %d" % (slot + 1), slot, world["tick"]))
    rack_id = cur.lastrowid
    items_cost = _place_layout(db, rack_id, layout)
    _spend(db, world, company, cfg.RACK_SHELL_CENTS + items_cost, "hardware", "New rack in " + dc["name"])
    return {"rack_id": rack_id, "cost_cents": cfg.RACK_SHELL_CENTS + items_cost}


@command("rename_rack")
def rename_rack(db, world, company, payload):
    rack = _own_rack(db, company, _int(payload, "rack_id"))
    db.execute("UPDATE racks SET name = ? WHERE id = ?", (_name(payload), rack["id"]))
    return {}


@command("install_item")
def install_item(db, world, company, payload):
    rack = _own_rack(db, company, _int(payload, "rack_id"))
    hw = _hw_by_code(db, payload.get("code"))
    _require_unlocked(db, company, hw["code"])
    u_start = _int(payload, "u_start")
    err = rk.placement_error(_rack_items(db, rack["id"]), hw, u_start)
    if err:
        raise CommandError(err)
    _spend(db, world, company, hw["price_cents"], "hardware", hw["name"])
    cur = db.execute("INSERT INTO rack_items (rack_id, hardware_type_id, u_start) VALUES (?, ?, ?)",
                     (rack["id"], hw["id"], u_start))
    return {"item_id": cur.lastrowid}


def _own_item(db, company, item_id):
    row = db.execute(
        "SELECT i.id, i.rack_id, i.u_start, h.code, h.category, h.name, h.u_height, h.power_w, h.heat_w,"
        " h.ports, h.price_cents, h.attrs_json FROM rack_items i"
        " JOIN hardware_types h ON h.id = i.hardware_type_id"
        " JOIN racks r ON r.id = i.rack_id JOIN datacenters d ON d.id = r.datacenter_id"
        " WHERE i.id = ? AND d.company_id = ?", (item_id, company["id"])).fetchone()
    if row is None:
        raise CommandError("Item not found")
    return rk.item_from_row(row)


@command("move_item")
def move_item(db, world, company, payload):
    item = _own_item(db, company, _int(payload, "item_id"))
    u_start = _int(payload, "u_start")
    err = rk.placement_error(_rack_items(db, item["rack_id"]), item, u_start, ignore_item_id=item["id"])
    if err:
        raise CommandError(err)
    db.execute("UPDATE rack_items SET u_start = ? WHERE id = ?", (u_start, item["id"]))
    return {}


@command("remove_item")
def remove_item(db, world, company, payload):
    item = _own_item(db, company, _int(payload, "item_id"))
    db.execute("DELETE FROM rack_items WHERE id = ?", (item["id"],))
    refund = int(item["price_cents"] * cfg.SELL_BACK_RATIO)
    _refund(db, world, company, refund, "Sold " + item["name"])
    return {"refund_cents": refund}


@command("sell_rack")
def sell_rack(db, world, company, payload):
    rack = _own_rack(db, company, _int(payload, "rack_id"))
    items = _rack_items(db, rack["id"])
    refund = int((cfg.RACK_SHELL_CENTS + sum(i["price_cents"] for i in items)) * cfg.SELL_BACK_RATIO)
    db.execute("DELETE FROM racks WHERE id = ?", (rack["id"],))
    _refund(db, world, company, refund, "Sold " + rack["name"])
    return {"refund_cents": refund}


@command("repair_rack")
def repair_rack(db, world, company, payload):
    rack = _own_rack(db, company, _int(payload, "rack_id"))
    if rack["status"] == "ok":
        raise CommandError("Rack does not need repairs")
    stats = rk.rack_stats(_rack_items(db, rack["id"]))
    if rack["status"] == "tripped":
        if stats["overload"] or stats["pdu_count"] == 0:
            raise CommandError("Still overloaded: remove hardware or add PDU capacity first")
        cost = 0
    else:
        cost = cfg.REPAIR_COST_CENTS
    if cost:
        _spend(db, world, company, cost, "repair", "Repair " + rack["name"])
    db.execute("UPDATE racks SET status = 'ok', down_until_tick = NULL, down_reason = NULL WHERE id = ?",
               (rack["id"],))
    return {"cost_cents": cost}


# ---------------------------------------------------------------- templates

@command("save_template")
def save_template(db, world, company, payload):
    rack = _own_rack(db, company, _int(payload, "rack_id"))
    name = _name(payload, default=rack["name"] + " template")
    count = db.execute("SELECT COUNT(*) FROM rack_templates WHERE company_id = ?", (company["id"],)).fetchone()[0]
    if count >= cfg.MAX_TEMPLATES:
        raise CommandError("Maximum %d templates" % cfg.MAX_TEMPLATES)
    layout = _layout_of(_rack_items(db, rack["id"]))
    if not layout:
        raise CommandError("The rack is empty")
    cur = db.execute("INSERT INTO rack_templates (company_id, name, layout_json) VALUES (?, ?, ?)",
                     (company["id"], name, json.dumps(layout)))
    return {"template_id": cur.lastrowid}


@command("delete_template")
def delete_template(db, world, company, payload):
    cur = db.execute("DELETE FROM rack_templates WHERE id = ? AND company_id = ?",
                     (_int(payload, "template_id"), company["id"]))
    if cur.rowcount == 0:
        raise CommandError("Template not found")
    return {}


# ---------------------------------------------------------------- contracts

@command("accept_contract")
def accept_contract(db, world, company, payload):
    c = db.execute("SELECT * FROM contracts WHERE id = ? AND world_id = ? AND status = 'offered'",
                   (_int(payload, "contract_id"), world["id"])).fetchone()
    if c is None:
        raise CommandError("Offer is no longer available")
    has_dc = db.execute("SELECT 1 FROM datacenters WHERE company_id = ? AND region_id = ? AND status = 'active'",
                        (company["id"], c["region_id"])).fetchone()
    if not has_dc:
        raise CommandError("You need a datacenter in this region")
    active = db.execute("SELECT COUNT(*) FROM contracts WHERE company_id = ? AND status = 'active'",
                        (company["id"],)).fetchone()[0]
    if active >= cfg.MAX_ACTIVE_CONTRACTS:
        raise CommandError("Maximum %d active contracts" % cfg.MAX_ACTIVE_CONTRACTS)
    db.execute("UPDATE contracts SET company_id = ?, status = 'active', start_tick = ?, end_tick = ?,"
               " sla_fail_streak = 0 WHERE id = ?",
               (company["id"], world["tick"], world["tick"] + c["duration_ticks"], c["id"]))
    market.compute_market(db, world["id"], world["tick"], persist=True)
    return {}


@command("cancel_contract")
def cancel_contract(db, world, company, payload):
    c = db.execute("SELECT * FROM contracts WHERE id = ? AND company_id = ? AND status = 'active'",
                   (_int(payload, "contract_id"), company["id"])).fetchone()
    if c is None:
        raise CommandError("Contract not found")
    penalty = int(c["penalty_cents"] * cfg.CANCEL_PENALTY_RATIO)
    _spend(db, world, company, penalty, "penalty", "Cancelled: " + c["name"])
    db.execute("UPDATE contracts SET status = 'cancelled' WHERE id = ?", (c["id"],))
    market.compute_market(db, world["id"], world["tick"], persist=True)
    return {"penalty_cents": penalty}


# ---------------------------------------------------------------- staff

@command("resolve_decision")
def resolve_decision(db, world, company, payload):
    try:
        return decisions.resolve(db, world, company, _int(payload, "decision_id"), payload.get("option"))
    except decisions.DecisionError as exc:
        raise CommandError(str(exc))


@command("start_research")
def start_research(db, world, company, payload):
    try:
        research.start(db, world, company, payload.get("code"))
    except research.ResearchError as exc:
        raise CommandError(str(exc))
    return {}


@command("set_admin_policy")
def set_admin_policy(db, world, company, payload):
    try:
        staff.set_policy(db, company["id"], payload.get("policy"))
        staff.run_auto_approve(db, world, company)   # applies to plans that are already waiting
    except staff.StaffError as exc:
        raise CommandError(str(exc))
    return {}


@command("hire_candidate")
def hire_candidate(db, world, company, payload):
    try:
        return {"employee_id": staff.hire(db, world, company, _int(payload, "candidate_id"))}
    except staff.StaffError as exc:
        raise CommandError(str(exc))


@command("fire_employee")
def fire_employee(db, world, company, payload):
    try:
        return {"name": staff.fire(db, world, company, _int(payload, "employee_id"))}
    except staff.StaffError as exc:
        raise CommandError(str(exc))


@command("approve_proposal")
def approve_proposal(db, world, company, payload):
    try:
        return {"order_id": staff.approve(db, world, company, _int(payload, "proposal_id"))}
    except staff.StaffError as exc:
        raise CommandError(str(exc))


@command("set_auto_accept")
def set_auto_accept(db, world, company, payload):
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise CommandError("enabled must be true or false")
    staff.set_auto_accept(db, company["id"], enabled)
    return {"enabled": enabled}


@command("reject_proposal")
def reject_proposal(db, world, company, payload):
    try:
        staff.reject(db, company, _int(payload, "proposal_id"))
    except staff.StaffError as exc:
        raise CommandError(str(exc))
    return {}


# ---------------------------------------------------------------- execution

def execute_command(db, world, company, cmd_type, payload):
    """Run a command and log it. Returns (ok, result_or_error)."""
    handler = HANDLERS.get(cmd_type)
    if handler is None:
        return False, "unknown command type"

    db.execute("BEGIN IMMEDIATE")
    try:
        try:
            result = handler(db, world, company, payload)
            sim.refresh_company(db, world, company["id"], world["tick"])
            ok, error = True, None
        except CommandError as exc:
            # Roll back partial changes of the failed handler, keep only the log entry.
            db.execute("ROLLBACK")
            db.execute("BEGIN IMMEDIATE")
            result, ok, error = None, False, str(exc)
        db.execute(
            "INSERT INTO command_log (world_id, company_id, tick, type, payload_json, ok, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (world["id"], company["id"], world["tick"], cmd_type, json.dumps(payload), 1 if ok else 0, error),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return ok, (result if ok else error)
