"""Spontaneous teams: from a sentence (typed or spoken) or the quick form to a team for one day."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentActor
from app.core.errors import AppError
from app.teams.spontaneous import create_day_team, parse

router = APIRouter(prefix="/api/teams/spontaneous", tags=["teams"])


class ParseIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)


@router.post("/parse")
def parse_text(data: ParseIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Preview: day, people and vehicle the AI read from the sentence (nothing is stored)."""
    actor.require("staff.write")
    return parse(db, actor.require_tenant(), data.text)


class CreateIn(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    date: dt.date | None = None
    member_ids: list[str] = Field(default_factory=list)
    vehicle_id: str | None = None
    name: str | None = Field(default=None, max_length=120)


@router.post("", status_code=201)
def create(data: CreateIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """With date and members from the form; with only a text the AI reads them first."""
    actor.require("staff.write")
    tid = actor.require_tenant()
    day, members, vehicle = data.date, data.member_ids, data.vehicle_id
    unknown: list[str] = []
    if data.text and (day is None or not members):
        p = parse(db, tid, data.text)
        day, members = day or p["date"], members or p["member_ids"]
        vehicle = vehicle or p["vehicle_id"]
        unknown = p["unknown"]
    if day is None or not members:
        raise AppError("errors.team_parse_failed", status_code=422)
    team = create_day_team(db, actor, day, members, vehicle, data.name, data.text)
    return {
        "id": team.id,
        "name": team.name,
        "date": day,
        "member_ids": team.member_ids,
        "vehicle_id": team.vehicle_id,
        "unknown": unknown,
    }
