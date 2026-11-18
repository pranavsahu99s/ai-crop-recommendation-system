"""Domain classes from the SRS class diagram (Lab 8).

Farmer, FarmDetails, WeatherData, Crop and CropRecommendation are plain data
classes built from database rows. RecommendationModel lives in
services/recommender.py because it holds trained state.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .seed import SEASONS

# Letters (any script), digits, spaces and . , ' ( ) - only. Rejects markup and SQL punctuation (TC-46).
_PLACE_RE = re.compile(r"^[^\W_][\w .,'()\-]{1,79}$", re.UNICODE)
_CONTACT_RE = re.compile(r"^[6-9]\d{9}$")

SOIL_LIMITS = {"n": (0, 300), "p": (0, 300), "k": (0, 300), "ph": (0, 14)}
SOIL_LABELS = {"n": "Nitrogen (N)", "p": "Phosphorus (P)", "k": "Potassium (K)", "ph": "pH"}


def clean_place(value, label="Location"):
    value = " ".join((value or "").split())
    if not value:
        return None, f"{label} is required."
    if not _PLACE_RE.match(value):
        return None, f"{label} may contain only letters, numbers, spaces and basic punctuation."
    return value, None


def parse_number(raw, label, low=None, high=None, required=True):
    """Return (value, error). Rejects text such as "seven" (TC-10) and out-of-range values (TC-09)."""
    raw = (raw or "").strip()
    if raw == "":
        return None, (f"{label} is required." if required else None)
    try:
        value = float(raw)
    except ValueError:
        return None, f"{label} must be a number."
    if value != value or value in (float("inf"), float("-inf")):
        return None, f"{label} must be a number."
    if low is not None and high is not None and not (low <= value <= high):
        return None, f"{label} must be between {low:g} and {high:g}."
    return value, None


@dataclass
class Farmer:
    farmer_id: int
    name: str
    location: str
    contact_no: str
    status: str = "active"

    @staticmethod
    def validate_registration(form):
        errors, data = {}, {}
        data["name"] = " ".join((form.get("name") or "").split())
        if not data["name"]:
            errors["name"] = "Name is required."
        elif not _PLACE_RE.match(data["name"]):
            errors["name"] = "Name may contain only letters, spaces and basic punctuation."
        data["location"], err = clean_place(form.get("location"), "Village / district")
        if err:
            errors["location"] = err
        data["contact_no"] = re.sub(r"[\s-]", "", form.get("contact_no") or "")
        if not data["contact_no"]:
            errors["contact_no"] = "Contact number is required."
        elif not _CONTACT_RE.match(data["contact_no"]):
            errors["contact_no"] = "Enter a 10-digit mobile number."
        password = form.get("password") or ""
        if len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
        elif password != (form.get("confirm") or ""):
            errors["confirm"] = "Passwords do not match."
        data["password"] = password
        return data, errors


@dataclass
class FarmDetails:
    farmer_id: int
    plot_no: int
    location: str
    land_area: float
    season: str
    soil_type: str | None = None
    n: float | None = None
    p: float | None = None
    k: float | None = None
    ph: float | None = None
    plot_name: str | None = None

    @classmethod
    def from_row(cls, row):
        keys = row.keys()
        return cls(**{f: row[f] for f in cls.__dataclass_fields__ if f in keys})

    @staticmethod
    def validate_inputs(form, soil_names):
        """Validate the farm-details form. Soil values are optional when saving."""
        errors, data = {}, {}
        data["plot_name"] = " ".join((form.get("plot_name") or "").split())[:60] or None
        if data["plot_name"] and not _PLACE_RE.match(data["plot_name"]):
            errors["plot_name"] = "Plot name may contain only letters, numbers and basic punctuation."
        data["location"], err = clean_place(form.get("location"))
        if err:
            errors["location"] = err
        data["land_area"], err = parse_number(form.get("land_area"), "Land area", 0.01, 10000)
        if err:
            errors["land_area"] = err
        data["season"] = form.get("season")
        if data["season"] not in SEASONS:
            errors["season"] = "Choose a cultivation season."
        soil = form.get("soil_type") or None
        if soil and soil not in soil_names:
            errors["soil_type"] = "Choose a soil type from the list."
        data["soil_type"] = soil
        for key, (low, high) in SOIL_LIMITS.items():
            data[key], err = parse_number(form.get(key), SOIL_LABELS[key], low, high, required=False)
            if err:
                errors[key] = err
        return data, errors

    def missing_for_recommendation(self):
        """Fields the model needs that are not yet filled in (activity diagram decision node)."""
        missing = [label for key, label in (("location", "location"), ("season", "season"),
                                            ("soil_type", "soil type")) if not getattr(self, key)]
        missing += [SOIL_LABELS[k] for k in ("n", "p", "k", "ph") if getattr(self, k) is None]
        return missing

    def get_npk_values(self):
        return f"{self.n:g} : {self.p:g} : {self.k:g}" if None not in (self.n, self.p, self.k) else "—"


@dataclass
class WeatherData:
    location: str
    temperature: float
    rainfall: float
    humidity: float
    source: str
    season: str | None = None
    period: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    recorded_date: str | None = None
    weather_id: int | None = None

    @property
    def is_live(self):
        return self.source == "open-meteo"

    def is_data_fresh(self, max_age_hours):
        if not self.recorded_date:
            return False
        recorded = datetime.fromisoformat(self.recorded_date)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return now - recorded < timedelta(hours=max_age_hours)

    def get_weather_metrics(self):
        return f"{self.temperature:.1f} °C, {self.rainfall:.0f} mm/month, {self.humidity:.0f}% RH"


@dataclass
class Crop:
    crop_id: int
    crop_name: str
    optimal_temp: float
    min_rainfall: float
    soil_category: str
    category: str = "Other"
    seasons: str = ""
    temp_tolerance: float = 6
    max_rainfall: float = 250
    humidity_min: float = 30
    humidity_max: float = 85
    n_min: float = 0
    n_max: float = 0
    p_min: float = 0
    p_max: float = 0
    k_min: float = 0
    k_max: float = 0
    ph_min: float = 0
    ph_max: float = 0
    water_need: str = "Medium"
    duration_days: int | None = None
    guidance: str | None = None
    is_active: int = 1

    @classmethod
    def from_row(cls, row):
        keys = row.keys()
        return cls(**{f: row[f] for f in cls.__dataclass_fields__ if f in keys})

    @property
    def soil_list(self):
        return [s.strip() for s in self.soil_category.split(",") if s.strip()]

    @property
    def season_list(self):
        return [s.strip() for s in self.seasons.split(",") if s.strip()]

    def check_suitability(self, farm, weather):
        """Per-factor comparison of the inputs against this crop's preferred ranges.

        Returns a list of (factor, value, preferred, ok) used to explain a result.
        """
        def within(v, lo, hi):
            return lo <= v <= hi

        t_lo, t_hi = self.optimal_temp - self.temp_tolerance, self.optimal_temp + self.temp_tolerance
        return [
            ("Season", farm["season"], ", ".join(self.season_list), farm["season"] in self.season_list),
            ("Soil type", farm["soil_type"], ", ".join(self.soil_list), farm["soil_type"] in self.soil_list),
            ("Temperature", f"{weather['temperature']:.1f} °C", f"{t_lo:g}–{t_hi:g} °C",
             within(weather["temperature"], t_lo, t_hi)),
            ("Rainfall", f"{weather['rainfall']:.0f} mm/month", f"{self.min_rainfall:g}–{self.max_rainfall:g}",
             within(weather["rainfall"], self.min_rainfall, self.max_rainfall)),
            ("Humidity", f"{weather['humidity']:.0f}%", f"{self.humidity_min:g}–{self.humidity_max:g}%",
             within(weather["humidity"], self.humidity_min, self.humidity_max)),
            ("Nitrogen", f"{farm['n']:g}", f"{self.n_min:g}–{self.n_max:g}", within(farm["n"], self.n_min, self.n_max)),
            ("Phosphorus", f"{farm['p']:g}", f"{self.p_min:g}–{self.p_max:g}", within(farm["p"], self.p_min, self.p_max)),
            ("Potassium", f"{farm['k']:g}", f"{self.k_min:g}–{self.k_max:g}", within(farm["k"], self.k_min, self.k_max)),
            ("pH", f"{farm['ph']:g}", f"{self.ph_min:g}–{self.ph_max:g}", within(farm["ph"], self.ph_min, self.ph_max)),
        ]


@dataclass
class CropRecommendation:
    rec_id: int
    generated_date: str
    confidence_score: float
    status: str
    farmer_id: int
    crops: list = field(default_factory=list)   # [{crop: Crop, rank_order, suitability_score}]

    @property
    def top(self):
        return self.crops[0] if self.crops else None

    @property
    def is_low_confidence(self):
        return self.status == "low-confidence"
