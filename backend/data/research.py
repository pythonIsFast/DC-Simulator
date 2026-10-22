"""Research tree. Techs unlock hardware or give permanent bonuses. All numbers are estimates.

effects keys: pue (added to the facility power overhead), tech_speed (technician work speed),
incident_mult (added to the incident probability multiplier), revenue_mult (added to contract revenue).
"""

MAX_PARALLEL_RESEARCH = 2
ADMIN_RESEARCH_SPEED_PER_SKILL = 0.1     # research runs faster with skilled admins (max +100 %)

# code, name, description, branch, cost in currency units, ticks, requires, unlocks (hardware codes), effects
_RAW = [
    ("dense_compute", "Dense Compute", "More cores per server.", "Compute", 30_000, 48, [], ["cpu_1u_dense", "cpu_2u_hpc"], {}),
    ("quad_socket", "Quad-Socket Systems", "The biggest compute servers.", "Compute", 60_000, 72, ["dense_compute"], ["cpu_4u_quad"], {}),
    ("nvme", "NVMe Storage", "Fast flash storage servers.", "Storage", 30_000, 48, [], ["sto_1u_nvme"], {}),
    ("dense_storage", "Dense Storage", "200 TB in two rack units.", "Storage", 50_000, 72, [], ["sto_2u_dense"], {}),
    ("petabyte", "Petabyte Arrays", "A petabyte in four rack units.", "Storage", 90_000, 96, ["dense_storage"], ["sto_4u_jbod"], {}),
    ("gpu_basics", "GPU Computing", "Servers with GPUs for AI customers.", "GPU / AI", 50_000, 72, [], ["gpu_2u_entry", "gpu_2u"], {}),
    ("gpu_cluster", "GPU Clusters", "Eight GPUs per node.", "GPU / AI", 120_000, 120, ["gpu_basics"], ["gpu_4u"], {}),
    ("liquid_cooling", "Liquid Cooling", "Needed for the largest GPU nodes, also cuts cooling overhead.", "GPU / AI", 150_000, 120, ["gpu_cluster"], ["gpu_4u_max"], {"pue": -0.03}),
    ("net_25g", "25G Networking", "Faster top-of-rack switches.", "Network", 40_000, 48, [], ["tor_48_25g"], {}),
    ("net_100g", "100G Networking", "100G switches and big aggregation.", "Network", 100_000, 96, ["net_25g"], ["tor_32_100g", "dc_agg_big"], {}),
    ("hv_power", "High-Power Racks", "11 kW PDUs.", "Facility", 25_000, 48, [], ["pdu_11k"], {}),
    ("battery", "Battery Backup", "Large rack UPS.", "Facility", 25_000, 48, [], ["ups_4u"], {}),
    ("chillers", "Industrial Cooling", "Chiller plants and big power feeds.", "Facility", 70_000, 72, [], ["dc_chiller", "dc_feed_big"], {}),
    ("free_cooling", "Free Cooling", "Use outside air: lower power overhead.", "Facility", 80_000, 96, ["chillers"], [], {"pue": -0.05}),
    ("heat_reuse", "Heat Reuse", "Sell waste heat: lower power overhead.", "Facility", 150_000, 120, ["free_cooling"], [], {"pue": -0.05}),
    ("automation", "Automation", "Technicians work 25 % faster.", "Operations", 40_000, 72, [], [], {"tech_speed": 0.25}),
    ("monitoring", "Monitoring", "20 % fewer failures.", "Operations", 35_000, 72, [], [], {"incident_mult": -0.2}),
    ("predictive", "Predictive Maintenance", "Another 20 % fewer failures.", "Operations", 90_000, 96, ["monitoring"], [], {"incident_mult": -0.2}),
    ("account_mgmt", "Key Account Management", "5 % more revenue from contracts.", "Operations", 60_000, 96, [], [], {"revenue_mult": 0.05}),
    ("brand", "Strong Brand", "Another 5 % more revenue.", "Operations", 120_000, 120, ["account_mgmt"], [], {"revenue_mult": 0.05}),
]

TECHS = [
    {"code": c, "name": n, "desc": d, "branch": b, "cost_cents": cost * 100, "ticks": t, "requires": req, "unlocks": unl, "effects": eff}
    for c, n, d, b, cost, t, req, unl, eff in _RAW
]
TECH_BY_CODE = {t["code"]: t for t in TECHS}
HARDWARE_TECH = {hw: t["code"] for t in TECHS for hw in t["unlocks"]}
