# CropAdvisor — AI-Based Crop Recommendation System for Farmers

**Course:** BCS 522 Software Engineering Lab · **Team:** Pranav Sahu, Ayush Kumar · **Guide:** Dr. Nagresh Kumar
**Institution:** Amity University Rajasthan, Department of CSE

A Flask web application built from the SRS in `SRS new final.pdf` (Labs 1–10). A farmer saves their plots
with location, season and soil values. The system fetches seasonal weather for that place, runs a trained
Naive Bayes model over the crop knowledge base, and returns the top three crops with a confidence score.
Results are saved to history and can be downloaded as a PDF. An administrator manages users, crop data and
soil data, and views system reports.

---

## Run it

```bash
cd farmer_project_SE
python -m venv venv && source venv/bin/activate     # skip if venv/ already exists
pip install -r requirements.txt
python app.py                                       # http://127.0.0.1:5000
```

The database (`instance/cropadvisor.db`) is created and seeded on first start. To reset it:
`flask --app app init-db --reset`.

| Role | Login | Password |
|---|---|---|
| Farmer | `9123456789` (contact number) | `farmer123` |
| Administrator | `admin` (choose the *Administrator* tab) | `admin123` |

Optional environment variables: `CROPADVISOR_SECRET_KEY` (set this for any shared deployment),
`SESSION_MINUTES` (default 30), `CONFIDENCE_THRESHOLD` (default 0.40), `WEATHER_TIMEOUT`.

## Deployment (Vercel + Turso)

Vercel serves the Flask `app` object from `app.py` directly; there is no extra configuration file.

On Vercel, requests are spread across several short-lived server instances, so a local SQLite file can't
be shared between them. The hosted app therefore uses **Turso**, a hosted database with the same SQLite
dialect. Locally nothing changes: without Turso settings the app uses `instance/cropadvisor.db`.

Environment variables for the Vercel project:

| Variable | Purpose |
|---|---|
| `CROPADVISOR_SECRET_KEY` | Signs session cookies; any long random string |
| `TURSO_DATABASE_URL` | e.g. `libsql://cropadvisor-db-<org>.turso.io` |
| `TURSO_AUTH_TOKEN` | Turso database token |

`cropadvisor/turso.py` talks to Turso over its HTTP API using `requests`, so no extra package is needed.
The tables and reference data are created automatically on the first request. Each instance checks
whether the crop data has changed and retrains its copy of the model if so.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v
```

`tests/test_turso_adapter.py` runs the main workflow through the Turso connection against a simulated
Turso server. `tests/test_srs_cases.py` automates all 52 test cases from SRS Lab 10. Each test method starts with its ID
(`test_tc01_…` to `test_tc52_…`), plus 3 supporting checks. The Weather API is stubbed, so the tests run
offline and can simulate an unknown place, an outage and rate limiting.

---

## Project structure

```
farmer_project_SE/
├── app.py                      entry point (local server and Vercel)
├── config.py                   settings (secrets from environment, session lifetime, thresholds)
├── requirements.txt            Flask, requests — nothing else
├── cropadvisor/
│   ├── __init__.py             application factory, template filters, error pages (403/404/413/503)
│   ├── schema.sql              tables from the ER diagram (Lab 9)
│   ├── seed.py                 15 crops, 7 soil types, demo accounts
│   ├── db.py                   connection per request, init/seed, `flask init-db`
│   ├── turso.py                Turso (hosted SQLite) connection for the Vercel deployment
│   ├── domain.py               Farmer, FarmDetails, WeatherData, Crop, CropRecommendation (Lab 8)
│   ├── security.py             role guards, CSRF tokens, session expiry, security headers
│   ├── auth.py                 register / login / logout
│   ├── farmer.py               dashboard, profile, plots, request, history, download
│   ├── admin.py                reports, users, crop data, soil data, retrain
│   ├── services/
│   │   ├── recommender.py      RecommendationModel — Gaussian Naive Bayes
│   │   ├── weather.py          Open-Meteo client (geocoding + historical archive)
│   │   ├── advisory.py         the request workflow from the sequence diagram (Lab 6)
│   │   ├── soil_report.py      reads N, P, K, pH from an uploaded CSV/TXT soil report
│   │   ├── report.py           builds the recommendation PDF
│   │   └── pdf.py              small dependency-free PDF writer
│   ├── templates/              auth/, farmer/, admin/, errors/
│   └── static/                 css/app.css, js/app.js, samples/soil_report_sample.csv
├── tests/                      test_srs_cases.py (TC-01 … TC-52), test_turso_adapter.py
└── previous_version_backup.tar.gz   the earlier version of the project
```

---

## How a recommendation is produced

1. **Validate input:** the plot must have location, season, soil type, N, P, K and pH. If anything is
   missing, the farmer is sent back to the form (the decision node in the activity diagram).
2. **Fetch weather data:** the location is geocoded, then daily data for the most recent complete
   occurrence of the season (Kharif Jun–Oct, Rabi Nov–Mar, Zaid Mar–mid-Jun) is read from the Open-Meteo
   archive. The result is the season's mean temperature, mean humidity and mean monthly rainfall. Readings
   are cached for 12 hours.
   - Unknown place: the request stops and the farmer is told.
   - Service down or rate-limited: typical season values are used. They are stored as
     `seasonal-estimate` and the result is clearly labelled as estimated.
3. **Predict:** the model is trained on 300 samples per crop, drawn from each crop's ranges in the CROPS
   table. It uses Gaussian likelihoods for N, P, K, pH, temperature, rainfall and humidity, and smoothed
   categorical likelihoods for season and soil type. A fit factor lowers the score when the inputs fall
   outside every crop's range, so unusual inputs give low confidence rather than a false strong result.
4. **Save:** a RECOMMENDATIONS row (confidence, status, weather used, input snapshot) and three
   RECOMMENDATION_CROPS rows (rank, suitability). Below the confidence threshold the status is
   `low-confidence` and the page says so.

The model retrains automatically whenever an administrator changes crop or soil data, so new crops are
used right away (TC-39).

## SRS traceability

| SRS lab | Where it is implemented |
|---|---|
| 1 Problem statement | Whole system; landing page |
| 2–3 Use cases | Farmer: register, login, manage profile, enter farm details, upload soil report, view farm details, request / view / download recommendation, view history. Admin: manage users, crop data, soil data, view system reports. Weather API: provide weather data. |
| 4 Activity diagram | `services/advisory.py` + plot page (the "details available?" decision sends the farmer back to the form) |
| 5 State diagram | New user → registered → logged in → entering details → validating → fetching weather → analysing → generated → viewing → downloaded → session ended (logout or 30-minute expiry) |
| 6 Sequence diagram | `farmer.request_recommendation` → `advisory.generate_recommendation` → `WeatherService` → `RecommendationModel` → database |
| 7 DFD | D1 `farmers`/`admins`, D2 `farm_details`, D3 `crops` + `soil_types` + `weather_data`, D4 `recommendations` + `recommendation_crops` |
| 8 Class diagram | `domain.py` (+ `RecommendationModel` in `services/recommender.py`): `validate_inputs`, `get_npk_values`, `is_data_fresh`, `get_weather_metrics`, `check_suitability`, `preprocess`, `predict_crops`, `calculate_confidence` |
| 9 ER diagram | `schema.sql`: FARMERS, FARM_DETAILS (weak entity, composite key, ON DELETE CASCADE), WEATHER_DATA, RECOMMENDATIONS, CROPS, RECOMMENDATION_CROPS (M:N junction). Columns added beyond the SRS are marked `ext`. |
| 10 Test cases | `tests/test_srs_cases.py`, all 52 passing |

### Design decisions worth knowing
- **Crops in saved recommendations cannot be deleted** (`ON DELETE RESTRICT`); they can be deactivated.
  This keeps history consistent (TC-35).
- **Recommendations store an input snapshot**, so editing or removing a plot never changes past results.
- **Farmers log in with their contact number**, which is `UNIQUE` (TC-04). Passwords are hashed with
  Werkzeug's PBKDF2/scrypt (TC-42).
- **Rainfall is mean monthly rainfall over the season** (mm/month), in both the weather data and the
  crop ranges, so the two are directly comparable.
- No third-party UI framework. The interface uses one stylesheet (`static/css/app.css`) and works without
  JavaScript; the JS only adds the processing indicator, confirmation dialogs and "fill typical values".
