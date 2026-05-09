from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen
import json

from .config import WeatherConfig


@dataclass(frozen=True)
class WeatherReport:
    location: str
    temperature_c: float | None
    apparent_temperature_c: float | None
    precipitation_mm: float | None
    wind_speed_kmh: float | None
    weather_code: int | None
    local_time: str | None = field(default=None)
    time_of_day: str | None = field(default=None)

    def to_dict(self) -> dict[str, float | int | str | None]:
        return asdict(self)


def time_of_day_from_hour(hour: int) -> str:
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 21:
        return "evening"
    return "late_night"


def fetch_weather(config: WeatherConfig) -> WeatherReport:
    params = urlencode(
        {
            "latitude": config.latitude,
            "longitude": config.longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation",
                    "wind_speed_10m",
                    "weather_code",
                ]
            ),
            "timezone": "auto",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"

    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    current = payload.get("current", {})
    local_time = current.get("time")
    time_of_day = None
    if isinstance(local_time, str):
        try:
            time_of_day = time_of_day_from_hour(datetime.fromisoformat(local_time).hour)
        except ValueError:
            time_of_day = None

    return WeatherReport(
        location=config.name,
        temperature_c=current.get("temperature_2m"),
        apparent_temperature_c=current.get("apparent_temperature"),
        precipitation_mm=current.get("precipitation"),
        wind_speed_kmh=current.get("wind_speed_10m"),
        weather_code=current.get("weather_code"),
        local_time=local_time if isinstance(local_time, str) else None,
        time_of_day=time_of_day,
    )
