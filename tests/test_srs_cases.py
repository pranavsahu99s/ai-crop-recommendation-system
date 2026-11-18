"""Automated versions of the SRS Lab 10 test cases (TC-01 … TC-52).

Run with:  python -m unittest discover -s tests -v

Each test method name starts with its test-case ID. The Weather API is
replaced with a stub so that success, unknown place, outage and rate
limiting can be simulated without network access.
"""
import io
import os
import re
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from cropadvisor import create_app
from cropadvisor.db import get_db
from cropadvisor.domain import WeatherData
from cropadvisor.services import recommender
from cropadvisor.services.pdf import PdfDocument
from cropadvisor.services.weather import WeatherError

FARMER = {"name": "Sita Devi", "contact_no": "9876500001", "location": "Jaipur", "password": "secret12",
          "confirm": "secret12"}
PLOT = {"plot_name": "North field", "location": "Jaipur", "land_area": "2.5", "season": "Rabi",
        "soil_type": "Loamy", "n": "100", "p": "50", "k": "45", "ph": "7.0"}


class StubWeather:
    """Stands in for WeatherService. `mode` selects the behaviour."""

    def __init__(self):
        self.mode = "ok"
        self.calls = 0

    def fetch_weather_data(self, location, season):
        self.calls += 1
        if self.mode == "not_found":
            raise WeatherError("not_found", f"“{location}” was not found.")
        if self.mode == "down":
            raise WeatherError("unavailable", "The weather service could not be reached.")
        if self.mode == "rate_limited":
            raise WeatherError("rate_limited", "The weather service is limiting requests right now.")
        values = {"Rabi": (18.0, 8.0, 55.0), "Kharif": (29.0, 180.0, 78.0), "Zaid": (31.0, 15.0, 40.0)}[season]
        return WeatherData(location=f"{location}, Rajasthan, India", temperature=values[0], rainfall=values[1],
                           humidity=values[2], source="open-meteo", season=season,
                           period="01 Nov 2025 – 31 Mar 2026", latitude=26.9, longitude=75.8)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("config.TestConfig", DATABASE=os.path.join(self.tmp.name, "test.db"),
                              WEATHER_ENABLED=True, WTF_CSRF_DISABLED=True)
        self.weather = StubWeather()
        self.app.extensions["weather_service"] = self.weather
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # helpers ---------------------------------------------------------------
    def db_query(self, sql, *args):
        with self.app.app_context():
            return get_db().execute(sql, args).fetchall()

    def register(self, **overrides):
        return self.client.post("/register", data=FARMER | overrides)

    def login_farmer(self, contact=FARMER["contact_no"], password=FARMER["password"], client=None):
        return (client or self.client).post("/login", data={"role": "farmer", "identifier": contact,
                                                            "password": password})

    def login_admin(self, client=None):
        return (client or self.client).post("/login", data={"role": "admin", "identifier": "admin",
                                                            "password": "admin123"})

    def farmer_session(self):
        self.register()
        self.login_farmer()

    def add_plot(self, **overrides):
        return self.client.post("/farms/new", data=PLOT | overrides)

    def recommend(self, plot_no=1):
        return self.client.post(f"/farms/{plot_no}/recommend")

    def latest_rec_id(self):
        return self.db_query("SELECT MAX(rec_id) AS id FROM recommendations")[0]["id"]


# ---------------------------------------------------------------------------
# Module 1: Farmer interface (frontend)
# ---------------------------------------------------------------------------
class Module1FarmerInterface(BaseCase):
    def test_tc01_open_application(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Log in", r.data)
        self.assertIn(b"Register", r.data)

    def test_tc02_register_new_farmer(self):
        r = self.register()
        self.assertEqual(r.status_code, 302)
        rows = self.db_query("SELECT * FROM farmers WHERE contact_no = ?", FARMER["contact_no"])
        self.assertEqual(len(rows), 1)
        self.assertIn(b"Account created", self.client.get(r.headers["Location"]).data)

    def test_tc03_register_with_missing_field(self):
        r = self.register(contact_no="")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Contact number is required", r.data)
        self.assertEqual(self.db_query("SELECT COUNT(*) AS n FROM farmers WHERE name = ?", FARMER["name"])[0]["n"], 0)

    def test_tc04_register_existing_contact(self):
        self.register()
        r = self.register(name="Someone Else")
        self.assertIn(b"already registered", r.data)
        self.assertEqual(len(self.db_query("SELECT 1 FROM farmers WHERE contact_no = ?", FARMER["contact_no"])), 1)

    def test_tc05_login_valid(self):
        self.register()
        r = self.login_farmer()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/dashboard"))
        self.assertIn(b"Namaste", self.client.get("/dashboard").data)

    def test_tc06_login_invalid(self):
        self.register()
        r = self.login_farmer(password="wrong-pass")
        self.assertEqual(r.status_code, 401)
        self.assertIn(b"incorrect", r.data)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_tc07_enter_farm_details(self):
        self.farmer_session()
        r = self.add_plot(soil_type="", n="", p="", k="", ph="")
        self.assertEqual(r.status_code, 302)
        page = self.client.get(r.headers["Location"]).data
        self.assertIn(b"Farm details saved", page)
        row = self.db_query("SELECT * FROM farm_details")[0]
        self.assertEqual((row["location"], row["land_area"], row["season"]), ("Jaipur", 2.5, "Rabi"))

    def test_tc08_enter_soil_information_and_upload_report(self):
        self.farmer_session()
        self.add_plot()
        page = self.client.get("/farms/1").data
        self.assertIn(b"Loamy", page)
        report = (io.BytesIO(b"N,P,K,pH\n92,48,44,7.1\n"), "soil.csv")
        self.client.post("/farms/1/edit", data=PLOT | {"n": "", "soil_report": report},
                         content_type="multipart/form-data")
        row = self.db_query("SELECT n, p, k, ph FROM farm_details")[0]
        self.assertEqual(tuple(row), (92.0, 48.0, 44.0, 7.1))

    def test_tc09_out_of_range_soil_values(self):
        self.farmer_session()
        r = self.add_plot(ph="15", n="-4")
        self.assertIn(b"pH must be between 0 and 14", r.data)
        self.assertIn(b"Nitrogen (N) must be between 0 and 300", r.data)
        self.assertEqual(self.db_query("SELECT COUNT(*) AS n FROM farm_details")[0]["n"], 0)

    def test_tc10_non_numeric_soil_input(self):
        self.farmer_session()
        r = self.add_plot(ph="seven")
        self.assertIn(b"pH must be a number", r.data)

    def test_tc11_request_shows_processing_indicator(self):
        self.farmer_session()
        self.add_plot()
        page = self.client.get("/farms/1").data
        self.assertIn(b'data-busy="Generating recommendation', page)
        r = self.recommend()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/recommendations/", r.headers["Location"])

    def test_tc12_view_recommendation(self):
        self.farmer_session()
        self.add_plot()
        r = self.client.get(self.recommend().headers["Location"])
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Recommended crop", r.data)
        self.assertIn(b"confidence", r.data)
        self.assertIn(b"Wheat", r.data)

    def test_tc13_view_history(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        self.recommend()
        page = self.client.get("/recommendations").data
        self.assertEqual(page.count(b">Open</a>"), 2)
        self.assertIn(b"Wheat", page)

    def test_tc14_download_recommendation(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        rec_id = self.latest_rec_id()
        r = self.client.get(f"/recommendations/{rec_id}/download")
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF-1.4"))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        top = self.db_query("SELECT c.crop_name FROM recommendation_crops rc JOIN crops c USING (crop_id)"
                            " WHERE rc.rec_id = ? AND rank_order = 1", rec_id)[0]["crop_name"]
        import zlib
        streams = re.findall(rb"stream\n(.*?)\nendstream", r.data, re.S)
        text = b"".join(zlib.decompress(s) for s in streams)
        self.assertIn(top.encode(), text)


# ---------------------------------------------------------------------------
# Module 2: Backend AI processing and weather retrieval
# ---------------------------------------------------------------------------
class Module2Backend(BaseCase):
    def setUp(self):
        super().setUp()
        self.farmer_session()

    def test_tc15_receive_request(self):
        self.add_plot()
        self.assertEqual(self.recommend().status_code, 302)
        self.assertEqual(self.weather.calls, 1)

    def test_tc16_validate_complete_input(self):
        self.add_plot()
        self.recommend()
        self.assertEqual(len(self.db_query("SELECT * FROM recommendations")), 1)

    def test_tc17_reject_incomplete_input(self):
        self.add_plot(ph="", soil_type="")
        r = self.recommend()
        self.assertIn("/farms/1/edit", r.headers["Location"])
        self.assertIn(b"still needed", self.client.get(r.headers["Location"]).data)
        self.assertEqual(self.weather.calls, 0)
        self.assertEqual(len(self.db_query("SELECT * FROM recommendations")), 0)

    def test_tc18_store_farm_information(self):
        self.add_plot()
        farmer_id = self.db_query("SELECT farmer_id FROM farmers WHERE contact_no = ?", FARMER["contact_no"])[0][0]
        row = self.db_query("SELECT * FROM farm_details")[0]
        self.assertEqual(row["farmer_id"], farmer_id)

    def test_tc19_fetch_weather_data(self):
        self.add_plot()
        self.recommend()
        w = self.db_query("SELECT * FROM weather_data WHERE source = 'open-meteo'")[0]
        self.assertEqual((w["temperature"], w["rainfall"], w["humidity"]), (18.0, 8.0, 55.0))

    def test_tc20_unknown_location(self):
        self.add_plot(location="Qwertyville")
        self.weather.mode = "not_found"
        r = self.recommend()
        self.assertEqual(r.status_code, 302)
        self.assertIn(b"was not found", self.client.get(r.headers["Location"]).data)
        self.assertEqual(len(self.db_query("SELECT * FROM recommendations")), 0)

    def test_tc21_weather_api_unavailable(self):
        self.add_plot()
        self.weather.mode = "down"
        page = self.client.get(self.recommend().headers["Location"]).data
        self.assertIn(b"Weather is estimated", page)
        self.assertEqual(self.db_query("SELECT source FROM weather_data")[0]["source"], "seasonal-estimate")
        self.assertNotIn(b"Open-Meteo archive", page)

    def test_tc22_retrieve_crop_reference_data(self):
        self.add_plot()
        self.recommend()
        model = recommender.model
        self.assertEqual(model.describe()["classes"], self.db_query("SELECT COUNT(*) FROM crops")[0][0])

    def test_tc23_analyze_soil_data(self):
        features = recommender.model.preprocess(
            {"n": 100, "p": 50, "k": 45, "ph": 7.0, "season": "Rabi", "soil_type": "Loamy"},
            {"temperature": 18, "rainfall": 8, "humidity": 55})
        self.assertEqual((features["n"], features["p"], features["k"], features["ph"]), (100, 50, 45, 7.0))

    def test_tc24_combine_inputs(self):
        features = recommender.model.preprocess(
            {"n": 1, "p": 2, "k": 3, "ph": 6, "season": "Rabi", "soil_type": "Loamy"},
            {"temperature": 18, "rainfall": 8, "humidity": 55})
        self.assertEqual(set(features), set(recommender.NUMERIC_FEATURES) | {"season", "soil_type"})
        with self.assertRaises(ValueError):
            recommender.model.preprocess({"n": None, "p": 2, "k": 3, "ph": 6, "season": "Rabi", "soil_type": "Loamy"},
                                         {"temperature": 18, "rainfall": 8, "humidity": 55})

    def test_tc25_generate_recommendation(self):
        self.add_plot()
        self.recommend()
        crops = self.db_query("SELECT * FROM recommendation_crops ORDER BY rank_order")
        self.assertGreaterEqual(len(crops), 1)

    def test_tc26_confidence_between_0_and_1(self):
        for plot in (PLOT, PLOT | {"season": "Kharif", "soil_type": "Clayey"}, PLOT | {"season": "Zaid", "soil_type": "Sandy"}):
            self.add_plot(**plot)
        for n in (1, 2, 3):
            self.recommend(n)
        for row in self.db_query("SELECT suitability_score FROM recommendation_crops"):
            self.assertTrue(0 <= row[0] <= 1)

    def test_tc27_low_confidence_flagged(self):
        self.add_plot(n="290", p="2", k="290", ph="3.5", soil_type="Laterite", season="Rabi")
        page = self.client.get(self.recommend().headers["Location"]).data
        self.assertEqual(self.db_query("SELECT status FROM recommendations")[0]["status"], "low-confidence")
        self.assertIn(b"Low confidence", page)

    def test_tc28_save_recommendation(self):
        self.add_plot()
        self.recommend()
        rec = self.db_query("SELECT * FROM recommendations")[0]
        self.assertIsNotNone(rec["weather_id"])
        ranks = [r["rank_order"] for r in self.db_query("SELECT rank_order FROM recommendation_crops ORDER BY rank_order")]
        self.assertEqual(ranks, [1, 2, 3])


# ---------------------------------------------------------------------------
# Module 3: Admin crop and soil data management
# ---------------------------------------------------------------------------
NEW_CROP = {"crop_name": "Fenugreek (Methi)", "category": "Vegetable", "seasons": ["Rabi"],
            "soil_category": ["Loamy", "Sandy"], "optimal_temp": "17", "min_rainfall": "0", "max_rainfall": "40",
            "temp_tolerance": "5", "humidity_min": "35", "humidity_max": "70", "n_min": "30", "n_max": "70",
            "p_min": "20", "p_max": "50", "k_min": "20", "k_max": "50", "ph_min": "6", "ph_max": "8",
            "water_need": "Low"}


class Module3Admin(BaseCase):
    def test_tc29_admin_dashboard(self):
        self.login_admin()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"System reports", r.data)

    def test_tc30_reject_farmer_admin_access(self):
        self.farmer_session()
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_tc31_view_user_accounts(self):
        self.register()
        self.login_admin()
        self.assertIn(FARMER["name"].encode(), self.client.get("/admin/users").data)

    def test_tc32_update_user_account(self):
        self.register()
        self.login_admin()
        fid = self.db_query("SELECT farmer_id FROM farmers WHERE contact_no = ?", FARMER["contact_no"])[0][0]
        self.client.post(f"/admin/users/{fid}", data={"name": "Sita D.", "contact_no": FARMER["contact_no"],
                                                       "location": "Ajmer", "status": "disabled"})
        page = self.client.get("/admin/users").data
        self.assertIn(b"Sita D.", page)
        self.assertIn(b"disabled", page)
        other = self.app.test_client()
        self.assertIn(b"disabled", self.login_farmer(client=other).data)

    def test_tc33_add_crop(self):
        self.login_admin()
        self.client.post("/admin/crops/new", data=NEW_CROP)
        self.assertIn(b"Fenugreek (Methi)", self.client.get("/admin/crops").data)

    def test_tc34_update_crop(self):
        self.login_admin()
        cid = self.db_query("SELECT crop_id FROM crops WHERE crop_name = 'Wheat'")[0][0]
        crop = dict(self.db_query("SELECT * FROM crops WHERE crop_id = ?", cid)[0])
        data = {k: str(v) for k, v in crop.items() if v is not None}
        data |= {"seasons": crop["seasons"].split(","), "soil_category": crop["soil_category"].split(","),
                 "min_rainfall": "10"}
        self.client.post(f"/admin/crops/{cid}", data=data)
        rows = self.db_query("SELECT min_rainfall FROM crops WHERE crop_name = 'Wheat'")
        self.assertEqual([r[0] for r in rows], [10.0])

    def test_tc35_delete_crop_keeps_history_consistent(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        self.client.post("/logout")
        self.login_admin()
        used = self.db_query("SELECT crop_id FROM recommendation_crops WHERE rank_order = 1")[0][0]
        self.client.post(f"/admin/crops/{used}/delete")
        self.assertEqual(len(self.db_query("SELECT 1 FROM crops WHERE crop_id = ?", used)), 1)
        unused = self.db_query("SELECT crop_id FROM crops WHERE crop_id NOT IN"
                               " (SELECT crop_id FROM recommendation_crops)")[0][0]
        self.client.post(f"/admin/crops/{unused}/delete")
        self.assertEqual(len(self.db_query("SELECT 1 FROM crops WHERE crop_id = ?", unused)), 0)

    def test_tc36_incomplete_crop_record(self):
        self.login_admin()
        r = self.client.post("/admin/crops/new", data=NEW_CROP | {"crop_name": ""})
        self.assertIn(b"Crop name is required", r.data)

    def test_tc37_add_update_soil_reference(self):
        self.login_admin()
        self.client.post("/admin/soils/new", data={"name": "Saline", "typical_n": "30", "typical_p": "20",
                                                   "typical_k": "40", "typical_ph": "8.6", "drainage": "Poor"})
        self.assertEqual(len(self.db_query("SELECT 1 FROM soil_types WHERE name = 'Saline'")), 1)

    def test_tc38_data_persistence(self):
        self.login_admin()
        self.client.post("/admin/crops/new", data=NEW_CROP)
        fresh = create_app("config.TestConfig", DATABASE=self.app.config["DATABASE"])
        with fresh.app_context():
            self.assertIsNotNone(get_db().execute("SELECT 1 FROM crops WHERE crop_name = ?",
                                                  (NEW_CROP["crop_name"],)).fetchone())

    def test_tc39_updated_crop_used_in_recommendation(self):
        self.login_admin()
        self.client.post("/admin/crops/new", data=NEW_CROP | {
            "crop_name": "Test Crop", "soil_category": ["Laterite"], "seasons": ["Zaid"], "optimal_temp": "31",
            "min_rainfall": "10", "max_rainfall": "20", "humidity_min": "35", "humidity_max": "45",
            "n_min": "5", "n_max": "15", "p_min": "5", "p_max": "15", "k_min": "200", "k_max": "220",
            "ph_min": "4.5", "ph_max": "5.0"})
        self.client.post("/logout")
        self.farmer_session()
        self.add_plot(season="Zaid", soil_type="Laterite", n="10", p="10", k="210", ph="4.8")
        page = self.client.get(self.recommend().headers["Location"]).data
        self.assertIn(b'<div class="crop-name">Test Crop</div>', page)

    def test_tc40_view_system_reports(self):
        self.login_admin()
        page = self.client.get("/admin/").data
        for text in (b"Farmers", b"Recommendations", b"Recommendation model", b"Recent activity"):
            self.assertIn(text, page)


# ---------------------------------------------------------------------------
# Module 4: Security, integrity and reliability
# ---------------------------------------------------------------------------
class Module4Security(BaseCase):
    def test_tc41_role_based_access(self):
        self.farmer_session()
        for url in ("/admin/", "/admin/users", "/admin/crops", "/admin/soils"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post("/admin/crops/1/delete").status_code, 403)

    def test_tc42_passwords_hashed(self):
        self.register()
        stored = self.db_query("SELECT password_hash FROM farmers WHERE contact_no = ?", FARMER["contact_no"])[0][0]
        self.assertNotEqual(stored, FARMER["password"])
        self.assertNotIn(FARMER["password"], stored)

    def test_tc43_expired_session(self):
        self.farmer_session()
        with self.client.session_transaction() as s:
            s["last_seen"] = int(time.time()) - 31 * 60
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_tc44_tampered_token(self):
        self.farmer_session()
        cookie = self.client.get_cookie("session")
        self.client.set_cookie("session", cookie.value[:-4] + "AAAA")
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertNotIn(b"Namaste", r.data)

    def test_tc45_isolate_farmer_data(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        rec_id = self.latest_rec_id()
        other = self.app.test_client()
        other.post("/register", data=FARMER | {"contact_no": "9876500002"})
        self.login_farmer(contact="9876500002", client=other)
        self.assertEqual(other.get("/farms/1").status_code, 404)
        self.assertEqual(other.get(f"/recommendations/{rec_id}").status_code, 404)
        self.assertEqual(other.get(f"/recommendations/{rec_id}/download").status_code, 404)

    def test_tc46_sanitize_text_input(self):
        self.farmer_session()
        r = self.add_plot(location="<script>alert(1)</script>")
        self.assertIn(b"may contain only letters", r.data)
        r = self.add_plot(location="Jaipur'; DROP TABLE farmers;--")
        self.assertEqual(len(self.db_query("SELECT name FROM sqlite_master WHERE name = 'farmers'")), 1)
        self.assertNotIn(b"<script>alert(1)</script>", r.data)

    def test_tc47_database_failure(self):
        self.app.config["DATABASE"] = "/proc/no-such-dir/crop.db"
        r = self.client.post("/login", data={"role": "farmer", "identifier": "1", "password": "x"})
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"temporarily unavailable", r.data)

    def test_tc48_model_unavailable(self):
        self.farmer_session()
        self.add_plot()
        saved = recommender.model._classes
        recommender.model._classes = {}
        try:
            # Training also fails, so the model stays unavailable for this request.
            with mock.patch.object(recommender.model, "train", lambda *a, **k: None):
                r = self.recommend()
        finally:
            recommender.model._classes = saved
        self.assertIn(b"unavailable", self.client.get(r.headers["Location"]).data)
        self.assertEqual(len(self.db_query("SELECT * FROM recommendations")), 0)

    def test_tc49_weather_rate_limited(self):
        self.farmer_session()
        self.add_plot()
        self.weather.mode = "rate_limited"
        page = self.client.get(self.recommend().headers["Location"]).data
        self.assertIn(b"limiting requests", page)
        self.assertIn(b"Weather is estimated", page)
        self.assertEqual(self.db_query("SELECT COUNT(*) FROM weather_data WHERE source = 'open-meteo'")[0][0], 0)

    def test_tc50_api_keys_not_exposed(self):
        self.app.config["WEATHER_API_KEY"] = "sk-test-SECRET-123"
        self.farmer_session()
        self.add_plot()
        with self.assertLogs(level="INFO") as logs:
            self.weather.mode = "down"
            r = self.client.get(self.recommend().headers["Location"])
            import logging
            logging.getLogger("probe").info("probe")
        for page in (r.data, self.client.get("/dashboard").data, self.client.get("/farms/1").data):
            self.assertNotIn(b"SECRET", page)
        self.assertFalse(any("SECRET" in line for line in logs.output))

    def test_tc51_duplicate_primary_key(self):
        self.farmer_session()
        self.add_plot()
        with self.app.app_context():
            db = get_db()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO farm_details (farmer_id, plot_no, location, land_area, season)"
                           " SELECT farmer_id, plot_no, location, land_area, season FROM farm_details")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO crops (crop_id, crop_name, optimal_temp, min_rainfall, soil_category)"
                           " VALUES (1, 'Dup', 20, 0, 'Loamy')")

    def test_tc52_cascading_deletion(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        self.client.post("/logout")
        self.login_admin()
        fid = self.db_query("SELECT farmer_id FROM farmers WHERE contact_no = ?", FARMER["contact_no"])[0][0]
        self.client.post(f"/admin/users/{fid}/delete")
        self.assertEqual(self.db_query("SELECT COUNT(*) FROM farm_details WHERE farmer_id = ?", fid)[0][0], 0)
        self.assertEqual(self.db_query("SELECT COUNT(*) FROM recommendations WHERE farmer_id = ?", fid)[0][0], 0)
        self.assertEqual(self.db_query("SELECT COUNT(*) FROM recommendation_crops")[0][0], 0)


class SupportingChecks(BaseCase):
    def test_csrf_token_required(self):
        self.app.config["WTF_CSRF_DISABLED"] = False
        self.register()
        self.assertEqual(self.db_query("SELECT COUNT(*) FROM farmers WHERE contact_no = ?", FARMER["contact_no"])[0][0], 0)

    def test_weather_cached_between_requests(self):
        self.farmer_session()
        self.add_plot()
        self.recommend()
        self.recommend()
        self.assertEqual(self.weather.calls, 1)

    def test_pdf_writer_produces_valid_structure(self):
        doc = PdfDocument("t")
        doc.paragraph("Hello – 25 °C (test)")
        out = doc.output()
        self.assertTrue(out.endswith(b"%%EOF\n"))
        self.assertIn(b"/Type /Catalog", out)


if __name__ == "__main__":
    unittest.main()
