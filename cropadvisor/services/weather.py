"""Weather API client (Open-Meteo).

For a location and season the service geocodes the place, then reads daily
observations for the most recent complete occurrence of that season from the
Open-Meteo historical archive. It returns the season's mean temperature, mean
relative humidity and mean monthly rainfall, which is what the crop data is
expressed in.

Failures are reported, never hidden (TC-20, TC-21, TC-49):
  * unknown place             -> WeatherError("not_found"), request stops
  * service down / rate limit -> the caller may use a seasonal estimate,
                                 stored with source='seasonal-estimate' and
                                 labelled as such everywhere it is shown.
"""
import logging
from datetime import date, timedelta

import requests

from ..domain import WeatherData

log = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# (start month, start day, end month, end day); Rabi crosses the year boundary.
SEASON_WINDOWS = {"Kharif": (6, 1, 10, 31), "Rabi": (11, 1, 3, 31), "Zaid": (3, 1, 6, 15)}

# Typical season figures for the Indian plains, used only when the API cannot be reached.
SEASONAL_ESTIMATES = {
    "Kharif": {"temperature": 29.0, "humidity": 76.0, "rainfall": 160.0},
    "Rabi": {"temperature": 18.5, "humidity": 58.0, "rainfall": 12.0},
    "Zaid": {"temperature": 31.0, "humidity": 42.0, "rainfall": 20.0},
}


class WeatherError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind          # "not_found" | "unavailable" | "rate_limited"
        self.message = message


def season_window(season, today=None):
    """Most recent complete occurrence of the season, ending at least a week ago."""
    today = today or date.today()
    sm, sd, em, ed = SEASON_WINDOWS[season]
    cutoff = today - timedelta(days=7)
    for year in range(today.year, today.year - 3, -1):
        start = date(year, sm, sd)
        end = date(year + (1 if em < sm else 0), em, ed)
        if end <= cutoff:
            return start, end
    raise ValueError("no complete season window")


class WeatherService:
    def __init__(self, timeout=6.0, api_key="", session=None):
        self.timeout = timeout
        self.api_key = api_key
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = "CropAdvisor/2.0 (BCS 522 lab project)"

    def _get(self, url, params):
        try:
            resp = self.http.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            # Log the exception type only; URLs could carry a key with other providers (TC-50).
            log.warning("Weather API request failed: %s", type(exc).__name__)
            raise WeatherError("unavailable", "The weather service could not be reached.") from None
        if resp.status_code == 429:
            raise WeatherError("rate_limited", "The weather service is limiting requests right now.")
        if resp.status_code >= 400:
            log.warning("Weather API returned HTTP %s", resp.status_code)
            raise WeatherError("unavailable", "The weather service returned an error.")
        try:
            return resp.json()
        except ValueError:
            raise WeatherError("unavailable", "The weather service sent an unreadable response.") from None

    def geocode(self, location):
        data = self._get(GEOCODE_URL, {"name": location, "count": 1, "language": "en", "format": "json"})
        results = data.get("results") or []
        if not results:
            raise WeatherError("not_found", f"“{location}” was not found. Check the spelling or try the district name.")
        r = results[0]
        label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        return r["latitude"], r["longitude"], label

    def fetch_weather_data(self, location, season):
        lat, lon, label = self.geocode(location)
        start, end = season_window(season)
        data = self._get(ARCHIVE_URL, {
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "temperature_2m_mean,relative_humidity_2m_mean,precipitation_sum",
            "timezone": "auto",
        })
        daily = data.get("daily") or {}
        temps = [v for v in daily.get("temperature_2m_mean", []) if v is not None]
        hums = [v for v in daily.get("relative_humidity_2m_mean", []) if v is not None]
        rain = [v for v in daily.get("precipitation_sum", []) if v is not None]
        if not temps or not hums or not rain:
            raise WeatherError("unavailable", "The weather service returned no data for this place.")
        months = max(((end - start).days + 1) / 30.44, 1)
        return WeatherData(
            location=label,
            temperature=round(sum(temps) / len(temps), 1),
            humidity=round(sum(hums) / len(hums), 1),
            rainfall=round(sum(rain) / months, 1),
            source="open-meteo",
            season=season,
            period=f"{start:%d %b %Y} – {end:%d %b %Y}",
            latitude=round(lat, 4),
            longitude=round(lon, 4),
        )

    @staticmethod
    def seasonal_estimate(location, season):
        est = SEASONAL_ESTIMATES[season]
        return WeatherData(location=location, source="seasonal-estimate", season=season,
                           period="Typical season values (not measured)", **est)
