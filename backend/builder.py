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
    if count >= cfg.DC_MAX_PER_REGION:
        raise BuildError("Maximum %d datacenters per region" % cfg.DC_MAX_PER_REGION)
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


def insert_rack(db, world, dc_id, name, slot, layout):
    cur = db.execute("INSERT INTO racks (datacenter_id, name, slot, created_tick) VALUES (?, ?, ?, ?)",
                     (dc_id, name, slot, world["tick"]))
    rack_id = cur.lastrowid
    return rack_id, place_layout(db, rack_id, layout)
