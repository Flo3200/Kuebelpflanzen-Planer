"""Travel distances and times behind the RoutingProvider interface.

Implementations: offline (straight line × detour factor ÷ average speed, no network),
OSRM, OpenRouteService and Google Distance Matrix. Results are cached in route_cache.
Vehicle and driver speed factors are applied by the planner, not here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from sqlalchemy import Float, Index, String, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_config
from app.models.base import Base, IdMixin

Point = tuple[float, float]  # (lat, lon)


class RouteCache(IdMixin, Base):
    """Cached travel distance/time between two rounded coordinates for one provider."""

    __tablename__ = "route_cache"
    __table_args__ = (Index("ux_route_cache_key", "provider", "origin", "destination", unique=True),)

    provider: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(32))
    destination: Mapped[str] = mapped_column(String(32))
    distance_km: Mapped[float] = mapped_column(Float)
    duration_min: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


def haversine_km(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


@dataclass
class Matrix:
    distance_km: list[list[float]]
    duration_min: list[list[float]]


class RoutingProvider(Protocol):
    name: str

    def matrix(self, points: list[Point]) -> Matrix: ...


class OfflineProvider:
    """No network: straight-line distance × detour factor, divided by an average speed."""

    name = "offline"

    def __init__(self, detour_factor: float = 1.35, avg_speed_kmh: float = 45.0) -> None:
        self.detour = detour_factor
        self.speed = avg_speed_kmh

    def matrix(self, points: list[Point]) -> Matrix:
        n = len(points)
        dist = [[0.0] * n for _ in range(n)]
        dur = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    d = haversine_km(points[i], points[j]) * self.detour
                    dist[i][j] = d
                    # short trips are slower (town traffic): blend towards 25 km/h below 5 km
                    speed = self.speed if d > 5 else 25 + (self.speed - 25) * d / 5
                    dur[i][j] = d / max(speed, 1) * 60
        return Matrix(dist, dur)


class OSRMProvider:
    name = "osrm"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def matrix(self, points: list[Point]) -> Matrix:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
        resp = httpx.get(
            f"{self.base_url}/table/v1/driving/{coords}",
            params={"annotations": "distance,duration"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        dist = [[(x or 0) / 1000 for x in row] for row in data["distances"]]
        dur = [[(x or 0) / 60 for x in row] for row in data["durations"]]
        return Matrix(dist, dur)


class ORSProvider:
    name = "ors"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def matrix(self, points: list[Point]) -> Matrix:
        resp = httpx.post(
            "https://api.openrouteservice.org/v2/matrix/driving-car",
            json={
                "locations": [[lon, lat] for lat, lon in points],
                "metrics": ["distance", "duration"],
                "units": "km",
            },
            headers={"Authorization": self.api_key},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return Matrix(
            [[x or 0 for x in row] for row in data["distances"]],
            [[(x or 0) / 60 for x in row] for row in data["durations"]],
        )


class GoogleProvider:
    name = "google"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def matrix(self, points: list[Point]) -> Matrix:
        n = len(points)
        dist = [[0.0] * n for _ in range(n)]
        dur = [[0.0] * n for _ in range(n)]
        step = 10  # Distance Matrix limit: 100 elements per request
        for i0 in range(0, n, step):
            for j0 in range(0, n, step):
                origins = points[i0 : i0 + step]
                dests = points[j0 : j0 + step]
                resp = httpx.get(
                    "https://maps.googleapis.com/maps/api/distancematrix/json",
                    params={
                        "origins": "|".join(f"{a},{b}" for a, b in origins),
                        "destinations": "|".join(f"{a},{b}" for a, b in dests),
                        "key": self.api_key,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                for i, row in enumerate(resp.json()["rows"]):
                    for j, el in enumerate(row["elements"]):
                        if el.get("status") == "OK":
                            dist[i0 + i][j0 + j] = el["distance"]["value"] / 1000
                            dur[i0 + i][j0 + j] = el["duration"]["value"] / 60
        return Matrix(dist, dur)


def make_provider(name: str, detour: float, speed: float) -> RoutingProvider:
    cfg = get_config()
    if name == "osrm":
        return OSRMProvider(cfg.osrm_url)
    if name == "ors" and cfg.ors_api_key:
        return ORSProvider(cfg.ors_api_key)
    if name == "google" and cfg.google_maps_api_key:
        return GoogleProvider(cfg.google_maps_api_key)
    return OfflineProvider(detour, speed)


def _key(p: Point) -> str:
    return f"{p[0]:.5f},{p[1]:.5f}"


def cached_matrix(db: Session | None, provider: RoutingProvider, points: list[Point]) -> Matrix:
    """Matrix with a database cache (skipped for the cheap offline provider)."""
    n = len(points)
    if provider.name == "offline" or db is None or n < 2:
        return provider.matrix(points)
    keys = [_key(p) for p in points]
    pairs = [(keys[i], keys[j]) for i in range(n) for j in range(n) if i != j]
    known: dict[tuple[str, str], tuple[float, float]] = {}
    for chunk_start in range(0, len(pairs), 5000):
        chunk = pairs[chunk_start : chunk_start + 5000]
        rows = db.execute(
            select(
                RouteCache.origin, RouteCache.destination, RouteCache.distance_km, RouteCache.duration_min
            ).where(
                RouteCache.provider == provider.name,
                tuple_(RouteCache.origin, RouteCache.destination).in_(chunk),
            )
        ).all()
        for o, d, dk, dm in rows:
            known[(o, d)] = (dk, dm)
    if len(known) < len(pairs):
        try:
            fresh = provider.matrix(points)
        except (httpx.HTTPError, KeyError, ValueError):
            fresh = OfflineProvider().matrix(points)
            return fresh
        values = []
        for i in range(n):
            for j in range(n):
                if i != j and (keys[i], keys[j]) not in known:
                    known[(keys[i], keys[j])] = (fresh.distance_km[i][j], fresh.duration_min[i][j])
                    values.append(
                        {
                            "provider": provider.name,
                            "origin": keys[i],
                            "destination": keys[j],
                            "distance_km": fresh.distance_km[i][j],
                            "duration_min": fresh.duration_min[i][j],
                        }
                    )
        if values:
            from app.core.db import system_session

            with system_session() as sdb:
                for k in range(0, len(values), 2000):
                    sdb.execute(insert(RouteCache).values(values[k : k + 2000]).on_conflict_do_nothing())
    dist = [[0.0] * n for _ in range(n)]
    dur = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                dist[i][j], dur[i][j] = known[(keys[i], keys[j])]
    return Matrix(dist, dur)


def provider_for(resolver) -> RoutingProvider:
    return make_provider(
        resolver.platform_value("drive.provider"),
        float(resolver.get("drive.detour_factor")),
        float(resolver.get("drive.avg_speed_kmh")),
    )
