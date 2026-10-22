"""Big events with a decision: the player picks an option, the outcome can be risky.

A decision has options; every option may cost money up front and has weighted outcomes
(with effects like downtime, fines, new offers, employees leaving). If the player does
not decide in time, the default option is applied for free.
"""
import json
import random

import builder
import market
from bookkeeping import add_event, book, change_cash
from data import game_config as cfg

CHANCE_PER_DAY = 0.22
MIN_GAP_TICKS = 72
FIRST_DECISION_TICK = 72
LIFETIME_TICKS = 72


class DecisionError(Exception):
    pass


def _m(cents):
    return "${:,.0f}".format(cents / 100)


def out(p, text, effects=(), bad=False):
    return {"p": p, "text": text, "effects": list(effects), "bad": bad}


def opt(label, hint, cost, outcomes):
    return {"label": label, "hint": hint, "cost_cents": cost, "outcomes": outcomes}


# ---------------------------------------------------------------- templates (each returns a dict or None)

def t_fire(c):
    dc = c["rng"].choice(c["dcs_with_racks"]) if c["dcs_with_racks"] else None
    if dc is None:
        return None
    return {"kind": "fire", "title": "Smoke in %s" % dc["name"], "default": 0,
            "body": "The smoke detectors went off in %s. A power supply is burning in one of the racks." % dc["name"],
            "options": [
                opt("Wait for the fire brigade", "Free, but risky", 0, [
                    out(0.65, "The fire was put out. One rack is offline for 12 hours.", [{"type": "rack_down", "dc_id": dc["id"], "ticks": 12, "reason": "fire"}]),
                    out(0.35, "A rack burned down completely. Its hardware is lost.", [{"type": "rack_loss", "dc_id": dc["id"]}], bad=True)]),
                opt("Gas fire suppression", "Safe", 1_500_000, [
                    out(1.0, "The system flooded the room with gas. Only 4 hours of downtime on one rack.", [{"type": "rack_down", "dc_id": dc["id"], "ticks": 4, "reason": "fire"}])]),
            ]}


def t_cyber(c):
    dc = c["rng"].choice(c["dcs"]) if c["dcs"] else None
    if dc is None:
        return None
    return {"kind": "cyber", "title": "Cyber attack on %s" % dc["name"], "default": 1,
            "body": "Attackers are scanning your network and trying to get in. What do you do?",
            "options": [
                opt("Hire security consultants", "Safe", 2_000_000, [out(1.0, "The consultants blocked the attack.")]),
                opt("Handle it internally", "Free, but risky", 0, [
                    out(0.6, "Your team stopped the attack in time."),
                    out(0.4, "The attackers got in. Systems were down for 8 hours and cleanup cost %s." % _m(1_000_000),
                        [{"type": "dc_down", "dc_id": dc["id"], "ticks": 8, "reason": "cyber_attack"}, {"type": "cash", "cents": -1_000_000}], bad=True)]),
                opt("Pay the ransom", "Certain, but expensive", 4_000_000, [out(1.0, "The attackers disappeared. Nobody talks about it.")]),
            ]}


def t_big_customer(c):
    if not c["dcs"]:
        return None
    dc = c["rng"].choice(c["dcs"])
    units = 400
    rate = int(units * cfg.BASE_RATE_CENTS * 1.6)
    spec = {"type": "contract", "region_id": dc["region_id"], "kind": "compute", "resource": "cpu", "units": units,
            "revenue": rate, "penalty": rate * 72, "days": 30, "name": "Megacorp Global", "premium": 1}
    better = dict(spec, revenue=int(rate * 1.25), penalty=int(rate * 1.25) * 72)
    return {"kind": "big_customer", "title": "Big customer wants you", "default": 2,
            "body": "Megacorp Global wants %d CPU units for 30 days at %s/h. It is a premium contract: it needs redundant racks "
                    "and a breach costs a lot. Do you have the capacity?" % (units, _m(rate)),
            "options": [
                opt("Sign the contract", "Starts immediately", 0, [out(1.0, "Contract signed. Make sure you can deliver!", [spec])]),
                opt("Negotiate a better price", "50 % chance of +25 % revenue", 0, [
                    out(0.5, "They agreed to a better price. Contract signed.", [better]),
                    out(0.5, "They walked away and went to a competitor.", bad=True)]),
                opt("Decline", "No risk", 0, [out(1.0, "You declined politely.")]),
            ]}


def t_audit(c):
    if not c["dcs"]:
        return None
    return {"kind": "audit", "title": "Authority audit announced", "default": 1,
            "body": "The regulator will inspect your facilities for safety and data protection next week.",
            "options": [
                opt("Prepare thoroughly", "Safe", 1_200_000, [out(1.0, "The audit went smoothly. No findings.")]),
                opt("Skip the preparation", "Free, but risky", 0, [
                    out(0.65, "You were lucky. The inspector found nothing."),
                    out(0.35, "The inspector found violations. Fine: %s." % _m(3_000_000), [{"type": "cash", "cents": -3_000_000}], bad=True)]),
            ]}


def t_energy(c):
    dc = c["rng"].choice(c["dcs"]) if c["dcs"] else None
    if dc is None:
        return None
    region = c["regions"][dc["region_id"]]
    return {"kind": "energy", "title": "Energy crisis in %s" % region["name"], "default": 1,
            "body": "Electricity prices in %s are about to jump by 50 %% for three days." % region["name"],
            "options": [
                opt("Sign a fixed-price deal", "Safe", 1_800_000, [out(1.0, "You locked in the old price. Nice.")]),
                opt("Ride it out", "Free, but costly", 0, [
                    out(1.0, "Prices spiked as expected.", [{"type": "region_event", "kind": "power_spike", "region_id": region["id"], "ticks": 72,
                                                              "message": "Power prices spike in %s" % region["name"]}], bad=True)]),
            ]}


def t_poach(c):
    if not c["employees"]:
        return None
    e = c["rng"].choice(c["employees"])
    rival = c["rivals"][0]["name"] if c["rivals"] else "A competitor"
    raise_cents = int(e["salary_cents_per_tick"] * 0.2)
    return {"kind": "poach", "title": "%s is being poached" % e["name"], "default": 2,
            "body": "%s offers %s a job. %s is one of your %ss with skill %d." % (rival, e["name"], e["name"], e["role"], e["skill"]),
            "options": [
                opt("Raise the salary by 20 %", "Stays for good", 0, [out(1.0, "%s accepted and stays." % e["name"], [{"type": "employee_raise", "employee_id": e["id"], "pct": 20}])]),
                opt("Offer a one-time bonus", "70 % chance to stay", 1_000_000, [
                    out(0.7, "%s accepted the bonus and stays." % e["name"]),
                    out(0.3, "%s left anyway." % e["name"], [{"type": "employee_quit", "employee_id": e["id"]}], bad=True)]),
                opt("Let them go", "Free", 0, [out(1.0, "%s left for the competitor." % e["name"], [{"type": "employee_quit", "employee_id": e["id"]}], bad=True)]),
            ]}


def t_scandal(c):
    if not c["dcs"] or not c["rivals"]:
        return None
    dc = c["rng"].choice(c["dcs"])
    region = c["regions"][dc["region_id"]]
    rival = c["rng"].choice(c["rivals"])["name"]
    return {"kind": "scandal", "title": "%s had a big outage" % rival, "default": 1,
            "body": "Customers in %s are unhappy with %s and are looking for alternatives." % (region["name"], rival),
            "options": [
                opt("Launch a marketing campaign", "Brings new offers", 1_000_000, [
                    out(1.0, "Four new customers asked for offers.", [{"type": "offers", "region_id": region["id"], "count": 4}])]),
                opt("Do nothing", "Free", 0, [out(1.0, "Nothing happened.")]),
            ]}


def t_heatwave(c):
    dc = c["rng"].choice(c["dcs"]) if c["dcs"] else None
    if dc is None:
        return None
    region = c["regions"][dc["region_id"]]
    return {"kind": "heatwave", "title": "Record heatwave forecast for %s" % region["name"], "default": 1,
            "body": "Temperatures will be extreme for three days. Cooling capacity drops by 20 %.",
            "options": [
                opt("Rent mobile cooling units", "Safe", 800_000, [out(1.0, "The mobile units kept everything cool.")]),
                opt("Hope for the best", "Free, but risky", 0, [
                    out(1.0, "The heatwave hit hard. Watch your temperatures!", [{"type": "region_event", "kind": "heatwave", "region_id": region["id"], "ticks": 72,
                                                                                    "message": "Heatwave in %s: cooling capacity reduced" % region["name"]}], bad=True)]),
            ]}


def t_grant(c):
    if not c["dcs"]:
        return None
    return {"kind": "grant", "title": "Green datacenter grant", "default": 1,
            "body": "The government pays up to %s to operators who invest in efficient datacenters. Applications are free but not always successful." % _m(5_000_000),
            "options": [
                opt("Apply for the grant", "60 %% chance of %s" % _m(5_000_000), 0, [
                    out(0.6, "Your application was approved: %s." % _m(5_000_000), [{"type": "cash", "cents": 5_000_000}]),
                    out(0.4, "Your application was rejected.")]),
                opt("Ignore it", "Nothing happens", 0, [out(1.0, "You let it pass.")]),
            ]}


TEMPLATES = [t_fire, t_cyber, t_big_customer, t_audit, t_energy, t_poach, t_scandal, t_heatwave, t_grant]


# ---------------------------------------------------------------- creation

def _context(db, world, company, tick, rng):
    import sim   # local import: sim imports this module
    dcs = sim.load_assets(db, company["id"])
    return {
        "rng": rng, "dcs": dcs, "dcs_with_racks": [d for d in dcs if any(r["items"] for r in d["racks"])],
        "regions": {r["id"]: r for r in db.execute("SELECT * FROM regions WHERE world_id = ?", (world["id"],))},
        "employees": db.execute("SELECT * FROM employees WHERE company_id = ?", (company["id"],)).fetchall(),
        "rivals": db.execute("SELECT * FROM companies WHERE world_id = ? AND is_ai = 1", (world["id"],)).fetchall(),
    }


def maybe_create(db, world, company, tick, rng):
    """Called once per day: sometimes confronts the player with a decision."""
    if tick < FIRST_DECISION_TICK or rng.random() >= CHANCE_PER_DAY:
        return None
    last = db.execute("SELECT MAX(created_tick) FROM decisions WHERE company_id = ?", (company["id"],)).fetchone()[0]
    open_n = db.execute("SELECT COUNT(*) FROM decisions WHERE company_id = ? AND status = 'open'", (company["id"],)).fetchone()[0]
    if open_n or (last is not None and tick - last < MIN_GAP_TICKS):
        return None
    ctx = _context(db, world, company, tick, rng)
    built = [d for d in (t(ctx) for t in TEMPLATES) if d]
    if not built:
        return None
    d = rng.choice(built)
    cur = db.execute(
        "INSERT INTO decisions (company_id, kind, title, body, options_json, default_option, created_tick, expires_tick)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (company["id"], d["kind"], d["title"], d["body"], json.dumps(d["options"]), d["default"], tick, tick + LIFETIME_TICKS))
    add_event(db, world["id"], tick, "decision", "Decision needed: %s" % d["title"], company_id=company["id"])
    return cur.lastrowid


# ---------------------------------------------------------------- resolution

def _apply(db, world, company, effect, rng, tick):
    kind = effect["type"]
    cid, wid = company["id"], world["id"]
    if kind == "cash":
        change_cash(db, cid, effect["cents"])
        book(db, wid, cid, tick, "event" if effect["cents"] < 0 else "grant", effect["cents"], "Event")
    elif kind in ("rack_down", "dc_down"):
        rows = db.execute("SELECT r.id FROM racks r WHERE r.datacenter_id = ? AND EXISTS (SELECT 1 FROM rack_items i WHERE i.rack_id = r.id)", (effect["dc_id"],)).fetchall()
        if kind == "rack_down" and rows:
            rows = [rng.choice(rows)]
        for r in rows:
            db.execute("UPDATE racks SET status = 'down', down_until_tick = ?, down_reason = ? WHERE id = ? AND status = 'ok'",
                       (tick + effect["ticks"], effect["reason"], r["id"]))
    elif kind == "rack_loss":
        rows = db.execute("SELECT r.id FROM racks r WHERE r.datacenter_id = ? AND EXISTS (SELECT 1 FROM rack_items i WHERE i.rack_id = r.id)", (effect["dc_id"],)).fetchall()
        if rows:
            db.execute("DELETE FROM racks WHERE id = ?", (rng.choice(rows)["id"],))
    elif kind == "region_event":
        add_event(db, wid, tick, effect["kind"], effect["message"], region_id=effect["region_id"], ends_tick=tick + effect["ticks"])
    elif kind == "offers":
        market.seed_offers(db, dict(world, tick=tick), tick, effect["region_id"], effect["count"])
    elif kind == "employee_quit":
        emp = db.execute("SELECT * FROM employees WHERE id = ? AND company_id = ?", (effect["employee_id"], cid)).fetchone()
        if emp:
            if emp["order_id"]:
                db.execute("UPDATE work_orders SET status = 'queued', employee_id = NULL WHERE id = ? AND status = 'in_progress'", (emp["order_id"],))
            db.execute("DELETE FROM employees WHERE id = ?", (emp["id"],))
    elif kind == "employee_raise":
        db.execute("UPDATE employees SET salary_cents_per_tick = CAST(salary_cents_per_tick * ? AS INTEGER) WHERE id = ? AND company_id = ?",
                   (1 + effect["pct"] / 100.0, effect["employee_id"], cid))
    elif kind == "contract":
        units_eq = effect["units"] * cfg.UNIT_WEIGHT[effect["resource"]]
        db.execute(
            "INSERT INTO contracts (world_id, company_id, region_id, kind, name, resource, units, units_eq, premium, revenue_cents_per_tick,"
            " penalty_cents, duration_ticks, offered_tick, offer_expires_tick, start_tick, end_tick, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (wid, cid, effect["region_id"], effect["kind"], effect["name"], effect["resource"], effect["units"], units_eq,
             effect["premium"], effect["revenue"], effect["penalty"], effect["days"] * 24, tick, tick, tick, tick + effect["days"] * 24))
        market.compute_market(db, wid, tick, persist=True)


def resolve(db, world, company, decision_id, option_index, forced=False):
    """Apply the chosen option. `forced` = the time ran out: the default option applies for free."""
    d = db.execute("SELECT * FROM decisions WHERE id = ? AND company_id = ? AND status = 'open'", (decision_id, company["id"])).fetchone()
    if d is None:
        raise DecisionError("This decision is no longer open")
    options = json.loads(d["options_json"])
    if not isinstance(option_index, int) or isinstance(option_index, bool) or not 0 <= option_index < len(options):
        raise DecisionError("Unknown option")
    option = options[option_index]
    tick = world["tick"]
    cost = 0 if forced else option["cost_cents"]
    if cost:
        cash = db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company["id"],)).fetchone()[0]
        if cost > cash:
            raise DecisionError("Not enough cash (need %s)" % _m(cost))
        change_cash(db, company["id"], -cost)
        book(db, world["id"], company["id"], tick, "event", -cost, d["title"])
    rng = random.Random(decision_id * 104729 + tick)
    roll, acc, chosen = rng.random(), 0.0, option["outcomes"][-1]
    for o in option["outcomes"]:
        acc += o["p"]
        if roll < acc:
            chosen = o
            break
    for effect in chosen["effects"]:
        _apply(db, world, company, effect, rng, tick)
    text = ("No decision was made in time. " if forced else "") + chosen["text"]
    db.execute("UPDATE decisions SET status = 'resolved', result = ? WHERE id = ?", (text, decision_id))
    add_event(db, world["id"], tick, "decision_result", "%s: %s" % (d["title"], text), company_id=company["id"])
    return {"text": text, "bad": bool(chosen["bad"])}


def expire(db, world, company, tick):
    """Open decisions whose time ran out get their default option."""
    rows = db.execute("SELECT id, default_option FROM decisions WHERE company_id = ? AND status = 'open' AND expires_tick < ?", (company["id"], tick)).fetchall()
    for r in rows:
        resolve(db, dict(world, tick=tick), company, r["id"], r["default_option"], forced=True)


def open_decisions(db, company_id):
    rows = db.execute("SELECT * FROM decisions WHERE company_id = ? AND status = 'open' ORDER BY id", (company_id,)).fetchall()
    result = []
    for d in rows:
        options = json.loads(d["options_json"])
        result.append({
            "id": d["id"], "kind": d["kind"], "title": d["title"], "body": d["body"], "expires_tick": d["expires_tick"],
            "default_option": d["default_option"],
            "options": [{"label": o["label"], "hint": o["hint"], "cost_cents": o["cost_cents"],
                         "risk": round(sum(x["p"] for x in o["outcomes"] if x["bad"]), 2)} for o in options],
        })
    return result
