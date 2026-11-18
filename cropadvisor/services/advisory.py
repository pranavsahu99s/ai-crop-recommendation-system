"""The recommendation workflow from the SRS sequence diagram (Lab 6).

validate input -> fetch weather data -> retrieve crop data -> preprocess ->
predict -> save recommendation. Each step reports failure instead of
continuing with made-up data.
"""
import json

from flask import current_app

from ..domain import Crop, CropRecommendation, FarmDetails, WeatherData
from .recommender import ModelUnavailable, model
from .weather import WeatherError, WeatherService


class IncompleteInput(ValueError):
    def __init__(self, missing):
        super().__init__("Missing: " + ", ".join(missing))
        self.missing = missing


def _weather_from_row(row):
    return WeatherData(**{k: row[k] for k in row.keys() if k in WeatherData.__dataclass_fields__})


def get_weather(db, location, season):
    """Return (WeatherData, notice). Uses a fresh cached reading when one exists."""
    cfg = current_app.config
    cached = db.execute(
        "SELECT * FROM weather_data WHERE lower(location) = lower(?) AND season = ? AND source = 'open-meteo'"
        " ORDER BY recorded_date DESC LIMIT 1", (location, season)).fetchone()
    if cached:
        w = _weather_from_row(cached)
        if w.is_data_fresh(cfg["WEATHER_CACHE_HOURS"]):
            return w, None

    service = current_app.extensions.get("weather_service") or WeatherService(cfg["WEATHER_TIMEOUT"])
    notice = None
    try:
        if not cfg.get("WEATHER_ENABLED", True):
            raise WeatherError("unavailable", "Live weather is turned off in this configuration.")
        weather = service.fetch_weather_data(location, season)
    except WeatherError as err:
        if err.kind == "not_found":
            raise
        weather = WeatherService.seasonal_estimate(location, season)
        notice = (f"{err.message} Typical {season} values were used instead and the result is marked "
                  "as an estimate.")

    cur = db.execute(
        "INSERT INTO weather_data (location, temperature, rainfall, humidity, season, source, period,"
        " latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (location if weather.source != "open-meteo" else weather.location, weather.temperature,
         weather.rainfall, weather.humidity, season, weather.source, weather.period,
         weather.latitude, weather.longitude))
    weather.weather_id = cur.lastrowid
    # Cache under the farmer's own spelling as well, so the lookup above finds it.
    if weather.source == "open-meteo" and weather.location.lower() != location.lower():
        db.execute(
            "INSERT INTO weather_data (location, temperature, rainfall, humidity, season, source, period,"
            " latitude, longitude) VALUES (?, ?, ?, ?, ?, 'open-meteo', ?, ?, ?)",
            (location, weather.temperature, weather.rainfall, weather.humidity, season,
             weather.period, weather.latitude, weather.longitude))
    return weather, notice


def generate_recommendation(db, farmer_id, plot: FarmDetails):
    """Run the full request. Returns (rec_id, notice). Raises IncompleteInput,
    WeatherError(not_found) or ModelUnavailable without saving anything."""
    missing = plot.missing_for_recommendation()
    if missing:
        raise IncompleteInput(missing)
    if not model.is_trained:
        raise ModelUnavailable("The recommendation model is not available.")

    weather, notice = get_weather(db, plot.location, plot.season)
    farm = {"n": plot.n, "p": plot.p, "k": plot.k, "ph": plot.ph,
            "season": plot.season, "soil_type": plot.soil_type}
    features = model.preprocess(farm, {"temperature": weather.temperature, "rainfall": weather.rainfall,
                                       "humidity": weather.humidity})
    ranked = model.predict_crops(features, top_k=3)
    confidence = model.calculate_confidence(ranked)
    status = "confident" if confidence >= current_app.config["CONFIDENCE_THRESHOLD"] else "low-confidence"

    snapshot = {
        "plot_name": plot.plot_name, "location": plot.location, "land_area": plot.land_area,
        **farm, "weather_source": weather.source,
    }
    cur = db.execute(
        "INSERT INTO recommendations (confidence_score, status, farmer_id, weather_id, plot_no,"
        " model_version, input_snapshot) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (confidence, status, farmer_id, weather.weather_id, plot.plot_no, model.model_version,
         json.dumps(snapshot)))
    rec_id = cur.lastrowid
    db.executemany(
        "INSERT INTO recommendation_crops (rec_id, crop_id, rank_order, suitability_score) VALUES (?, ?, ?, ?)",
        [(rec_id, crop.crop_id, rank, round(prob, 4)) for rank, (crop, prob) in enumerate(ranked, start=1)])
    return rec_id, notice


def load_recommendation(db, rec_id):
    """Load a stored recommendation with its crops, inputs and weather."""
    row = db.execute("SELECT * FROM recommendations WHERE rec_id = ?", (rec_id,)).fetchone()
    if row is None:
        return None
    crop_rows = db.execute(
        "SELECT rc.rank_order, rc.suitability_score, c.* FROM recommendation_crops rc"
        " JOIN crops c ON c.crop_id = rc.crop_id WHERE rc.rec_id = ? ORDER BY rc.rank_order", (rec_id,)).fetchall()
    rec = CropRecommendation(
        rec_id=row["rec_id"], generated_date=row["generated_date"], confidence_score=row["confidence_score"],
        status=row["status"], farmer_id=row["farmer_id"],
        crops=[{"crop": Crop.from_row(r), "rank_order": r["rank_order"],
                "suitability_score": r["suitability_score"]} for r in crop_rows])
    weather = _weather_from_row(db.execute(
        "SELECT * FROM weather_data WHERE weather_id = ?", (row["weather_id"],)).fetchone())
    inputs = json.loads(row["input_snapshot"])
    farmer = db.execute("SELECT name, contact_no FROM farmers WHERE farmer_id = ?", (row["farmer_id"],)).fetchone()
    return {"rec": rec, "weather": weather, "inputs": inputs, "farmer": farmer,
            "plot_no": row["plot_no"], "model_version": row["model_version"]}
