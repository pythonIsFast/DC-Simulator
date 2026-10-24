"""Rack rules: placement validation and per-rack statistics.

Items are plain dicts with the keys: id, code, category, name, u_start, u_height,
power_w, heat_w, ports, price_cents, attrs (dict).
"""
import functools
import json

from data import game_config as cfg

SERVER_PREFIX = "server_"


# Attributes are static per hardware type. Parsing them for every item on every tick was the main
# cost of a tick, so the parsed dicts are shared. Callers must treat them as read only.
@functools.lru_cache(maxsize=1024)
def parse_attrs(text):
    return json.loads(text)


def item_from_row(row):
    """Build an item dict from a joined rack_items + hardware_types row."""
    return {
        "id": row["id"], "rack_id": row["rack_id"], "u_start": row["u_start"], "code": row["code"],
        "category": row["category"], "name": row["name"], "u_height": row["u_height"],
        "power_w": row["power_w"], "heat_w": row["heat_w"], "ports": row["ports"],
        "price_cents": row["price_cents"], "attrs": parse_attrs(row["attrs_json"]),
    }


def hardware_from_row(row):
    return {
        "id": row["id"], "code": row["code"], "category": row["category"], "name": row["name"],
        "u_height": row["u_height"], "power_w": row["power_w"], "heat_w": row["heat_w"],
        "ports": row["ports"], "price_cents": row["price_cents"], "attrs": parse_attrs(row["attrs_json"]),
    }


def placement_error(items, hw, u_start, ignore_item_id=None):
    """Return an error string if `hw` cannot be mounted at `u_start`, else None."""
    if hw["u_height"] < 1:
        return "This equipment is not rack mounted"
    if not isinstance(u_start, int) or isinstance(u_start, bool):
        return "u_start must be an integer"
    top = u_start + hw["u_height"] - 1
    if u_start < 1 or top > cfg.RACK_U:
        return "Does not fit into the rack"
    others = [i for i in items if i["id"] != ignore_item_id]
    occupied = set()
    for i in others:
        occupied.update(range(i["u_start"], i["u_start"] + i["u_height"]))
    if occupied.intersection(range(u_start, top + 1)):
        return "Slot is already occupied"
    limit = cfg.MAX_PER_RACK.get(hw["category"])
    if limit is not None and sum(1 for i in others if i["category"] == hw["category"]) >= limit:
        return "Maximum %d x %s per rack" % (limit, hw["category"].replace("_", " "))
    return None


def rack_stats(items):
    """Compute power, heat, network and redundancy figures of a rack."""
    used_u = sum(i["u_height"] for i in items)
    empty_u = cfg.RACK_U - used_u
    servers = sorted((i for i in items if i["category"].startswith(SERVER_PREFIX)), key=lambda i: i["u_start"])
    pdus = [i for i in items if i["category"] == "pdu"]
    tors = [i for i in items if i["category"] == "switch_tor"]
    ups = [i for i in items if i["category"] == "ups"]

    load_w = sum(i["power_w"] for i in items)
    heat_mult = 1.0 + (cfg.EMPTY_U_HEAT_PENALTY * empty_u if servers else 0.0)
    fan_cut = min(0.15, sum(i["attrs"].get("heat_reduction", 0) for i in items))
    heat_w = sum(i["heat_w"] for i in items) * heat_mult * (1.0 - fan_cut)

    pdu_caps = [p["attrs"].get("max_w", 0) for p in pdus]
    pdu_cap_w = sum(pdu_caps)
    limit_w = min(pdu_cap_w, cfg.RACK_FEED_LIMIT_W)
    # N+1: if the largest PDU fails, the rest must still carry the whole load.
    power_redundant = len(pdus) >= 2 and (pdu_cap_w - max(pdu_caps)) >= load_w
    overload = bool(pdus) and load_w > limit_w

    ports_total = sum(t["ports"] for t in tors)
    uplinks_needed = sum(t["attrs"].get("uplinks", 0) for t in tors)
    free_ports = ports_total
    connected_ids = []
    for s in servers:
        nic = s["attrs"].get("nic", 1)
        if tors and nic <= free_ports:
            free_ports -= nic
            connected_ids.append(s["id"])
    connected = set(connected_ids)

    cap = {"cpu": 0.0, "storage_tb": 0.0, "gpu": 0.0}
    for s in servers:
        if s["id"] in connected:
            for key in cap:
                cap[key] += s["attrs"].get(key, 0)

    ups_w = sum(u["attrs"].get("ups_w", 0) for u in ups)
    has_cable_mgmt = any(i["category"] == "cable_mgmt" for i in items)
    has_patch = any(i["category"] == "patch_panel" for i in items)
    incident_mult = 1.0 - (0.5 if has_cable_mgmt else 0.0) - (0.25 if has_patch else 0.0)

    warnings = []
    if servers and not pdus:
        warnings.append("No PDU: the rack has no power")
    if overload:
        warnings.append("Overload: %.1f kW > %.1f kW limit, the breaker will trip" % (load_w / 1000, limit_w / 1000))
    if servers and not tors:
        warnings.append("No ToR switch: servers have no network")
    elif len(connected_ids) < len(servers):
        warnings.append("%d server(s) have no free network port" % (len(servers) - len(connected_ids)))
    if tors and free_ports >= 8:
        warnings.append("%d switch ports unused" % free_ports)
    if pdus and len(pdus) < 2:
        warnings.append("Single PDU: no power redundancy")
    elif len(pdus) >= 2 and not power_redundant:
        warnings.append("Load too high for N+1 power redundancy")
    if tors and len(tors) < 2:
        warnings.append("Single ToR switch: no network redundancy")
    if servers and empty_u > 0 and heat_mult > 1.0:
        warnings.append("Empty U raises heat by %.0f %%" % ((heat_mult - 1) * 100))

    return {
        "used_u": used_u, "free_u": empty_u, "load_w": load_w, "heat_w": heat_w, "limit_w": limit_w,
        "pdu_count": len(pdus), "pdu_cap_w": pdu_cap_w, "tor_count": len(tors),
        "ports_total": ports_total, "ports_used": ports_total - free_ports, "uplinks_needed": uplinks_needed,
        "server_count": len(servers), "connected_ids": connected_ids,
        "cpu": cap["cpu"], "storage_tb": cap["storage_tb"], "gpu": cap["gpu"],
        "power_redundant": power_redundant, "net_redundant": len(tors) >= 2,
        "redundant": power_redundant and len(tors) >= 2,
        "overload": overload, "ups_w": ups_w, "has_ups": ups_w >= load_w and ups_w > 0,
        "incident_mult": max(0.1, incident_mult), "warnings": warnings,
    }
