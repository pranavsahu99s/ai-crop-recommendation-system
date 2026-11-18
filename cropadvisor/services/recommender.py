"""RecommendationModel: a Naive Bayes classifier trained on crop reference data.

Training set
    For every active crop, synthetic field observations are sampled from its
    agronomic ranges in the CROPS table (N, P, K, pH, temperature, rainfall,
    humidity). Sampling uses a fixed seed, so the same crop data always
    produces the same model. When an administrator edits crop data the model
    is retrained, so recommendations reflect the change (TC-39).

Model
    Gaussian likelihoods for the seven numeric features, and smoothed
    categorical likelihoods for season and soil type. Plain Naive Bayes
    multiplies nine likelihoods and produces near-certain posteriors, so the
    log-posterior is divided by a temperature before the softmax. The result
    is a probability distribution over crops.

    A posterior only compares crops with each other, so it stays high even
    when the inputs fit no crop at all. Each crop's posterior is therefore
    multiplied by a fit factor that falls as the inputs move outside that
    crop's training distribution. The product is the suitability score, and
    the top score is the confidence (always between 0 and 1, TC-26); unusual
    inputs give a low confidence instead of a false strong result (TC-27).
"""
import hashlib
import math
import random
import threading
from datetime import datetime

from ..domain import Crop

NUMERIC_FEATURES = ("n", "p", "k", "ph", "temperature", "rainfall", "humidity")
SAMPLES_PER_CROP = 300
SOFTMAX_TEMPERATURE = 3.0
# Mean squared z-score of a typical in-range sample is about 1; fit decays beyond that.
FIT_FREE_Z2 = 1.5
FIT_DECAY = 3.0
# Probability that a crop grown outside its listed seasons / soils still appears in the data.
OFF_SEASON_RATE = 0.04
OFF_SOIL_RATE = 0.10
MIN_STD = {"n": 6.0, "p": 5.0, "k": 5.0, "ph": 0.25, "temperature": 1.5, "rainfall": 10.0, "humidity": 5.0}


class ModelUnavailable(Exception):
    """No trained model, or nothing to recommend (TC-48)."""


def _feature_ranges(crop: Crop):
    return {
        "n": (crop.n_min, crop.n_max),
        "p": (crop.p_min, crop.p_max),
        "k": (crop.k_min, crop.k_max),
        "ph": (crop.ph_min, crop.ph_max),
        "temperature": (crop.optimal_temp - crop.temp_tolerance, crop.optimal_temp + crop.temp_tolerance),
        "rainfall": (crop.min_rainfall, max(crop.max_rainfall, crop.min_rainfall)),
        "humidity": (crop.humidity_min, crop.humidity_max),
    }


def build_training_set(crops, seasons, soils, rng):
    """Sample labelled observations from each crop's preferred ranges."""
    rows = []
    for crop in crops:
        ranges = _feature_ranges(crop)
        good_seasons = [s for s in crop.season_list if s in seasons] or list(seasons)
        good_soils = [s for s in crop.soil_list if s in soils] or list(soils)
        for _ in range(SAMPLES_PER_CROP):
            row = {f: rng.uniform(*ranges[f]) for f in NUMERIC_FEATURES}
            row["season"] = rng.choice(seasons if rng.random() < OFF_SEASON_RATE else good_seasons)
            row["soil_type"] = rng.choice(soils if rng.random() < OFF_SOIL_RATE else good_soils)
            row["label"] = crop.crop_id
            rows.append(row)
    return rows


class RecommendationModel:
    algorithm_name = "Gaussian Naive Bayes (tempered)"

    def __init__(self):
        self._lock = threading.Lock()
        self.model_version = None
        self.trained_dataset = None
        self.trained_at = None
        self.data_signature = None
        self._classes = {}

    @property
    def is_trained(self):
        return bool(self._classes)

    def train(self, crops, seasons, soils):
        crops = [c for c in crops if c.is_active]
        if not crops:
            with self._lock:
                self._classes = {}
            return
        rows = build_training_set(crops, list(seasons), list(soils), random.Random(522))
        classes = {}
        for crop in crops:
            mine = [r for r in rows if r["label"] == crop.crop_id]
            stats = {}
            for f in NUMERIC_FEATURES:
                values = [r[f] for r in mine]
                mean = sum(values) / len(values)
                var = sum((v - mean) ** 2 for v in values) / len(values)
                stats[f] = (mean, max(math.sqrt(var), MIN_STD[f]))
            stats["season"] = self._categorical(mine, "season", seasons)
            stats["soil_type"] = self._categorical(mine, "soil_type", soils)
            classes[crop.crop_id] = {"crop": crop, "prior": len(mine) / len(rows), "stats": stats}
        with self._lock:
            self._classes = classes
            self.trained_at = datetime.now()
            self.trained_dataset = f"crop reference ranges, {len(rows)} samples, {len(crops)} crops"
            self.model_version = f"gnb-{self.trained_at:%Y%m%d.%H%M%S}"

    @staticmethod
    def _categorical(rows, key, categories):
        counts = {c: 1.0 for c in categories}          # Laplace smoothing
        for r in rows:
            counts[r[key]] = counts.get(r[key], 1.0) + 1
        total = sum(counts.values())
        return {c: v / total for c, v in counts.items()}

    @staticmethod
    def preprocess(farm, weather):
        """Combine farm, soil and weather inputs into one feature vector (TC-24)."""
        features = {
            "n": farm["n"], "p": farm["p"], "k": farm["k"], "ph": farm["ph"],
            "temperature": weather["temperature"], "rainfall": weather["rainfall"],
            "humidity": weather["humidity"], "season": farm["season"], "soil_type": farm["soil_type"],
        }
        missing = [k for k, v in features.items() if v is None]
        if missing:
            raise ValueError(f"Missing model inputs: {', '.join(missing)}")
        return features

    def predict_crops(self, features, top_k=3):
        """Return [(Crop, probability)] for the top_k crops, best first."""
        with self._lock:
            classes = dict(self._classes)
        if not classes:
            raise ModelUnavailable("The recommendation model has not been trained.")
        scores, fit = {}, {}
        for crop_id, cls in classes.items():
            log_p = math.log(cls["prior"])
            z2 = 0.0
            for f in NUMERIC_FEATURES:
                mean, std = cls["stats"][f]
                z = (features[f] - mean) / std
                z2 += z * z
                log_p += -0.5 * z * z - math.log(std)
            fit[crop_id] = math.exp(-max(z2 / len(NUMERIC_FEATURES) - FIT_FREE_Z2, 0) / FIT_DECAY)
            log_p += math.log(cls["stats"]["season"].get(features["season"], 1e-3))
            log_p += math.log(cls["stats"]["soil_type"].get(features["soil_type"], 1e-3))
            scores[crop_id] = log_p / SOFTMAX_TEMPERATURE
        peak = max(scores.values())
        exp = {cid: math.exp(s - peak) for cid, s in scores.items()}
        total = sum(exp.values())
        ranked = sorted(((classes[cid]["crop"], e / total * fit[cid]) for cid, e in exp.items()),
                        key=lambda pair: pair[1], reverse=True)
        return ranked[:top_k]

    @staticmethod
    def calculate_confidence(ranked):
        return round(ranked[0][1], 4) if ranked else 0.0

    def describe(self):
        return {
            "algorithm": self.algorithm_name,
            "version": self.model_version or "not trained",
            "dataset": self.trained_dataset or "—",
            "trained_at": self.trained_at.strftime("%d %b %Y, %H:%M") if self.trained_at else "—",
            "classes": len(self._classes),
        }


model = RecommendationModel()


def retrain(db, force=True):
    """Train the shared model from crop and soil reference data in the database.

    With force=False, training is skipped when the data is unchanged since the
    last training. On the hosted deployment several server instances share one
    database, so each instance calls this before predicting to pick up crop
    edits made through another instance.
    """
    from ..seed import SEASONS
    crop_rows = db.execute("SELECT * FROM crops ORDER BY crop_id").fetchall()
    soils = [r["name"] for r in db.execute("SELECT name FROM soil_types ORDER BY name").fetchall()]
    signature = hashlib.sha256(repr(([tuple(r) for r in crop_rows], soils)).encode()).hexdigest()
    if force or signature != model.data_signature or not model.is_trained:
        model.train([Crop.from_row(r) for r in crop_rows], SEASONS, soils)
        model.data_signature = signature
    return model
