"""Hava durumu: konumu IP'den bulur (ya da verilen şehri arar), Open-Meteo'dan güncel durumu getirir."""
from __future__ import annotations

import time

import requests

TIMEOUT = 7
_CACHE: dict[str, tuple[float, tuple[str, float, float]]] = {}   # anahtar -> (zaman, (şehir, enlem, boylam))
CACHE_SECONDS = 6 * 3600

WMO = {0: "açık", 1: "çoğunlukla açık", 2: "parçalı bulutlu", 3: "kapalı", 45: "sisli", 48: "kırağılı sisli",
       51: "hafif çiseleyen", 53: "çiseleyen", 55: "yoğun çiseleyen", 56: "dondurucu çiseleyen",
       57: "dondurucu çiseleyen", 61: "hafif yağmurlu", 63: "yağmurlu", 65: "şiddetli yağmurlu",
       66: "dondurucu yağmurlu", 67: "dondurucu yağmurlu", 71: "hafif karlı", 73: "karlı", 75: "yoğun karlı",
       77: "kar taneli", 80: "hafif sağanaklı", 81: "sağanaklı", 82: "şiddetli sağanaklı", 85: "hafif kar sağanaklı",
       86: "kar sağanaklı", 95: "gök gürültülü fırtınalı", 96: "dolulu fırtınalı", 99: "şiddetli dolulu fırtınalı"}


def _cached(key: str):
    item = _CACHE.get(key)
    if item and time.time() - item[0] < CACHE_SECONDS:
        return item[1]
    return None


def locate_me() -> tuple[str, float, float] | None:
    """Genel IP adresinden yaklaşık şehir ve koordinat (bilgisayarın bulunduğu bölge)."""
    hit = _cached("me")
    if hit:
        return hit
    sources = (
        ("https://ipapi.co/json/", lambda d: (d.get("city"), d.get("latitude"), d.get("longitude"))),
    )
    for url, pick in sources:
        try:
            data = requests.get(url, timeout=TIMEOUT).json()
            city, lat, lon = pick(data)
            if city and lat is not None and lon is not None:
                result = (str(city), float(lat), float(lon))
                _CACHE["me"] = (time.time(), result)
                return result
        except (requests.RequestException, ValueError, KeyError, AttributeError):
            continue
    return None


def geocode(name: str) -> tuple[str, float, float] | None:
    key = "geo:" + name.lower()
    hit = _cached(key)
    if hit:
        return hit
    try:
        data = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                            params={"name": name, "count": 1, "language": "tr"}, timeout=TIMEOUT).json()
        r = (data.get("results") or [None])[0]
        if r:
            result = (r.get("name") or name, float(r["latitude"]), float(r["longitude"]))
            _CACHE[key] = (time.time(), result)
            return result
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def forecast(lat: float, lon: float) -> dict:
    return requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"},
        timeout=TIMEOUT).json()


def report(location: str | None = None) -> str | None:
    """Türkçe hava durumu özeti. Konum bulunamazsa ya da ağ yoksa None döner."""
    place = geocode(location) if location else locate_me()
    if not place:
        return None
    city, lat, lon = place
    try:
        data = forecast(lat, lon)
        cur, day = data["current"], data["daily"]
        desc = WMO.get(int(cur["weather_code"]), "değişken")
        text = (f"{city}: şu an {cur['temperature_2m']:.0f}°C, {desc}. Hissedilen {cur['apparent_temperature']:.0f}°C. "
                f"Bugün {day['temperature_2m_min'][0]:.0f} ile {day['temperature_2m_max'][0]:.0f}°C arasında, "
                f"nem %{cur['relative_humidity_2m']:.0f}, rüzgâr {cur['wind_speed_10m']:.0f} km/sa.")
        rain = day.get("precipitation_probability_max", [None])[0]
        if rain is not None:
            text += f" Yağış ihtimali %{rain:.0f}."
        return text
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
