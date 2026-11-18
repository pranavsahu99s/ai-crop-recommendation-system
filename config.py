"""Application configuration.

Secrets and keys are read from the environment so they never appear in
templates, responses or logs (SRS TC-50).
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("CROPADVISOR_SECRET_KEY") or "dev-only-change-me"
    # On Vercel only /tmp is writable, and it is reset when the function instance is recycled.
    DATABASE = os.environ.get("CROPADVISOR_DB") or (
        "/tmp/cropadvisor.db" if os.environ.get("VERCEL") else os.path.join(BASE_DIR, "instance", "cropadvisor.db"))

    # Sessions expire after 30 minutes of inactivity (TC-43).
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_MINUTES", 30)))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Soil report uploads (TC-08).
    MAX_CONTENT_LENGTH = 512 * 1024

    # Weather service (Open-Meteo needs no key; the setting exists for providers that do).
    WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")
    WEATHER_TIMEOUT = float(os.environ.get("WEATHER_TIMEOUT", 6))
    WEATHER_CACHE_HOURS = 12
    WEATHER_ENABLED = True

    # Recommendations below this confidence are flagged, not presented as strong (TC-27).
    CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.40))


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WEATHER_ENABLED = False
