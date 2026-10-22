"""Static seed data for new worlds: regions and AI rivals.

Region values (demand, power price, temperature, land cost) are rough
estimates meant to be tuned. Rival names are parodies on purpose.
"""

# code, name, lat, lon, demand_index, power_price_cents_kwh, avg_temp_c, land_cost_index
REGIONS = [
    ("FRA", "Frankfurt", 50.11, 8.68, 1.4, 22.0, 10.0, 1.3),
    ("AMS", "Amsterdam", 52.37, 4.90, 1.2, 18.0, 10.5, 1.4),
    ("LON", "London", 51.51, -0.13, 1.3, 24.0, 11.0, 1.8),
    ("STO", "Stockholm", 59.33, 18.07, 0.7, 6.0, 7.0, 0.8),
    ("VIR", "Virginia", 38.95, -77.45, 1.8, 8.0, 13.0, 0.9),
    ("OHI", "Ohio", 40.00, -83.00, 1.0, 7.0, 11.0, 0.5),
    ("OREG", "Oregon", 45.60, -121.18, 0.8, 5.0, 10.0, 0.4),
    ("SAO", "Sao Paulo", -23.55, -46.63, 0.9, 12.0, 20.0, 0.7),
    ("SIN", "Singapore", 1.35, 103.82, 1.3, 15.0, 27.0, 2.0),
    ("TOK", "Tokyo", 35.68, 139.69, 1.5, 20.0, 16.0, 2.2),
    ("MUM", "Mumbai", 19.08, 72.88, 1.1, 9.0, 27.0, 0.6),
    ("SYD", "Sydney", -33.87, 151.21, 0.8, 17.0, 18.0, 1.2),
]

# Regions the player may build in at the start of a world.
STARTER_REGION_CODES = ("FRA",)

# name, color, strategy
AI_RIVALS = [
    ("Googol", "#e8453c", "aggressive"),
    ("Microsoftie", "#2fb344", "balanced"),
    ("Amazen Web Services", "#f5a623", "frugal"),
    ("Oraclet", "#b0413e", "balanced"),
    ("Alibabble Cloud", "#ff6a00", "aggressive"),
]
