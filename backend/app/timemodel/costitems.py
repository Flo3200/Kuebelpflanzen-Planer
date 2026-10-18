"""Own cost items in tour and order costs (package E).

Tours: every item that belongs to the nursery, the tour's vehicle (or trailer) or one of its team
members is charged by its basis: per km driven, per hour on tour, per trip, per day in use (on the
first trip of the day; nursery items shared by the units of that day), per month pro rata per day
in use (costs.workdays_per_month), per plant transported.

Orders before planning: like the other costs, with an average vehicle and average staff member, the
drive share of the order and the typical number of stops per tour (pricing.typical_tour_stops).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.costs import CostItem


def load_items(db: Session, tenant_id: uuid.UUID) -> list[CostItem]:
    return list(
        db.scalars(
            select(CostItem)
            .where(CostItem.tenant_id == tenant_id, CostItem.deleted_at.is_(None), CostItem.active.is_(True))
            .order_by(CostItem.name)
        )
    )


def scope_of(item: CostItem) -> str:
    if item.vehicle_id:
        return "vehicle"
    if item.staff_id:
        return "staff"
    return "tenant"


def _line(item: CostItem, amount: float) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "basis": item.basis,
        "scope": scope_of(item),
        "amount": round(amount, 2),
    }


def _merge(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for line in lines:
        if line["id"] in by_id:
            by_id[line["id"]]["amount"] = round(by_id[line["id"]]["amount"] + line["amount"], 2)
        else:
            by_id[line["id"]] = dict(line)
    return [x for x in by_id.values() if x["amount"]]


def trip_costs(
    items: list[CostItem],
    *,
    vehicle_ids: set[str],
    staff_ids: list[str],
    km: float,
    minutes: float,
    plants: int,
    first_trip_of_day: bool,
    units_that_day: int,
    workdays_per_month: int,
) -> tuple[float, list[dict[str, Any]]]:
    """Own costs of one trip of a unit; returns (total, lines per item)."""
    lines: list[dict[str, Any]] = []
    hours = max(0.0, minutes) / 60
    for item in items:
        scope = scope_of(item)
        if scope == "vehicle":
            times = 1 if str(item.vehicle_id) in vehicle_ids else 0
        elif scope == "staff":
            times = staff_ids.count(str(item.staff_id))
        else:
            times = 1
        if not times:
            continue
        amt = float(item.amount_eur or 0)
        if item.basis == "per_km":
            value = amt * km
        elif item.basis == "per_hour":
            value = amt * hours
        elif item.basis == "per_use":
            value = amt
        elif item.basis == "per_plant":
            value = amt * plants
        else:  # per_day / per_month: once per unit and day, nursery items shared by that day's units
            day_amount = amt if item.basis == "per_day" else amt / max(1, workdays_per_month)
            if not first_trip_of_day:
                continue
            value = day_amount / max(1, units_that_day) if scope == "tenant" else day_amount
        lines.append(_line(item, value * times))
    lines = _merge(lines)
    return round(sum(x["amount"] for x in lines), 2), lines


def order_costs(
    items: list[CostItem],
    *,
    n_vehicles: int,
    n_staff: int,
    team: int,
    km: float,
    hours: float,
    plants: int,
    stops_per_tour: int,
    workdays_per_month: int,
) -> tuple[float, list[dict[str, Any]]]:
    """Expected own costs of one order before planning (average vehicle and staff member)."""
    lines: list[dict[str, Any]] = []
    stops = max(1, stops_per_tour)
    for item in items:
        scope = scope_of(item)
        # an average vehicle carries a vehicle item with probability 1/n; a team of `team` people
        # contains a given person with probability team/n
        share = (
            1.0
            if scope == "tenant"
            else (1 / max(1, n_vehicles) if scope == "vehicle" else team / max(1, n_staff))
        )
        amt = float(item.amount_eur or 0)
        if item.basis == "per_km":
            value = amt * km
        elif item.basis == "per_hour":
            value = amt * hours
        elif item.basis == "per_use":
            value = amt / stops
        elif item.basis == "per_plant":
            value = amt * plants
        else:
            day_amount = amt if item.basis == "per_day" else amt / max(1, workdays_per_month)
            value = day_amount / stops
        lines.append(_line(item, value * share))
    lines = _merge(lines)
    return round(sum(x["amount"] for x in lines), 2), lines


def allocate_to_stops(total_lines: list[dict[str, Any]], stop_plants: list[int], stop_weights: list[float]):
    """Splits the own costs of a trip over its stops: per-plant items by plants, the rest by weight
    (the stops' share of the trip's direct costs). Returns one amount per stop."""
    n = len(stop_plants)
    if not n:
        return []
    out = [0.0] * n
    plants_total = sum(stop_plants) or 1
    weight_total = sum(stop_weights) or n
    for line in total_lines:
        for i in range(n):
            if line["basis"] == "per_plant":
                out[i] += line["amount"] * stop_plants[i] / plants_total
            else:
                w = stop_weights[i] if sum(stop_weights) else 1
                out[i] += line["amount"] * w / weight_total
    return [round(x, 2) for x in out]
