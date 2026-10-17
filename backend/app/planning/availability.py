"""Availability of staff and vehicles per day.

Rules (Availability rows):
  - 'available' rules define working windows (optionally only on given weekdays / date range)
  - absences (unavailable, vacation, sick, maintenance) remove a resource for the covered days;
    with start/end time only that part of the day
  - without any 'available' rule a resource works Mon–Fri within planning.day_start/day_end
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.masterdata import Availability
from app.settings.service import SettingsResolver


@dataclass
class DayWindow:
    available: bool
    start: time | None = None
    end: time | None = None
    reason: str | None = None


def _t(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _covers(rule: Availability, day: date) -> bool:
    if rule.date_from and day < rule.date_from:
        return False
    if rule.date_to and day > rule.date_to:
        return False
    if rule.weekdays and day.weekday() not in rule.weekdays:
        return False
    return True


def day_windows(
    db: Session,
    resolver: SettingsResolver,
    resource_type: str,
    resource_ids: list[uuid.UUID],
    start: date,
    end: date,
) -> dict[uuid.UUID, dict[date, DayWindow]]:
    rules: dict[uuid.UUID, list[Availability]] = defaultdict(list)
    if resource_ids:
        for r in db.scalars(
            select(Availability).where(
                Availability.resource_type == resource_type, Availability.resource_id.in_(resource_ids)
            )
        ):
            rules[r.resource_id].append(r)
    scope = "staff" if resource_type == "staff" else "vehicle"
    out: dict[uuid.UUID, dict[date, DayWindow]] = {}
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    for rid in resource_ids:
        default_start = _t(resolver.get("planning.day_start", (scope, rid)))
        default_end = _t(resolver.get("planning.day_end", (scope, rid)))
        own = rules.get(rid, [])
        positive = [r for r in own if r.kind == "available"]
        absences = [r for r in own if r.kind != "available"]
        per_day: dict[date, DayWindow] = {}
        for day in days:
            if positive:
                matching = [r for r in positive if _covers(r, day)]
                if not matching:
                    per_day[day] = DayWindow(False, reason="no_pattern")
                    continue
                st = min((r.start_time or default_start) for r in matching)
                en = max((r.end_time or default_end) for r in matching)
                window = DayWindow(True, st, en)
            else:
                window = DayWindow(
                    day.weekday() < 5, default_start, default_end, None if day.weekday() < 5 else "weekend"
                )
            for a in absences:
                if not _covers(a, day) or not window.available:
                    continue
                if a.start_time is None and a.end_time is None:
                    window = DayWindow(False, reason=a.kind)
                    break
                # partial absence: shorten the window from the side it touches
                a_start = a.start_time or window.start
                a_end = a.end_time or window.end
                if a_start <= window.start and a_end >= window.end:
                    window = DayWindow(False, reason=a.kind)
                    break
                if a_start <= window.start:
                    window = DayWindow(True, a_end, window.end, a.kind)
                elif a_end >= window.end:
                    window = DayWindow(True, window.start, a_start, a.kind)
                else:  # absence in the middle: keep the longer part
                    first = (a_start.hour * 60 + a_start.minute) - (
                        window.start.hour * 60 + window.start.minute
                    )
                    second = (window.end.hour * 60 + window.end.minute) - (a_end.hour * 60 + a_end.minute)
                    window = (
                        DayWindow(True, window.start, a_start, a.kind)
                        if first >= second
                        else DayWindow(True, a_end, window.end, a.kind)
                    )
            per_day[day] = window
        out[rid] = per_day
    return out
