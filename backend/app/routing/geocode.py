"""Geocoding behind a small interface. 'offline' never calls the network (coordinates are entered
or picked on the map); 'nominatim' uses OpenStreetMap Nominatim (respect its usage policy:
at most one request per second, identifying User-Agent)."""

from __future__ import annotations

import threading
import time
from functools import lru_cache

import httpx

from app.core.config import get_config

_lock = threading.Lock()
_last_call = 0.0


@lru_cache(maxsize=2048)
def geocode(query: str) -> tuple[float, float, str] | None:
    cfg = get_config()
    if cfg.geocoder != "nominatim":
        return None
    global _last_call
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    try:
        resp = httpx.get(
            f"{cfg.nominatim_url}/search",
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": f"Kuebelpflanzen-Planer ({cfg.base_url})"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), "nominatim"
