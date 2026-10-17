"""AI functions: JSON schemas of the structured outputs and the default prompts.

The default prompts are seeded into prompt_templates (version 1, global) and can be edited by the
admin or overridden per tenant. Every extracted value is returned as {value, confidence}.
"""

from __future__ import annotations

from typing import Any

FUNCTIONS = ("completeness_check", "photo_analysis", "message_intake", "settings_assistant", "support_agent")


def vf(kind: str) -> dict[str, Any]:
    """A value with confidence (0..1). value may be null if unknown."""
    return {
        "type": "object",
        "properties": {"value": {"type": [kind, "null"]}, "confidence": {"type": "number"}},
        "required": ["value", "confidence"],
        "additionalProperties": False,
    }


def obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


INTAKE_SCHEMA = obj(
    {
        "customer": obj(
            {"name": vf("string"), "company": vf("string"), "email": vf("string"), "phone": vf("string")}
        ),
        "address": obj(
            {
                "street": vf("string"),
                "postal_code": vf("string"),
                "city": vf("string"),
                "floor": vf("string"),
                "parking_notes": vf("string"),
                "access_notes": vf("string"),
            }
        ),
        "order": obj({"earliest_date": vf("string"), "latest_date": vf("string"), "notes": vf("string")}),
        "plants": {
            "type": "array",
            "items": obj(
                {
                    "label": vf("string"),
                    "species": vf("string"),
                    "count": vf("integer"),
                    "pot_diameter_cm": vf("number"),
                    "pot_height_cm": vf("number"),
                    "total_height_cm": vf("number"),
                    "crown_width_cm": vf("number"),
                    "weight_kg": vf("number"),
                    "location": vf("string"),
                    "notes": vf("string"),
                }
            ),
        },
        "path": obj(
            {
                "length_m": vf("number"),
                "steps": vf("integer"),
                "height_m": vf("number"),
                "min_width_cm": vf("number"),
                "elevator": vf("boolean"),
                "surface": vf("string"),
                "description": vf("string"),
            }
        ),
        "missing": {"type": "array", "items": {"type": "string"}},
        "follow_up_message": {"type": "string"},
    }
)

COMPLETENESS_SCHEMA = obj(
    {
        "photos": {
            "type": "array",
            "items": obj(
                {
                    "index": {"type": "integer"},
                    "kind": {"type": "string"},
                    "usable": {"type": "boolean"},
                    "plant_fully_visible": {"type": ["boolean", "null"]},
                    "a4_visible": {"type": ["boolean", "null"]},
                    "issues": {"type": "array", "items": {"type": "string"}},
                }
            ),
        },
        "missing": {"type": "array", "items": {"type": "string"}},
        "path_complete": {"type": ["boolean", "null"]},
        "overall_ok": {"type": "boolean"},
        "feedback": {"type": "array", "items": {"type": "string"}},
    }
)

PHOTO_ANALYSIS_SCHEMA = obj(
    {
        "plant": obj(
            {
                "species": vf("string"),
                "total_height_cm": vf("number"),
                "crown_width_cm": vf("number"),
                "crown_height_cm": vf("number"),
                "crown_shape": vf("string"),
                "crown_density": vf("number"),
                "pot_diameter_cm": vf("number"),
                "pot_height_cm": vf("number"),
                "pot_shape": vf("string"),
                "pot_material": vf("string"),
                "weight_kg": vf("number"),
            }
        ),
        "path": obj(
            {
                "length_m": vf("number"),
                "steps": vf("integer"),
                "height_m": vf("number"),
                "min_width_cm": vf("number"),
                "doors": vf("integer"),
                "surface": vf("string"),
                "elevator": vf("boolean"),
            }
        ),
        "a4_used": {"type": "boolean"},
        "notes": {"type": "string"},
    }
)

SCHEMAS = {
    "message_intake": INTAKE_SCHEMA,
    "completeness_check": COMPLETENESS_SCHEMA,
    "photo_analysis": PHOTO_ANALYSIS_SCHEMA,
}

DEFAULT_PROMPTS: dict[str, dict[str, str]] = {
    "message_intake": {
        "system": (
            "Du unterstützt eine Gärtnerei, die im Herbst Kübelpflanzen bei Kunden abholt, überwintert und im "
            "Frühjahr zurückbringt. Du liest weitergeleitete Kundennachrichten (E-Mail, Chat, Sprachnachricht als "
            "Text, Fotos) und erzeugst daraus einen Entwurf für Kunde, Adresse, Auftrag, Pflanzen und den Weg vom "
            "Stellplatz zum Fahrzeug.\n\n"
            "Regeln:\n"
            "- Erfinde nichts. Unbekannte Werte sind null mit Sicherheit 0.\n"
            "- Gib zu jedem Wert eine Sicherheit zwischen 0 und 1 an: 0,9+ wenn wörtlich genannt, 0,5–0,8 wenn "
            "aus Fotos oder Andeutungen abgeleitet, unter 0,5 bei Vermutungen.\n"
            "- Maße in Zentimetern, Gewichte in Kilogramm, Weglängen in Metern. Rechne Angaben wie „1,80 m“ um.\n"
            "- Mehrere gleiche Pflanzen: ein Eintrag mit count.\n"
            "- Pflanzenarten auf Deutsch, möglichst wie im mitgelieferten Katalog benannt.\n"
            "- Weglänge und Gewicht sind meist unsicher: niedrige Sicherheit, wenn nicht ausdrücklich genannt.\n"
            "- missing: kurze deutsche Stichworte, was für die Planung fehlt.\n"
            "- follow_up_message: eine freundliche, kurze Rückfrage an den Kunden auf Deutsch (Sie-Form), die nach "
            "den fehlenden Angaben bzw. Fotos fragt; leer, wenn nichts fehlt."
        ),
        "instructions": "Erzeuge den Entwurf als JSON nach dem vorgegebenen Schema.",
    },
    "completeness_check": {
        "system": (
            "Du prüfst Fotos, die Kunden einer Gärtnerei für die Abholung von Kübelpflanzen schicken. Für jede "
            "Pflanze werden erwartet: frontal und seitlich mit einem A4-Blatt am Stamm, schräg von oben, der Topf "
            "aus der Nähe mit A4-Blatt; für den Weg eine lückenlose Bildfolge vom Stellplatz bis zum Fahrzeug "
            "(Start, jede Tür, jede Treppe, jede Engstelle, Ende).\n"
            "Prüfe je Foto: Ist die Pflanze ganz im Bild, ist das Bild scharf und gut belichtet, liegt das A4-Blatt "
            "flach und ist es vollständig sichtbar? Ist der Weg lückenlos, sind Stufen und Engstellen erkennbar?\n"
            "Gib konkrete, kurze Rückmeldungen auf Deutsch, z. B. „Bild 3 fehlt: Topf aus der Nähe“ oder "
            "„Bild 2: A4-Blatt verdeckt“."
        ),
        "instructions": "Antworte als JSON nach dem vorgegebenen Schema.",
    },
    "photo_analysis": {
        "system": (
            "Du schätzt aus Fotos die Maße von Kübelpflanzen und die Eigenschaften des Wegs. Ein A4-Blatt "
            "(21,0 × 29,7 cm) am Stamm dient als Maßstab; wenn eine lokale Erkennung den Maßstab (cm pro Pixel) "
            "mitliefert, nutze ihn. Gib zu jedem Wert eine Sicherheit zwischen 0 und 1 an. Gewicht nur schätzen, "
            "wenn der Topf gut erkennbar ist; Erde wiegt etwa 1,2–1,6 kg pro Liter. Unbekanntes ist null."
        ),
        "instructions": "Antworte als JSON nach dem vorgegebenen Schema.",
    },
    "settings_assistant": {
        "system": (
            "Du bist die Einstellungs-KI des Kübelpflanzen-Planers. Du kennst alle Funktionen der App (siehe "
            "Funktionsbeschreibung) und alle Einstellungen mit ihren aktuellen Werten und ihrer Herkunft. "
            "Erkläre verständlich auf Deutsch. Wenn der Benutzer eine Änderung wünscht, ändere sie mit den "
            "Werkzeugen und sage danach genau, was du geändert hast (alter und neuer Wert) und dass es im "
            "Änderungsprotokoll mit einem Klick rückgängig gemacht werden kann. Ändere nur, was ausdrücklich "
            "gewünscht ist. Frage nach, wenn unklar ist, welcher Wert oder welche Ebene gemeint ist."
        ),
        "instructions": "",
    },
    "support_agent": {
        "system": "Du hilfst Benutzern des Kübelpflanzen-Planers bei Fragen zur Bedienung. Antworte kurz und auf Deutsch.",
        "instructions": "",
    },
}
