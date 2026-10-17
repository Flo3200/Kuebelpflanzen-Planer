"""Seed AI providers, models and prompts on first start (all editable by the admin afterwards)."""

from __future__ import annotations

from sqlalchemy import select
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
        exists = db.scalar(
            select(PromptTemplate.id)
            .where(PromptTemplate.tenant_id.is_(None), PromptTemplate.function == function)
            .limit(1)
        )
        if exists is None:
            db.add(
                PromptTemplate(
                    tenant_id=None,
                    function=function,
                    version=1,
                    system=prompt["system"],
                    instructions=prompt["instructions"],
                    active=True,
                    note="Standard",
                )
            )
    db.flush()
