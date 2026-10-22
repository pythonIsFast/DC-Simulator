"""Research: unlocking hardware and permanent bonuses."""
from bookkeeping import add_event, book, change_cash
from data import research as data


class ResearchError(Exception):
    pass


def done_set(db, company_id):
    return {r["tech_code"] for r in db.execute("SELECT tech_code FROM research WHERE company_id = ? AND status = 'done'", (company_id,))}


def hw_allowed(code, done):
    tech = data.HARDWARE_TECH.get(code)
    return tech is None or tech in done


def require_hw(db, company_id, code):
    tech = data.HARDWARE_TECH.get(code)
    if tech is not None and tech not in done_set(db, company_id):
        raise ResearchError("Requires research: %s" % data.TECH_BY_CODE[tech]["name"])


def effects(db, company_id):
    out = {"pue": 0.0, "tech_speed": 0.0, "incident_mult": 1.0, "revenue_mult": 0.0}
    for code in done_set(db, company_id):
        for key, value in data.TECH_BY_CODE[code]["effects"].items():
            out[key] += value
    out["incident_mult"] = max(0.2, out["incident_mult"])
    return out


def start(db, world, company, code):
    tech = data.TECH_BY_CODE.get(code)
    if tech is None:
        raise ResearchError("Unknown technology")
    rows = db.execute("SELECT tech_code, status FROM research WHERE company_id = ?", (company["id"],)).fetchall()
    states = {r["tech_code"]: r["status"] for r in rows}
    if code in states:
        raise ResearchError("Already researched or in progress")
    done = {c for c, s in states.items() if s == "done"}
    missing = [data.TECH_BY_CODE[r]["name"] for r in tech["requires"] if r not in done]
    if missing:
        raise ResearchError("Requires: %s" % ", ".join(missing))
    if sum(1 for s in states.values() if s == "researching") >= data.MAX_PARALLEL_RESEARCH:
        raise ResearchError("At most %d projects at the same time" % data.MAX_PARALLEL_RESEARCH)
    cash = db.execute("SELECT cash_cents FROM companies WHERE id = ?", (company["id"],)).fetchone()[0]
    if tech["cost_cents"] > cash:
        raise ResearchError("Not enough cash (need %s)" % "{:,.0f}".format(tech["cost_cents"] / 100))
    change_cash(db, company["id"], -tech["cost_cents"])
    book(db, world["id"], company["id"], world["tick"], "research", -tech["cost_cents"], tech["name"])
    db.execute("INSERT INTO research (company_id, tech_code, status, progress) VALUES (?, ?, 'researching', 0)", (company["id"], code))


def tick(db, world, company, tick_no):
    """Advance running projects. Skilled admins speed research up."""
    rows = db.execute("SELECT * FROM research WHERE company_id = ? AND status = 'researching'", (company["id"],)).fetchall()
    if not rows:
        return
    skill = db.execute("SELECT COALESCE(SUM(skill), 0) FROM employees WHERE company_id = ? AND role = 'admin'", (company["id"],)).fetchone()[0]
    speed = 1.0 + min(1.0, data.ADMIN_RESEARCH_SPEED_PER_SKILL * skill)
    for r in rows:
        tech = data.TECH_BY_CODE[r["tech_code"]]
        progress = r["progress"] + speed
        if progress >= tech["ticks"]:
            db.execute("UPDATE research SET status = 'done', progress = ?, done_tick = ? WHERE id = ?", (tech["ticks"], tick_no, r["id"]))
            add_event(db, world["id"], tick_no, "research_done", "Research complete: %s" % tech["name"], company_id=company["id"])
        else:
            db.execute("UPDATE research SET progress = ? WHERE id = ?", (progress, r["id"]))


def state(db, company_id, hw_names):
    rows = {r["tech_code"]: r for r in db.execute("SELECT * FROM research WHERE company_id = ?", (company_id,))}
    done = {c for c, r in rows.items() if r["status"] == "done"}
    techs = []
    for t in data.TECHS:
        row = rows.get(t["code"])
        if row is not None:
            status = row["status"]
        else:
            status = "available" if all(r in done for r in t["requires"]) else "locked"
        techs.append({
            "code": t["code"], "name": t["name"], "desc": t["desc"], "branch": t["branch"], "cost_cents": t["cost_cents"],
            "ticks": t["ticks"], "requires": [data.TECH_BY_CODE[r]["name"] for r in t["requires"]], "status": status,
            "progress": (row["progress"] / t["ticks"]) if row is not None else 0.0,
            "unlocks": [hw_names.get(c, c) for c in t["unlocks"]], "effects": t["effects"],
        })
    return {"techs": techs, "done": sorted(done), "max_parallel": data.MAX_PARALLEL_RESEARCH,
            "active": sum(1 for r in rows.values() if r["status"] == "researching")}
