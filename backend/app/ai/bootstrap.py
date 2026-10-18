"""Seed AI providers, models and prompts on first start (all editable by the admin afterwards)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.functions import DEFAULT_PROMPTS
from app.models.ai import AIModel, AIProvider, PromptTemplate

# Model names are only seed data; the admin maintains them in the UI.
SEED = [
    {
        "provider": {"name": "Testmodell", "kind": "fake", "active": True},
        "models": [
            {
                "model_name": "fake-1",
                "label": "Testmodell (ohne KI, kostenlos)",
                "is_default": True,
                "input_price_per_mtok": 0,
                "output_price_per_mtok": 0,
                "supports_tools": True,
            },
        ],
    },
    {
        "provider": {"name": "Anthropic", "kind": "anthropic", "active": True},
        "models": [
            {
                "model_name": "claude-opus-5-5",
                "label": "Claude Opus 5.5",
                "input_price_per_mtok": 4.0,
                "output_price_per_mtok": 20.0,
                "use_fallbacks": True,
                "effort": "medium",
            },
            {
                "model_name": "claude-sonnet-5-5",
                "label": "Claude Sonnet 5.5",
                "input_price_per_mtok": 2.0,
                "output_price_per_mtok": 10.0,
                "use_fallbacks": True,
                "effort": "medium",
            },
            {
                "model_name": "claude-haiku-5-5",
                "label": "Claude Haiku 5.5",
                "input_price_per_mtok": 0.10,
                "output_price_per_mtok": 0.50,
                "use_fallbacks": False,
                "effort": "low",
            },
        ],
    },
    {"provider": {"name": "OpenAI", "kind": "openai", "active": False}, "models": []},
]


def seed_ai(db: Session) -> None:
    if db.scalar(select(AIProvider.id).limit(1)) is None:
        for entry in SEED:
            provider = AIProvider(**entry["provider"])
            db.add(provider)
            db.flush()
            for m in entry["models"]:
                db.add(AIModel(provider_id=provider.id, price_currency="USD", **m))
    for function, prompt in DEFAULT_PROMPTS.items():
        # a newer default prompt becomes a new global version; versions the admin made stay and win
        # while they are newer, older ones remain in the history (prompts are versioned, never edited)
        version = int(prompt.get("version", 1))
        latest = db.scalar(
            select(func.max(PromptTemplate.version)).where(
                PromptTemplate.tenant_id.is_(None), PromptTemplate.function == function
            )
        )
        if latest is None or latest < version:
            db.add(
                PromptTemplate(
                    tenant_id=None,
                    function=function,
                    version=version,
                    system=prompt["system"],
                    instructions=prompt["instructions"],
                    active=True,
                    note="Standard" if version == 1 else f"Standard (Version {version})",
                )
            )
    db.flush()


# test set for the evaluation tool: vehicle by chat (photo sets need real photos, the admin adds them)
VEHICLE_CHAT_EVAL = [
    (
        "Sprinter mit Maßen",
        "Mercedes Sprinter, Laderaum 3,30 x 1,78 x 1,94 m, Nutzlast 1.150 kg. "
        "Die Tür ist 1,56 m breit und 1,84 m hoch.",
        {
            "cargo_length_cm": 330,
            "cargo_width_cm": 178,
            "cargo_height_cm": 194,
            "payload_kg": 1150,
            "door_width_cm": 156,
            "door_height_cm": 184,
        },
    ),
    (
        "7,5-Tonner",
        "Unser 7,5-Tonner mit Ladebordwand: Ladefläche 6,10 m lang, 2,45 m breit, 2,40 m hoch. "
        "Nutzlast 2,8 t, Führerschein C1.",
        {"cargo_length_cm": 610, "cargo_width_cm": 245, "cargo_height_cm": 240, "payload_kg": 2800},
    ),
    (
        "Kofferanhänger",
        "Kofferanhänger 3,00 x 1,50 x 1,80 m, Nutzlast 1000 kg.",
        {"cargo_length_cm": 300, "cargo_width_cm": 150, "cargo_height_cm": 180, "payload_kg": 1000},
    ),
]


def seed_eval_sets(db: Session) -> None:
    from app.models.ai import EvalItem, EvalSet

    if db.scalar(select(EvalSet.id).where(EvalSet.function == "vehicle_chat").limit(1)) is not None:
        return
    s = EvalSet(
        tenant_id=None,
        name="Fahrzeug per Chat – Beispiele",
        function="vehicle_chat",
        notes="Beschreibungen mit bekannten Maßen; vergleicht die Laderaum-Maße und die Nutzlast.",
    )
    db.add(s)
    db.flush()
    for label, text, truth in VEHICLE_CHAT_EVAL:
        db.add(
            EvalItem(
                tenant_id=None, set_id=s.id, label=label, input_text=text, truth=truth, photo_file_ids=[]
            )
        )
    db.flush()
