"""Sellable capacity per region (total, sold, free per resource). Used by the state API and by admins."""

RESOURCES = ("cpu", "storage_tb", "gpu")


def region_capacity(dcs, contracts):
    """Capacity of online racks (x datacenter performance) minus what active contracts consume."""
    cap = {}
    for dc in dcs:
        c = cap.setdefault(dc["region_id"], {k: {"total": 0.0, "sold": 0.0, "red_total": 0.0, "red_sold": 0.0} for k in RESOURCES})
        for rack in dc["racks"]:
            if not rack["online"]:
                continue
            for k in RESOURCES:
                c[k]["total"] += rack["stats"][k] * dc["perf"]
                if rack["stats"]["redundant"]:
                    c[k]["red_total"] += rack["stats"][k] * dc["perf"]
    for ct in contracts:
        c = cap.get(ct["region_id"])
        if c is None:
            continue
        c[ct["resource"]]["sold"] += ct["units"]
        if ct["premium"]:
            c[ct["resource"]]["red_sold"] += ct["units"]
    return {
        rid: {k: {"total": v["total"], "sold": v["sold"], "free": v["total"] - v["sold"],
                  # Premium contracts consume redundant AND total capacity, so both must have room.
                  "red_free": min(v["total"] - v["sold"], v["red_total"] - v["red_sold"])} for k, v in c.items()}
        for rid, c in cap.items()
    }
