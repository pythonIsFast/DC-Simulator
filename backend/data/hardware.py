"""Hardware catalog: the single place to balance power, heat, ports and prices.

All numbers are rough estimates. Prices are given in whole currency units and
converted to cents. Heat equals electrical power (all power ends up as heat).

Categories:
  server_cpu / server_storage / server_gpu   rack servers, attrs: nic (ports needed) + capacity
  switch_tor                                 top-of-rack switch, ports = downlinks, attrs.uplinks
  pdu                                        attrs.max_w
  ups                                        attrs.ups_w (rides through grid outages)
  patch_panel / cable_mgmt / blank           small helpers
  dc_agg / dc_crac / dc_feed                 datacenter level (u_height 0, not rack mounted)
"""

# code, category, name, u_height, power_w, ports, price, attrs
_RAW = [
    ("cpu_1u", "server_cpu", "Compute 1U", 1, 250, 0, 2_500, {"nic": 1, "cpu": 16}),
    ("cpu_2u", "server_cpu", "Compute 2U Dual", 2, 450, 0, 6_500, {"nic": 2, "cpu": 44}),
    ("sto_2u", "server_storage", "Storage 2U (96 TB)", 2, 350, 0, 5_200, {"nic": 1, "storage_tb": 96}),
    ("sto_4u", "server_storage", "Storage 4U (384 TB)", 4, 600, 0, 14_000, {"nic": 2, "storage_tb": 384}),
    ("gpu_2u", "server_gpu", "GPU Node 2U", 2, 1_200, 0, 28_000, {"nic": 2, "gpu": 40}),
    ("gpu_4u", "server_gpu", "GPU Node 4U (8 GPUs)", 4, 3_200, 0, 80_000, {"nic": 4, "gpu": 120}),
    ("tor_24", "switch_tor", "ToR Switch 24x10G", 1, 100, 24, 1_800, {"uplinks": 2}),
    ("tor_48", "switch_tor", "ToR Switch 48x10G", 1, 160, 48, 3_200, {"uplinks": 4}),
    ("pdu_3k6", "pdu", "PDU 3.6 kW", 1, 0, 0, 400, {"max_w": 3_600}),
    ("pdu_7k2", "pdu", "PDU 7.2 kW", 1, 0, 0, 900, {"max_w": 7_200}),
    ("ups_2u", "ups", "Rack UPS 2U (5 kW)", 2, 40, 0, 1_800, {"ups_w": 5_000}),
    ("patch_1u", "patch_panel", "Patch Panel 1U", 1, 0, 0, 150, {}),
    ("cable_1u", "cable_mgmt", "Cable Management 1U", 1, 0, 0, 100, {}),
    ("blank_1u", "blank", "Blanking Panel 1U", 1, 0, 0, 8, {}),
    ("dc_agg", "dc_agg", "Aggregation Switch 32x40G", 0, 400, 32, 18_000, {}),
    ("dc_crac", "dc_crac", "Cooling Unit (40 kW)", 0, 0, 0, 22_000, {"cooling_kw": 40}),
    ("dc_feed", "dc_feed", "Power Feed (+100 kW)", 0, 0, 0, 30_000, {"power_kw": 100}),
]

HARDWARE = [
    {
        "code": code, "category": cat, "name": name, "u_height": u, "power_w": power,
        "heat_w": power, "ports": ports, "price_cents": price * 100, "attrs": attrs,
    }
    for code, cat, name, u, power, ports, price, attrs in _RAW
]

DC_CATEGORIES = ("dc_agg", "dc_crac", "dc_feed")
STARTER_DC_EQUIPMENT = {"dc_agg": 1}
