"""Spontaneous teams (round 2, package M): a sentence like "Morgen fahren Lea und Tom mit dem Sprinter"
(typed, from a message or spoken) becomes a team for that one day.

The AI (``ai.model.team_parse``) reads day, people and vehicle; names are matched against the staff
and vehicle lists. The team is a normal fixed team valid on that single day (``ad_hoc``), so the
planning uses it in both team modes (fixed teams first, see app.planning.inputs).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import service as ai
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError
from app.i18n import t
from app.models.masterdata import StaffMember, Team, Vehicle

WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
WEEKDAY_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _staff(db: Session, tid: uuid.UUID) -> list[StaffMember]:
    return list(
        db.scalars(
            select(StaffMember).where(
                StaffMember.tenant_id == tid, StaffMember.deleted_at.is_(None), StaffMember.active.is_(True)
            )
        )
    )


def _vehicles(db: Session, tid: uuid.UUID) -> list[Vehicle]:
    return list(
        db.scalars(
            select(Vehicle).where(
                Vehicle.tenant_id == tid, Vehicle.deleted_at.is_(None), Vehicle.active.is_(True)
            )
        )
    )


def match_person(name: str, staff: list[StaffMember]) -> StaffMember | None:
    """Full name, then first name, then beginning of a name (case-insensitive)."""
    low = name.strip().lower()
    if not low:
        return None
    for s in staff:
        if s.name.lower() == low:
            return s
    first = [s for s in staff if s.name.lower().split()[0] == low.split()[0]]
    if len(first) == 1:
        return first[0]
    starts = [s for s in staff if s.name.lower().startswith(low)]
    return starts[0] if len(starts) == 1 else None


def match_vehicle(name: str | None, vehicles: list[Vehicle]) -> Vehicle | None:
    if not name:
        return None
    low = name.lower()
    for v in vehicles:
        if v.name.lower() == low or (v.plate and v.plate.lower().replace(" ", "") == low.replace(" ", "")):
            return v
    hits = [v for v in vehicles if low in v.name.lower() or v.name.lower() in low]
    return hits[0] if len(hits) == 1 else None


def parse(db: Session, tid: uuid.UUID, text: str, today: date | None = None) -> dict[str, Any]:
    """Preview of the team in the sentence; nothing is stored."""
    today = today or date.today()
    staff, vehicles = _staff(db, tid), _vehicles(db, tid)
    prompt = (
        f"Heute ist {WEEKDAY_DE[today.weekday()]}, der {today.isoformat()}.\n"
        f"Personal: {', '.join(s.name for s in staff) or 'keins angelegt'}\n"
        f"Fahrzeuge: {', '.join(v.name for v in vehicles) or 'keine angelegt'}\n\n"
        f'Nachricht: """{text}"""'
    )
    context = {
        "text": text,
        "today": today.isoformat(),
        "staff": [s.name for s in staff],
        "vehicles": [v.name for v in vehicles],
    }
    resp, _ = ai.call(db, tid, "team_parse", prompt, context=context)
    data = resp.data or {}
    day = None
    try:
        raw = (data.get("date") or {}).get("value")
        day = date.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        day = None
    members, unknown = [], []
    for name in data.get("members") or []:
        m = match_person(str(name), staff)
        if m is None:
            unknown.append(str(name))
        elif m.id not in [x.id for x in members]:
            members.append(m)
    v = match_vehicle((data.get("vehicle") or {}).get("value"), vehicles)
    return {
        "date": day,
        "member_ids": [str(m.id) for m in members],
        "members": [m.name for m in members],
        "unknown": unknown,
        "vehicle_id": str(v.id) if v else None,
        "vehicle": v.name if v else None,
        "name": data.get("name"),
        "questions": list(data.get("questions") or []),
    }


def create_day_team(
    db: Session,
    actor: Actor,
    day: date,
    member_ids: list[str],
    vehicle_id: str | None = None,
    name: str | None = None,
    source_text: str | None = None,
) -> Team:
    tid = actor.require_tenant()
    staff = {str(s.id): s for s in _staff(db, tid)}
    ids = [m for m in member_ids if m in staff]
    if not ids or len(ids) != len(member_ids):
        raise AppError("errors.team_parse_failed")
    vid = None
    if vehicle_id:
        v = db.get(Vehicle, uuid.UUID(str(vehicle_id)))
        if v is None or v.tenant_id != tid:
            raise AppError("errors.validation")
        vid = v.id
    label = name or f"Tagesteam {day.strftime('%d.%m.')}: " + ", ".join(staff[i].name.split()[0] for i in ids)
    team = Team(
        tenant_id=tid,
        name=label[:120],
        member_ids=ids,
        vehicle_id=vid,
        weekdays=[],
        valid_from=day,
        valid_to=day,
        active=True,
        ad_hoc=True,
        source_text=source_text,
    )
    db.add(team)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="team",
        entity_id=team.id,
        action="create",
        new={
            "name": team.name,
            "date": day.isoformat(),
            "members": ids,
            "vehicle_id": str(vid) if vid else None,
        },
        undoable=True,
    )
    from app.api.planning import mark_needs_replan
    from app.notify.service import notify

    mark_needs_replan(db, tid, f"team:{team.name}", "pickup")
    notify(
        db,
        tid,
        "team_created",
        t("notifications.team_created", name=team.name),
        body=source_text,
        link="/betrieb/teams",
        data={"team_id": str(team.id), "date": day.isoformat()},
        replace_open=False,
    )
    return team


# ---------------------------------------------------------------------------- test model


def _day_from_text(low: str, today: date) -> date | None:
    if "übermorgen" in low:
        return today + timedelta(days=2)
    if "morgen" in low:
        return today + timedelta(days=1)
    if "heute" in low:
        return today
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", low)
    if m:
        try:
            d = date(int(m.group(3) or today.year), int(m.group(2)), int(m.group(1)))
            return d if d >= today - timedelta(days=1) or m.group(3) else d.replace(year=d.year + 1)
        except ValueError:
            return None
    for i, wd in enumerate(WEEKDAYS):
        if re.search(r"\b" + wd, low):
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def fake_team_parse(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rules instead of AI: day words, known first names and vehicle names in the sentence."""
    text = ctx.get("text") or ""
    low = text.lower()
    today = date.fromisoformat(ctx["today"]) if ctx.get("today") else date.today()
    day = _day_from_text(low, today)
    members = []
    for name in ctx.get("staff") or []:
        first = name.split()[0].lower()
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", low) or re.search(
            r"\b" + re.escape(first) + r"\b", low
        ):
            members.append(name)
    vehicle = None
    for name in ctx.get("vehicles") or []:
        words = [w for w in re.findall(r"[\wäöüß]+", name.lower()) if len(w) >= 4]
        if name.lower() in low or any(re.search(r"\b" + re.escape(w), low) for w in words):
            vehicle = name
            break
    questions = []
    if day is None:
        questions.append("An welchem Tag soll das Team fahren?")
    if not members:
        questions.append("Wer gehört zum Team?")
    return {
        "date": {"value": day.isoformat() if day else None, "confidence": 0.8 if day else 0},
        "members": members,
        "vehicle": {"value": vehicle, "confidence": 0.7 if vehicle else 0},
        "name": None,
        "questions": questions,
    }
