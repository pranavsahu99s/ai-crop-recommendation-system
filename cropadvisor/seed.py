"""Reference data loaded into a fresh database.

Climate figures are season averages: temperature in °C, humidity in %, and
rainfall as mean monthly rainfall (mm/month) over the growing season. Rabi
crops are normally irrigated, so their rainfall floor is low.
"""

DEMO_ADMIN = {"username": "admin", "name": "System Administrator", "password": "admin123"}
DEMO_FARMER = {"name": "Ramesh Patel", "location": "Jaipur", "contact_no": "9123456789", "password": "farmer123"}

SEASONS = ("Kharif", "Rabi", "Zaid")

SEASON_INFO = {
    "Kharif": "Monsoon crop, sown June–July, harvested September–October",
    "Rabi": "Winter crop, sown October–December, harvested March–April",
    "Zaid": "Short summer crop between Rabi and Kharif, March–June",
}

SOIL_TYPES = [
    {"name": "Alluvial", "n": 80, "p": 45, "k": 50, "ph": 7.0, "drainage": "Good",
     "description": "River-deposited soil of the Indo-Gangetic plains. Fertile, rich in potash."},
    {"name": "Black", "n": 60, "p": 40, "k": 70, "ph": 7.8, "drainage": "Poor",
     "description": "Regur soil of the Deccan plateau. Holds moisture well; suited to cotton."},
    {"name": "Red", "n": 45, "p": 30, "k": 35, "ph": 6.3, "drainage": "Good",
     "description": "Iron-rich soil of the southern and eastern plateau. Low in nitrogen and phosphorus."},
    {"name": "Loamy", "n": 75, "p": 50, "k": 50, "ph": 6.8, "drainage": "Good",
     "description": "Balanced mix of sand, silt and clay. Suits most field crops."},
    {"name": "Sandy", "n": 35, "p": 22, "k": 28, "ph": 7.6, "drainage": "Very good",
     "description": "Arid-zone soil of western Rajasthan. Low organic matter and water holding."},
    {"name": "Clayey", "n": 85, "p": 48, "k": 55, "ph": 7.3, "drainage": "Poor",
     "description": "Heavy, fine-textured soil that retains water. Good for paddy."},
    {"name": "Laterite", "n": 30, "p": 18, "k": 25, "ph": 5.4, "drainage": "Good",
     "description": "Leached, acidic soil of high-rainfall areas. Needs liming and manure."},
]


def _crop(name, category, seasons, soils, temp, tol, rain, hum, n, p, k, ph, water, days, guidance):
    return {
        "name": name, "category": category, "seasons": seasons, "soils": soils,
        "temp": temp, "tol": tol, "rain_min": rain[0], "rain_max": rain[1],
        "hum_min": hum[0], "hum_max": hum[1], "n_min": n[0], "n_max": n[1],
        "p_min": p[0], "p_max": p[1], "k_min": k[0], "k_max": k[1],
        "ph_min": ph[0], "ph_max": ph[1], "water": water, "days": days, "guidance": guidance,
    }


CROPS = [
    _crop("Rice", "Cereal", "Kharif", "Clayey,Alluvial,Loamy", 28, 5, (150, 500), (70, 95),
          (60, 120), (30, 60), (30, 60), (5.0, 7.2), "High", 120,
          "Transplant 25-day seedlings. Keep 2–5 cm standing water until panicle initiation. "
          "Apply nitrogen in three splits."),
    _crop("Wheat", "Cereal", "Rabi", "Loamy,Alluvial,Clayey,Black", 18, 5, (5, 60), (40, 75),
          (80, 150), (40, 70), (30, 60), (6.0, 7.8), "Medium", 130,
          "Sow in the first half of November. The crown-root irrigation at 21 days is the most important one."),
    _crop("Maize", "Cereal", "Kharif,Rabi,Zaid", "Loamy,Alluvial,Red", 26, 6, (50, 150), (50, 85),
          (60, 120), (35, 70), (25, 55), (5.6, 7.5), "Medium", 100,
          "Needs well-drained land; waterlogging for more than two days damages the crop. "
          "Top-dress nitrogen at knee height."),
    _crop("Pearl Millet (Bajra)", "Millet", "Kharif,Zaid", "Sandy,Loamy,Red", 30, 6, (25, 110), (30, 75),
          (30, 80), (15, 45), (15, 40), (6.0, 8.2), "Low", 85,
          "Tolerates drought and sandy soil. Sow with the first monsoon rain; thin to 12–15 cm spacing."),
    _crop("Chickpea (Gram)", "Pulse", "Rabi", "Loamy,Black,Sandy", 20, 5, (0, 40), (30, 65),
          (15, 45), (40, 80), (20, 50), (6.0, 8.0), "Low", 110,
          "Treat seed with Rhizobium culture. One irrigation at flowering is usually enough; avoid excess water."),
    _crop("Mustard", "Oilseed", "Rabi", "Loamy,Sandy,Alluvial", 17, 5, (0, 40), (35, 70),
          (50, 100), (25, 50), (20, 45), (6.0, 8.0), "Low", 120,
          "Thin plants 15–20 days after sowing. Watch for aphids in December–January."),
    _crop("Cotton", "Fibre", "Kharif", "Black,Alluvial,Loamy", 29, 5, (50, 130), (45, 80),
          (80, 140), (30, 60), (30, 70), (6.0, 8.2), "Medium", 170,
          "Keep the field weed-free for the first 45 days. Scout weekly for pink bollworm."),
    _crop("Sugarcane", "Cash crop", "Kharif,Zaid", "Loamy,Alluvial,Black", 28, 6, (75, 200), (55, 90),
          (120, 200), (50, 90), (60, 120), (6.0, 7.8), "High", 330,
          "Plant three-bud setts. Earth up at 90–120 days to prevent lodging."),
    _crop("Groundnut", "Oilseed", "Kharif,Zaid", "Sandy,Loamy,Red", 28, 5, (40, 120), (45, 80),
          (15, 40), (35, 65), (25, 55), (5.8, 7.5), "Medium", 110,
          "Needs loose soil for pegging. Apply gypsum at flowering (30–40 days)."),
    _crop("Soybean", "Oilseed", "Kharif", "Black,Loamy,Clayey", 27, 5, (80, 200), (60, 90),
          (20, 50), (50, 80), (30, 60), (6.0, 7.5), "Medium", 100,
          "Sow after 100 mm of monsoon rain. Ensure field drainage; the crop does not tolerate standing water."),
    _crop("Green Gram (Moong)", "Pulse", "Kharif,Zaid", "Loamy,Sandy,Red", 29, 5, (30, 110), (45, 80),
          (15, 40), (30, 60), (15, 40), (6.2, 7.6), "Low", 70,
          "Short-duration pulse that fits between Rabi and Kharif. Harvest pods in two to three pickings."),
    _crop("Potato", "Vegetable", "Rabi", "Loamy,Sandy,Alluvial", 17, 4, (5, 60), (55, 85),
          (90, 150), (50, 90), (80, 150), (5.2, 6.8), "Medium", 100,
          "Plant on ridges. Earth up 30–35 days after planting so tubers are not exposed to light."),
    _crop("Tomato", "Vegetable", "Rabi,Zaid", "Loamy,Red,Alluvial", 22, 5, (10, 90), (50, 80),
          (80, 130), (50, 80), (50, 100), (6.0, 7.0), "Medium", 120,
          "Stake plants early. Keep soil moisture even to prevent blossom-end rot."),
    _crop("Barley", "Cereal", "Rabi", "Sandy,Loamy,Alluvial", 16, 5, (0, 50), (30, 70),
          (40, 80), (20, 45), (20, 45), (6.5, 8.5), "Low", 120,
          "Tolerates mildly saline and alkaline soil better than wheat. Two to three irrigations are sufficient."),
    _crop("Watermelon", "Fruit", "Zaid", "Sandy,Loamy", 31, 5, (0, 50), (30, 65),
          (50, 100), (30, 60), (40, 90), (6.0, 7.5), "Medium", 85,
          "Sow on raised beds or river-bed sand. Reduce irrigation once fruits reach full size."),
]
