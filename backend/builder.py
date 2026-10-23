"""Construction helpers shared by player commands and staff work orders."""
import market
from data import game_config as cfg
from data.hardware import STARTER_DC_EQUIPMENT
import racks as rk


class BuildError(Exception):
    pass


def hw_by_code(db, code):
    row = db.execute("SELECT * FROM hardware_types WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise BuildError("Unknown hardware")
    return rk.hardware_from_row(row)


def dc_cost(region):
    return int(cfg.DC_BUILD_BASE_CENTS * region["land_cost_index"])


def insert_datacenter(db, world, company_id, region, name, cost):
    """Create a datacenter with the starter equipment. The first one in a region also seeds customer offers."""
    count = db.execute("SELECT COUNT(*) FROM datacenters WHERE company_id = ? AND region_id = ?",
                       (company_id, region["id"])).fetchone()[0]
    cur = db.execute(
        "INSERT INTO datacenters (world_id, company_id, region_id, name, power_capacity_kw, cooling_kw,"
        " build_cost_cents, built_tick) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (world["id"], company_id, region["id"], name, cfg.DC_BASE_POWER_KW, cfg.DC_BASE_COOLING_KW, cost, world["tick"]))
    dc_id = cur.lastrowid
    for code, qty in STARTER_DC_EQUIPMENT.items():
        add_dc_equipment(db, dc_id, code, qty)
    if count == 0:
        market.seed_offers(db, world, world["tick"], region["id"])
    return dc_id


def add_dc_equipment(db, dc_id, code, qty):
    hw = hw_by_code(db, code)
    db.execute(
        "INSERT INTO dc_equipment (datacenter_id, hardware_type_id, qty) VALUES (?, ?, ?)"
        " ON CONFLICT(datacenter_id, hardware_type_id) DO UPDATE SET qty = qty + excluded.qty",
        (dc_id, hw["id"], qty))


def free_slot(db, dc_id):
    used = {r["slot"] for r in db.execute("SELECT slot FROM racks WHERE datacenter_id = ?", (dc_id,))}
    return next((s for s in range(cfg.DC_MAX_RACKS) if s not in used), None)


def place_layout(db, rack_id, layout):
    """Validate and insert a layout [{code, u_start}] into an empty rack. Returns the total price in cents."""
    items, total = [], 0
    for entry in layout:
        hw = hw_by_code(db, entry.get("code"))
        err = rk.placement_error(items, hw, entry.get("u_start"))
        if err:
            raise BuildError(err)
        cur = db.execute("INSERT INTO rack_items (rack_id, hardware_type_id, u_start) VALUES (?, ?, ?)",
                         (rack_id, hw["id"], entry["u_start"]))
        items.append({**hw, "id": cur.lastrowid, "u_start": entry["u_start"]})
        total += hw["price_cents"]
    return total


def append_layout(db, rack_id, layout):
    """Add devices to an existing rack (validated against what is already mounted). Returns the price in cents."""
    rows = db.execute(
        "SELECT i.id, i.rack_id, i.u_start, h.code, h.category, h.name, h.u_height, h.power_w, h.heat_w, h.ports,"
        " h.price_cents, h.attrs_json FROM rack_items i JOIN hardware_types h ON h.id = i.hardware_type_id WHERE i.rack_id = ?",
        (rack_id,)).fetchall()
    items = [rk.item_from_row(r) for r in rows]
    total = 0
    for entry in layout:
        hw = hw_by_code(db, entry.get("code"))
        err = rk.placement_error(items, hw, entry.get("u_start"))
        if err:
            raise BuildError(err)
        cur = db.execute("INSERT INTO rack_items (rack_id, hardware_type_id, u_start) VALUES (?, ?, ?)",
                         (rack_id, hw["id"], entry["u_start"]))
        items.append({**hw, "id": cur.lastrowid, "u_start": entry["u_start"]})
        total += hw["price_cents"]
    return total


def rebuild(db, rack_id, remove_ids, layout):
    """Remove devices (sold back) and mount new ones. Returns the refund in cents. Raises BuildError if the rack changed."""
    if remove_ids:
        marks = ",".join("?" * len(remove_ids))
        rows = db.execute("SELECT i.id, h.price_cents FROM rack_items i JOIN hardware_types h ON h.id = i.hardware_type_id"
                          " WHERE i.rack_id = ? AND i.id IN (%s)" % marks, [rack_id, *remove_ids]).fetchall()
        if len(rows) != len(remove_ids):
            raise BuildError("The rack was changed in the meantime")
        db.execute("DELETE FROM rack_items WHERE rack_id = ? AND id IN (%s)" % marks, [rack_id, *remove_ids])
        refund = int(sum(r["price_cents"] for r in rows) * cfg.SELL_BACK_RATIO)
    else:
        refund = 0
    append_layout(db, rack_id, layout)
    return refund


def insert_rack(db, world, dc_id, name, slot, layout):
    cur = db.execute("INSERT INTO racks (datacenter_id, name, slot, created_tick) VALUES (?, ?, ?, ?)",
                     (dc_id, name, slot, world["tick"]))
    rack_id = cur.lastrowid
    return rack_id, place_layout(db, rack_id, layout)


# --- Taking over a rival: its abstract capacity becomes real datacenters --------------------------
# One standard rack: N+1 power, redundant ToR switches, 14 dual-socket compute servers, blanking panels.
# Only hardware that is available without research, so the layout is always valid.
ACQUIRED_RACK_LAYOUT = (
    [{"code": "pdu_7k2", "u_start": 1}, {"code": "pdu_7k2", "u_start": 2},
     {"code": "tor_24", "u_start": 3}, {"code": "tor_24", "u_start": 4}]
    + [{"code": "cpu_2u", "u_start": 5 + 2 * i} for i in range(14)]
    + [{"code": "blank_1u", "u_start": 33 + i} for i in range(10)]
)
ACQUIRED_RACK_UNITS = 14 * 44             # sellable cpu units of one standard rack (cpu weight is 1.0)
ACQUIRED_RACKS_PER_DC = 8                 # keeps cooling, power feed and uplinks of a starter datacenter sufficient


def take_over_capacity(db, world, company_id, rival_name, units_by_region):
    """Create datacenters with standard racks for a rival's capacity. Returns (datacenters, racks) created."""
    made_dcs = made_racks = 0
    for region_id, units in sorted(units_by_region.items()):
        region = db.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
        racks_left = max(1, round(units / ACQUIRED_RACK_UNITS))
        new_dcs = -(-racks_left // ACQUIRED_RACKS_PER_DC)
        for i in range(new_dcs):
            name = ("%s %s" % (rival_name, region["name"]))[:cfg.NAME_MAX - 3] + ("" if new_dcs == 1 else " %d" % (i + 1))
            dc_id = insert_datacenter(db, world, company_id, region, name, dc_cost(region))
            made_dcs += 1
            for n in range(min(racks_left, ACQUIRED_RACKS_PER_DC)):
                insert_rack(db, world, dc_id, "Rack %d" % (n + 1), free_slot(db, dc_id), ACQUIRED_RACK_LAYOUT)
                racks_left -= 1
                made_racks += 1
    return made_dcs, made_racks
