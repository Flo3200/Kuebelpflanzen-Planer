"""Settings AI: a chat that knows the app (docs/APP_GUIDE.md) and every setting with its current value
and origin, explains them and changes them through tools - within the rights of the signed-in user.
Every change is written with the source "settings_ai" and can be undone with one click."""

from __future__ import annotations

import json
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ai.providers import ProviderError, get_provider
from app.ai.service import _record, api_key_for, cost_eur, prompt_for, resolve_model, spend_status
from app.api.deps import DB, CurrentActor
from app.core.context import Actor
from app.core.errors import AppError
from app.i18n import t
from app.settings.registry import REGISTRY
from app.settings.service import SettingsResolver, coerce, describe, reset, set_value
from app.settings.texts import setting_text

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

MAX_ROUNDS = 6
GUIDE_PATHS = (Path(__file__).resolve().parents[3] / "docs" / "APP_GUIDE.md", Path("/app/docs/APP_GUIDE.md"))


@lru_cache
def app_guide() -> str:
    for p in GUIDE_PATHS:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def guide_sections(query: str, limit: int = 3) -> list[str]:
    """Sections of the app guide that mention the words of the query most often."""
    text = app_guide()
    parts = [s for s in ("\n" + text).split("\n## ") if s.strip()]
    words = [w for w in query.lower().split() if len(w) > 3]
    scored = sorted(parts, key=lambda s: -sum(s.lower().count(w[:6]) for w in words))
    return ["## " + s.strip()[:3000] for s in scored[:limit] if any(w[:6] in s.lower() for w in words)]


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_settings",
        "description": "Listet Einstellungen mit aktuellem Wert und Herkunft. Optional nach Gruppe oder Suchwort filtern.",
        "input_schema": {
            "type": "object",
            "properties": {"group": {"type": ["string", "null"]}, "query": {"type": ["string", "null"]}},
            "required": ["group", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_setting",
        "description": "Eine Einstellung mit Wert, Herkunft (Standard, Admin, Betrieb, Objekt), Grenzen und Erklärung.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_setting",
        "description": "Ändert eine Einstellung. scope: 'tenant' (Betrieb) oder 'platform' (nur Admin). Werte vom Typ json als JSON-Text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": ["string", "number", "boolean"]},
                "scope": {"type": "string", "enum": ["tenant", "platform"]},
                "object_id": {"type": ["string", "null"]},
            },
            "required": ["key", "value", "scope", "object_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reset_setting",
        "description": "Setzt eine Einstellung auf der Ebene zurück, so dass der Wert der Ebene darüber gilt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "scope": {"type": "string", "enum": ["tenant", "platform"]},
                "object_id": {"type": ["string", "null"]},
            },
            "required": ["key", "scope", "object_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "explain_setting",
        "description": "Erklärt eine Einstellung in einfachen Worten (Bedeutung, Einheit, Grenzen, aktueller Wert).",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_guide",
        "description": "Sucht in der Funktionsbeschreibung der App nach einem Thema.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def _scope_of(actor: Actor) -> str:
    return "tenant" if actor.tenant_id is not None else "platform"


def _settings_table(resolver: SettingsResolver, actor: Actor) -> list[dict[str, Any]]:
    rows = describe(resolver, _scope_of(actor))
    return [r for r in rows if not (r["admin_only"] and actor.tenant_id is not None)]


def _fmt(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)


ORIGIN = {"default": "Standard", "platform": "Admin", "tenant": "Betrieb"}


class ToolRunner:
    def __init__(self, db, actor: Actor) -> None:
        self.db = db
        self.actor = actor.with_via("settings_ai")
        self.changes: list[dict[str, Any]] = []

    def resolver(self) -> SettingsResolver:
        return SettingsResolver(self.db, self.actor.tenant_id)

    def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        try:
            return getattr(self, f"tool_{name}")(**args), False
        except AppError as exc:
            return t(exc.code, **exc.params), True
        except (TypeError, AttributeError, ValueError) as exc:
            return f"Ungültiger Aufruf: {exc}", True

    def _key(self, key: str) -> str:
        if key not in REGISTRY:
            raise AppError("errors.setting_unknown", key=key)
        return key

    def tool_list_settings(self, group: str | None = None, query: str | None = None) -> str:
        rows = _settings_table(self.resolver(), self.actor)
        if group:
            rows = [r for r in rows if r["group"] == group]
        if query:
            q = query.lower()
            rows = [r for r in rows if q in (r["key"] + " " + r["label"] + " " + (r["help"] or "")).lower()]
        return (
            "\n".join(
                f"{r['key']} | {r['label']} | {_fmt(r['value'])} {r['unit'] or ''} | {ORIGIN.get(r['origin'], r['origin'])}"
                for r in rows[:80]
            )
            or "Keine passende Einstellung."
        )

    def tool_get_setting(self, key: str) -> str:
        key = self._key(key)
        rows = [r for r in _settings_table(self.resolver(), self.actor) if r["key"] == key]
        if not rows:
            raise AppError("errors.setting_admin_only", key=key)
        r = rows[0]
        return json.dumps(
            {
                k: r.get(k)
                for k in (
                    "key",
                    "label",
                    "help",
                    "value",
                    "origin",
                    "unit",
                    "min",
                    "max",
                    "choices",
                    "type",
                    "inherited_value",
                )
            },
            ensure_ascii=False,
            default=str,
        )

    def tool_explain_setting(self, key: str) -> str:
        key = self._key(key)
        d = REGISTRY[key]
        texts = setting_text(key)
        res = self.resolver().resolve(key)
        bounds = (
            f" Erlaubt: {d.min}–{d.max} {d.unit or ''}." if d.min is not None or d.max is not None else ""
        )
        return (
            f"{texts['label']} ({key}): {texts['help'] or ''}{bounds} Aktueller Wert: {_fmt(res.value)} {d.unit or ''}"
            f" (Herkunft: {ORIGIN.get(res.origin, res.origin)})."
        )

    def tool_set_setting(self, key: str, value: Any, scope: str, object_id: str | None = None) -> str:
        key = self._key(key)
        d = REGISTRY[key]
        if d.type == "json" and isinstance(value, str):
            value = json.loads(value)
        old = self.resolver().resolve(key).value
        new = coerce(d, value)
        oid = uuid.UUID(object_id) if object_id else None
        entry = set_value(
            self.db,
            self.actor,
            scope=scope,
            key=key,
            value=new,
            tenant_id=None if scope == "platform" else self.actor.tenant_id,
            object_id=oid,
        )
        label = setting_text(key)["label"]
        self.changes.append(
            {"key": key, "label": label, "old": old, "new": new, "scope": scope, "audit_id": str(entry.id)}
        )
        return f"Geändert: {label} von {_fmt(old)} auf {_fmt(new)} {d.unit or ''} (Ebene {scope}). Rückgängig im Änderungsprotokoll."

    def tool_reset_setting(self, key: str, scope: str, object_id: str | None = None) -> str:
        key = self._key(key)
        old = self.resolver().resolve(key).value
        oid = uuid.UUID(object_id) if object_id else None
        batch_id, count = reset(
            self.db,
            self.actor,
            scope=scope,
            key=key,
            tenant_id=None if scope == "platform" else self.actor.tenant_id,
            object_id=oid,
        )
        new = self.resolver().resolve(key).value
        label = setting_text(key)["label"]
        if count:
            self.changes.append(
                {
                    "key": key,
                    "label": label,
                    "old": old,
                    "new": new,
                    "scope": scope,
                    "batch_id": str(batch_id),
                    "reset": True,
                }
            )
        return f"Zurückgesetzt: {label}, jetzt {_fmt(new)} (geerbt)."

    def tool_search_guide(self, query: str) -> str:
        return "\n\n".join(guide_sections(query)) or "Dazu steht nichts in der Funktionsbeschreibung."


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


def system_prompt(db, actor: Actor) -> str:
    base = prompt_for(db, actor.tenant_id, "settings_assistant")["system"]
    rows = _settings_table(SettingsResolver(db, actor.tenant_id), actor)
    table = "\n".join(
        f"{r['key']} | {r['label']} | {_fmt(r['value'])} {r['unit'] or ''} | {ORIGIN.get(r['origin'], r['origin'])}"
        for r in rows
    )
    who = f"Benutzer: {actor.label}, Rolle {actor.role}, " + (
        "Ebene Betrieb (scope 'tenant')." if actor.tenant_id else "Ebene Plattform/Admin (scope 'platform')."
    )
    return f"{base}\n\n{who}\n\n# Funktionsbeschreibung der App\n\n{app_guide()[:30000]}\n\n# Einstellungen (Schlüssel | Name | Wert | Herkunft)\n\n{table}"


@router.post("/chat")
def chat(data: ChatIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """One answer of the settings AI; changes are made through tools and listed for undo."""
    actor.require("ai.use") if actor.tenant_id else actor.require("platform.settings")
    resolver = SettingsResolver(db, actor.tenant_id)
    if actor.tenant_id is not None:
        status = spend_status(db, actor.tenant_id, resolver)
        if status["blocked"] and resolver.get("ai.key_mode") != "byok":
            raise AppError("errors.ai_limit", status_code=402)
    resolved = resolve_model(db, resolver, "settings_assistant")
    provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
    key, key_mode = api_key_for(db, actor.tenant_id, resolver, resolved.provider)
    runner = ToolRunner(db, actor)
    system = system_prompt(db, actor)
    messages: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in data.messages]
    options = {
        "effort": resolved.model.effort or "medium",
        "settings_index": [{"key": k, "label": setting_text(k)["label"]} for k in REGISTRY],
        "default_scope": _scope_of(actor),
    }
    text = ""
    for _round in range(MAX_ROUNDS):
        started = time.monotonic()
        try:
            turn = provider.chat(resolved.model.model_name, system, messages, TOOLS, key, options)
        except ProviderError as exc:
            _record(
                actor.tenant_id,
                "settings_assistant",
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
        from app.ai.providers import AIResponse

        usage = AIResponse(
            text=turn.text,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        _record(
            actor.tenant_id,
            "settings_assistant",
            resolved.provider,
            resolved.model,
            key_mode,
            usage,
            cost_eur(resolved.model, resolver, turn.input_tokens, turn.output_tokens),
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
        for call in turn.tool_calls:
            out, is_error = runner.run(call["name"], dict(call.get("input") or {}))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": out,
                    **({"is_error": True} if is_error else {}),
                }
            )
        messages.append({"role": "user", "content": results})
    return {
        "text": text or t("assistant.no_answer"),
        "changes": runner.changes,
        "model": resolved.model.model_name,
    }
