"""Voice control (round 2, package L): press the microphone, speak, the AI operates the app.

Speech to text: the transcription model (``ai.model.transcribe``, e.g. OpenAI gpt-4o-transcribe) or,
without one, the browser's speech recognition. The command goes to a tool-using model
(``ai.model.voice_command``, e.g. ChatGPT or Claude) that opens pages, searches, creates drafts and
day teams, lists tours, starts the planning and changes settings - always within the rights of the
signed-in user, every change with an audit entry (and undo where the app offers it).
Data minimisation: the model gets the command and the tool results it asks for, never whole lists.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.ai.providers import AIResponse, ProviderError, get_provider
from app.ai.service import _record, api_key_for, cost_eur, prompt_for, resolve_model, spend_status
from app.api.deps import DB, CurrentActor
from app.core.context import Actor
from app.core.errors import AppError
from app.i18n import t
from app.models.orders import Customer, Draft, PickupOrder
from app.settings.registry import REGISTRY
from app.settings.service import SettingsResolver
from app.settings.texts import setting_text

router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_ROUNDS = 5
# page key -> (route, German words the user may say)
PAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "overview": ("/betrieb", ("übersicht", "start", "dashboard", "startseite")),
    "inbox": ("/betrieb/posteingang", ("posteingang", "nachrichten", "entwürfe", "eingang")),
    "orders": ("/betrieb/auftraege", ("aufträge", "auftrag", "auftragsliste")),
    "tables": ("/betrieb/tabellen", ("tabelle", "tabellen", "übersichtstabelle", "excel")),
    "customers": ("/betrieb/kunden", ("kunden", "kundenliste")),
    "planning": ("/betrieb/planung", ("planung", "tourenplanung", "touren", "tourenplan")),
    "deviations": ("/betrieb/meldungen", ("meldungen", "abweichungen")),
    "teams": ("/betrieb/teams", ("teams", "team")),
    "staff": ("/betrieb/personal", ("personal", "mitarbeiter", "mitarbeiterinnen")),
    "vehicles": ("/betrieb/fahrzeuge", ("fahrzeuge", "fahrzeug", "fuhrpark")),
    "availability": ("/betrieb/verfuegbarkeit", ("verfügbarkeit", "urlaub", "kalender")),
    "costs": ("/betrieb/kosten", ("kosten",)),
    "settings": ("/betrieb/einstellungen", ("einstellungen",)),
    "privacy": ("/betrieb/datenschutz", ("datenschutz",)),
    "formulas": ("/betrieb/formeln", ("formeln", "formel", "formeleditor")),
    "model": ("/betrieb/modell", ("modellqualität", "messungen", "modell")),
    "scenarios": ("/betrieb/szenarien", ("szenarien", "szenario")),
    "assistant": ("/betrieb/assistent", ("assistent", "einstellungs-ki")),
}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "open_page",
        "description": "Öffnet eine Seite der App. page: " + ", ".join(PAGES),
        "input_schema": _obj({"page": {"type": "string", "enum": list(PAGES)}}),
    },
    {
        "name": "search",
        "description": "Sucht Aufträge (Nummer) und Kunden (Name, Ort). Bei genau einem Treffer wird er geöffnet.",
        "input_schema": _obj({"query": {"type": "string"}}),
    },
    {
        "name": "create_draft",
        "description": "Legt eine Kundennachricht (z. B. diktierte Anfrage mit Pflanzen, Adresse) als Entwurf im Posteingang an; die KI wertet sie aus.",
        "input_schema": _obj({"text": {"type": "string"}}),
    },
    {
        "name": "create_day_team",
        "description": "Legt ein Team für einen Tag an, z. B. 'Morgen fahren Lea und Tom mit dem Sprinter'. text: der Satz mit Tag, Personen, Fahrzeug.",
        "input_schema": _obj({"text": {"type": "string"}}),
    },
    {
        "name": "list_tours",
        "description": "Nennt die geplanten Touren eines Tages. day: 'today', 'tomorrow' oder JJJJ-MM-TT.",
        "input_schema": _obj({"day": {"type": "string"}}),
    },
    {
        "name": "start_planning",
        "description": "Startet die Tourenplanung ab einem Datum (JJJJ-MM-TT oder null = morgen) für days Tage (oder null).",
        "input_schema": _obj(
            {"start_date": {"type": ["string", "null"]}, "days": {"type": ["integer", "null"]}}
        ),
    },
    {
        "name": "set_setting",
        "description": "Ändert eine Einstellung des Betriebs (Schlüssel aus der Einstellungsliste).",
        "input_schema": _obj({"key": {"type": "string"}, "value": {"type": ["string", "number", "boolean"]}}),
    },
]


class Runner:
    """Executes the tools; collects the actions for the browser (navigate) and the changes."""

    def __init__(self, db, actor: Actor) -> None:
        self.db = db
        self.actor = actor.with_via("voice")
        self.actions: list[dict[str, Any]] = []
        self.changes: list[dict[str, Any]] = []

    def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        try:
            return getattr(self, f"tool_{name}")(**args), False
        except AppError as exc:
            return t(exc.code, **exc.params), True
        except (TypeError, AttributeError, ValueError, KeyError) as exc:
            return f"Ungültiger Aufruf: {exc}", True

    def tool_open_page(self, page: str) -> str:
        route = PAGES[page][0]
        self.actions.append({"type": "navigate", "to": route})
        return f"Seite {page} geöffnet."

    def tool_search(self, query: str) -> str:
        tid = self.actor.require_tenant()
        q = f"%{query.strip()}%"
        orders = list(
            self.db.scalars(
                select(PickupOrder)
                .join(Customer, Customer.id == PickupOrder.customer_id)
                .where(
                    PickupOrder.tenant_id == tid,
                    PickupOrder.deleted_at.is_(None),
                    or_(PickupOrder.number.ilike(q), Customer.name.ilike(q)),
                )
                .order_by(PickupOrder.created_at.desc())
                .limit(5)
            )
        )
        if len(orders) == 1:
            self.actions.append({"type": "navigate", "to": f"/betrieb/auftraege/{orders[0].id}"})
        if not orders and self.actor.has("customers.read"):
            customers = list(
                self.db.scalars(
                    select(Customer)
                    .where(Customer.tenant_id == tid, Customer.deleted_at.is_(None), Customer.name.ilike(q))
                    .limit(5)
                )
            )
            if len(customers) == 1:
                self.actions.append({"type": "navigate", "to": f"/betrieb/kunden/{customers[0].id}"})
            return "Kunden: " + "; ".join(c.name for c in customers) if customers else "Nichts gefunden."
        if not orders:
            return "Nichts gefunden."
        names = {
            c.id: c.name
            for c in self.db.scalars(select(Customer).where(Customer.id.in_([o.customer_id for o in orders])))
        }
        return "Aufträge: " + "; ".join(
            f"{o.number} {names.get(o.customer_id, '')} ({o.status})" for o in orders
        )

    def tool_create_draft(self, text: str) -> str:
        from app.jobs.queue import enqueue

        self.actor.require("drafts.write")
        tid = self.actor.require_tenant()
        d = Draft(
            tenant_id=tid,
            source_kind="voice",
            source_text=text,
            created_by=self.actor.user_id,
            created_via="voice",
            status="processing",
        )
        self.db.add(d)
        self.db.flush()
        job = enqueue(
            self.db, "ai.process_draft", {"draft_id": str(d.id)}, tenant_id=tid, created_by=self.actor.user_id
        )
        d.job_id = job.id
        self.actions.append({"type": "navigate", "to": f"/betrieb/posteingang/{d.id}"})
        self.changes.append({"kind": "draft", "id": str(d.id)})
        return "Entwurf im Posteingang angelegt; die KI wertet ihn aus."

    def tool_create_day_team(self, text: str) -> str:
        from app.teams.spontaneous import create_day_team, parse

        self.actor.require("staff.write")
        p = parse(self.db, self.actor.require_tenant(), text)
        if p["date"] is None or not p["member_ids"]:
            return "Unklar: " + " ".join(p["questions"] or [t("errors.team_parse_failed")])
        team = create_day_team(self.db, self.actor, p["date"], p["member_ids"], p["vehicle_id"], None, text)
        self.actions.append({"type": "navigate", "to": "/betrieb/teams"})
        self.changes.append({"kind": "team", "id": str(team.id), "name": team.name})
        extra = f" Unbekannt: {', '.join(p['unknown'])}." if p["unknown"] else ""
        return f"Team „{team.name}“ für den {p['date'].strftime('%d.%m.%Y')} angelegt{' mit ' + p['vehicle'] if p['vehicle'] else ''}.{extra}"

    def tool_list_tours(self, day: str) -> str:
        from app.models.masterdata import StaffMember, Vehicle
        from app.models.planning import Plan, Tour, TourStop

        tid = self.actor.require_tenant()
        d = (
            date.today()
            if day in ("today", "heute")
            else date.today() + timedelta(days=1)
            if day in ("tomorrow", "morgen")
            else date.fromisoformat(day)
        )
        tours = list(
            self.db.scalars(
                select(Tour)
                .join(Plan, Plan.id == Tour.plan_id)
                .where(Plan.tenant_id == tid, Plan.is_active.is_(True), Plan.kind == "plan", Tour.date == d)
                .order_by(Tour.start_min)
            )
        )
        if not tours:
            return f"Am {d.strftime('%d.%m.')} sind keine Touren geplant."
        staff = {
            str(s.id): s.name.split()[0]
            for s in self.db.scalars(select(StaffMember).where(StaffMember.tenant_id == tid))
        }
        lines = []
        for tour in tours:
            v = self.db.get(Vehicle, tour.vehicle_id) if tour.vehicle_id else None
            n = self.db.scalar(select(func.count()).select_from(TourStop).where(TourStop.tour_id == tour.id))
            who = ", ".join(staff.get(str(m), "?") for m in tour.member_ids or [])
            lines.append(
                f"{v.name if v else 'Fahrzeug'}: {n} Stopps, {tour.start_min // 60}:{tour.start_min % 60:02d} Uhr, {who}"
            )
        self.actions.append({"type": "navigate", "to": "/betrieb/planung"})
        return f"Touren am {d.strftime('%d.%m.')}: " + "; ".join(lines)

    def tool_start_planning(self, start_date: str | None = None, days: int | None = None) -> str:
        from app.api.planning import PlanIn, create_plan

        self.actor.require("planning.write")
        start = date.fromisoformat(start_date) if start_date else date.today() + timedelta(days=1)
        plan = create_plan(PlanIn(start_date=start, days=days), self.actor, self.db)
        self.actions.append({"type": "navigate", "to": "/betrieb/planung"})
        self.changes.append({"kind": "plan", "id": str(plan["id"])})
        return f"Planung ab {start.strftime('%d.%m.%Y')} gestartet; sie rechnet im Hintergrund."

    def tool_set_setting(self, key: str, value: Any, **_ignored: Any) -> str:
        # the voice control changes settings of the nursery only (scope given by a model is ignored)
        from app.api.assistant import ToolRunner

        self.actor.require("tenant.settings")
        runner = ToolRunner(self.db, self.actor)
        out = runner.tool_set_setting(key, value, "tenant", None)
        self.changes += runner.changes
        return out


def transcription_mode(db, actor: Actor) -> str:
    """'ai' when a real transcription model is set (and allowed), else 'browser'."""
    r = SettingsResolver(db, actor.tenant_id)
    wanted = r.get("voice.transcription")
    if wanted == "browser":
        return "browser"
    try:
        resolved = resolve_model(db, r, "transcribe")
    except AppError:
        return "browser"
    if resolved.provider.kind in ("openai", "openai_compatible") and r.get("ai.model.transcribe"):
        return "ai"
    return "browser"


@router.get("/config")
def config(actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("ai.use")
    r = SettingsResolver(db, actor.tenant_id)
    return {"enabled": bool(r.get("voice.enabled")), "transcription": transcription_mode(db, actor)}


@router.post("/transcribe")
async def transcribe(actor: CurrentActor, db: DB, audio: UploadFile = File(...)) -> dict[str, Any]:
    """Speech to text with the transcription model (the audio is not stored)."""
    actor.require("ai.use")
    raw = await audio.read()
    if len(raw) > 20 * 1024 * 1024:
        raise AppError("errors.file_too_large", status_code=413)
    r = SettingsResolver(db, actor.tenant_id)
    if transcription_mode(db, actor) != "ai":
        raise AppError("errors.transcription_unavailable")
    resolved = resolve_model(db, r, "transcribe")
    provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
    key, key_mode = api_key_for(db, actor.tenant_id, r, resolved.provider)
    started = time.monotonic()
    try:
        text = provider.transcribe(resolved.model.model_name, raw, audio.filename or "sprache.webm", key, {})
    except ProviderError as exc:
        _record(
            actor.tenant_id,
            "transcribe",
            resolved.provider,
            resolved.model,
            key_mode,
            None,
            0,
            False,
            str(exc),
            None,
        )
        raise AppError("errors.ai_failed", detail=str(exc)[:200]) from exc
    _record(
        actor.tenant_id,
        "transcribe",
        resolved.provider,
        resolved.model,
        key_mode,
        AIResponse(text=text, duration_ms=int((time.monotonic() - started) * 1000)),
        0,
        True,
        None,
        None,
    )
    return {"text": text}


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    page: str | None = Field(default=None, max_length=200)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10)


def system_prompt(db, actor: Actor, page: str | None) -> str:
    base = prompt_for(db, actor.tenant_id, "voice_command")["system"]
    keys = "\n".join(
        f"{k} | {setting_text(k)['label']}"
        for k, d in REGISTRY.items()
        if "tenant" in d.levels and not d.admin_only and not k.startswith(("billing.", "ai.model."))
    )
    today = date.today()
    return (
        f"{base}\n\nHeute ist der {today.isoformat()}. Benutzer: {actor.label} (Rolle {actor.role}). "
        f"Aktuelle Seite: {page or 'unbekannt'}.\n\nSeiten: {', '.join(PAGES)}\n\n"
        f"# Einstellungen (Schlüssel | Name)\n{keys}"
    )


@router.post("/command")
def command(data: CommandIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """One spoken command: the model calls tools; the answer is read out, actions run in the browser."""
    actor.require("ai.use")
    tid = actor.require_tenant()
    r = SettingsResolver(db, tid)
    if not r.get("voice.enabled"):
        raise AppError("errors.module_off", status_code=409, module="voice")
    status = spend_status(db, tid, r)
    if status["blocked"] and r.get("ai.key_mode") != "byok":
        raise AppError("errors.ai_limit", status_code=402)
    resolved = resolve_model(db, r, "voice_command")
    provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
    key, key_mode = api_key_for(db, tid, r, resolved.provider)
    runner = Runner(db, actor)
    messages: list[dict[str, Any]] = [
        {"role": h["role"], "content": h["content"]}
        for h in data.history
        if h.get("role") in ("user", "assistant") and h.get("content")
    ]
    messages.append({"role": "user", "content": data.text})
    options = {
        "mode": "voice",
        "effort": resolved.model.effort or "low",
        "pages": {k: list(v[1]) for k, v in PAGES.items()},
        "settings_index": [{"key": k, "label": setting_text(k)["label"]} for k in REGISTRY],
        "default_scope": "tenant",
    }
    system = system_prompt(db, actor, data.page)
    text = ""
    for _round in range(MAX_ROUNDS):
        started = time.monotonic()
        try:
            turn = provider.chat(resolved.model.model_name, system, messages, TOOLS, key, options)
        except ProviderError as exc:
            _record(
                tid,
                "voice_command",
                resolved.provider,
                resolved.model,
                key_mode,
                None,
                0,
                False,
                str(exc),
                None,
            )
            raise AppError("errors.ai_failed", detail=str(exc)[:200]) from exc
        _record(
            tid,
            "voice_command",
            resolved.provider,
            resolved.model,
            key_mode,
            AIResponse(
                text=turn.text,
                input_tokens=turn.input_tokens,
                output_tokens=turn.output_tokens,
                duration_ms=int((time.monotonic() - started) * 1000),
            ),
            cost_eur(resolved.model, r, turn.input_tokens, turn.output_tokens),
            True,
            None,
            None,
        )
        text = turn.text or text
        if not turn.tool_calls:
            break
        messages.append(
            {
                "role": "assistant",
                "content": turn.raw_content
                or [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]}
                    for c in turn.tool_calls
                ],
            }
        )
        results = []
        for c in turn.tool_calls:
            out, is_error = runner.run(c["name"], dict(c.get("input") or {}))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": c["id"],
                    "content": out,
                    **({"is_error": True} if is_error else {}),
                }
            )
        messages.append({"role": "user", "content": results})
    return {
        "heard": data.text,
        "text": text or t("errors.voice_not_understood"),
        "actions": runner.actions,
        "changes": runner.changes,
        "model": resolved.model.label,
    }
