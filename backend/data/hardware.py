"""Hardware catalog: the single place to balance power, heat, ports and prices.

All numbers are rough estimates. Prices are given in whole currency units and
converted to cents. Heat equals electrical power (all power ends up as heat).

Categories:
  server_cpu / server_storage / server_gpu   rack servers, attrs: nic (ports needed) + capacity
  switch_tor                                 top-of-rack switch, ports = downlinks, attrs.uplinks
  pdu                                        attrs.max_w
  ups                                        attrs.ups_w (rides through grid outages)
  fan_panel                                  attrs.heat_reduction (fraction of rack heat)
  patch_panel / cable_mgmt / blank           small helpers
  dc_agg / dc_crac / dc_feed                 datacenter level (u_height 0, not rack mounted)
"""

# code, category, name, u_height, power_w, ports, price, attrs
_RAW = [
    # --- compute servers
    ("cpu_1u_entry", "server_cpu", "Compute 1U Entry", 1, 200, 0, 1_800, {"nic": 1, "cpu": 10}),
    ("cpu_1u", "server_cpu", "Compute 1U", 1, 250, 0, 2_500, {"nic": 1, "cpu": 16}),
    ("cpu_1u_dense", "server_cpu", "Compute 1U Dense", 1, 350, 0, 4_200, {"nic": 1, "cpu": 28}),
    ("cpu_2u", "server_cpu", "Compute 2U Dual", 2, 450, 0, 6_500, {"nic": 2, "cpu": 44}),
    ("cpu_2u_hpc", "server_cpu", "Compute 2U High-Core", 2, 700, 0, 11_000, {"nic": 2, "cpu": 80}),
    ("cpu_4u_quad", "server_cpu", "Compute 4U Quad", 4, 1_200, 0, 20_000, {"nic": 4, "cpu": 150}),
    # --- storage servers
    ("sto_1u_nvme", "server_storage", "NVMe Storage 1U (30 TB)", 1, 300, 0, 4_500, {"nic": 1, "storage_tb": 30}),
    ("sto_2u", "server_storage", "Storage 2U (96 TB)", 2, 350, 0, 5_200, {"nic": 1, "storage_tb": 96}),
    ("sto_2u_dense", "server_storage", "Storage 2U Dense (200 TB)", 2, 400, 0, 9_000, {"nic": 2, "storage_tb": 200}),
    ("sto_4u", "server_storage", "Storage 4U (384 TB)", 4, 600, 0, 14_000, {"nic": 2, "storage_tb": 384}),
    ("sto_4u_jbod", "server_storage", "Storage 4U Petabyte (1 PB)", 4, 800, 0, 30_000, {"nic": 4, "storage_tb": 1_000}),
    # --- GPU / AI servers
    ("gpu_2u_entry", "server_gpu", "GPU Node 2U Entry (4 GPUs)", 2, 900, 0, 16_000, {"nic": 2, "gpu": 24}),
    ("gpu_2u", "server_gpu", "GPU Node 2U", 2, 1_200, 0, 28_000, {"nic": 2, "gpu": 40}),
    ("gpu_4u", "server_gpu", "GPU Node 4U (8 GPUs)", 4, 3_200, 0, 80_000, {"nic": 4, "gpu": 120}),
    ("gpu_4u_max", "server_gpu", "GPU Node 4U Max (liquid)", 4, 5_000, 0, 130_000, {"nic": 4, "gpu": 220}),
    # --- top-of-rack switches (ports = downlinks)
    ("tor_12", "switch_tor", "ToR Switch 12x10G", 1, 60, 12, 900, {"uplinks": 2}),
    ("tor_24", "switch_tor", "ToR Switch 24x10G", 1, 100, 24, 1_800, {"uplinks": 2}),
    ("tor_48", "switch_tor", "ToR Switch 48x10G", 1, 160, 48, 3_200, {"uplinks": 4}),
    ("tor_48_25g", "switch_tor", "ToR Switch 48x25G", 1, 220, 48, 6_500, {"uplinks": 4}),
    ("tor_32_100g", "switch_tor", "ToR Switch 32x100G", 1, 300, 32, 14_000, {"uplinks": 4}),
    # --- power
    ("pdu_2k4", "pdu", "PDU 2.4 kW", 1, 0, 0, 250, {"max_w": 2_400}),
    ("pdu_3k6", "pdu", "PDU 3.6 kW", 1, 0, 0, 400, {"max_w": 3_600}),
    ("pdu_7k2", "pdu", "PDU 7.2 kW", 1, 0, 0, 900, {"max_w": 7_200}),
    ("pdu_11k", "pdu", "PDU 11 kW", 1, 0, 0, 1_500, {"max_w": 11_000}),
    ("ups_1u", "ups", "Rack UPS 1U (2 kW)", 1, 20, 0, 900, {"ups_w": 2_000}),
    ("ups_2u", "ups", "Rack UPS 2U (5 kW)", 2, 40, 0, 1_800, {"ups_w": 5_000}),
    ("ups_4u", "ups", "Rack UPS 4U (12 kW)", 4, 80, 0, 4_500, {"ups_w": 12_000}),
    # --- extras
    ("fan_1u", "fan_panel", "Cooling Fan Panel 1U", 1, 60, 0, 350, {"heat_reduction": 0.04}),
    ("patch_1u", "patch_panel", "Patch Panel 1U", 1, 0, 0, 150, {}),
    ("cable_1u", "cable_mgmt", "Cable Management 1U", 1, 0, 0, 100, {}),
    ("blank_1u", "blank", "Blanking Panel 1U", 1, 0, 0, 8, {}),
    # --- datacenter level
    ("dc_agg", "dc_agg", "Aggregation Switch 32x40G", 0, 400, 32, 18_000, {}),
    ("dc_agg_big", "dc_agg", "Aggregation Switch 64x100G", 0, 900, 64, 48_000, {}),
    ("dc_crac_small", "dc_crac", "In-row Cooling (20 kW)", 0, 0, 0, 12_000, {"cooling_kw": 20}),
    ("dc_crac", "dc_crac", "Cooling Unit (40 kW)", 0, 0, 0, 22_000, {"cooling_kw": 40}),
    ("dc_chiller", "dc_crac", "Chiller Plant (120 kW)", 0, 0, 0, 58_000, {"cooling_kw": 120}),
    ("dc_feed", "dc_feed", "Power Feed (+100 kW)", 0, 0, 0, 30_000, {"power_kw": 100}),
    ("dc_feed_big", "dc_feed", "Power Feed (+250 kW)", 0, 0, 0, 65_000, {"power_kw": 250}),
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
