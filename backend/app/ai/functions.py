"""AI functions: JSON schemas of the structured outputs and the default prompts.

The default prompts are seeded into prompt_templates (version 1, global) and can be edited by the
admin or overridden per tenant. Every extracted value is returned as {value, confidence}.
"""

from __future__ import annotations

from typing import Any

FUNCTIONS = (
    "completeness_check",
    "photo_analysis",
    "message_intake",
    "settings_assistant",
    "support_agent",
    "vehicle_photo",
    "vehicle_chat",
)


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


def plant_traits() -> dict[str, Any]:
    """Properties the AI determines per plant (package B); stored on the plant with their confidence."""
    return {
        "frost_sensitive": vf("boolean"),
        "can_tilt": vf("boolean"),
        "sensitive": vf("boolean"),
        "compressibility": vf("number"),
        "tip_tendency": vf("number"),
    }


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
                    **plant_traits(),
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
                **plant_traits(),
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


def vehicle_schema() -> dict[str, Any]:
    """Vehicle draft (package C): vehicle values, costs and shelves, each with a confidence."""
    from app.fleet.fields import COST_FIELDS, SHELF_FIELDS, VEHICLE_FIELDS

    return obj(
        {
            "vehicle": obj({k: vf(kind) for k, kind in VEHICLE_FIELDS}),
            "costs": obj({k: vf(kind) for k, _, kind in COST_FIELDS}),
            "shelves": {"type": "array", "items": obj({k: vf(kind) for k, kind in SHELF_FIELDS})},
            "scale": {"type": "string", "enum": ["a4", "ruler", "known_model", "stated", "none"]},
            "questions": {"type": "array", "items": {"type": "string"}},
            "reply": {"type": "string"},
        }
    )


SCHEMAS = {
    "message_intake": INTAKE_SCHEMA,
    "completeness_check": COMPLETENESS_SCHEMA,
    "photo_analysis": PHOTO_ANALYSIS_SCHEMA,
    "vehicle_photo": vehicle_schema(),
    "vehicle_chat": vehicle_schema(),
}

TRAIT_RULES = (
    "- Bestimme je Pflanze die Art (deutscher Name, möglichst wie im mitgelieferten Katalog) und ihre "
    "Eigenschaften für Transport und Überwinterung: frost_sensitive (verträgt keinen Frost, z. B. Zitrus, "
    "Bougainvillea, Engelstrompete), can_tilt (darf zum Transport schräg gelegt werden), sensitive "
    "(empfindliche Blätter oder Blüten), compressibility (0 = starre Krone, 1 = Krone lässt sich stark "
    "zusammendrücken) und tip_tendency (0 = steht sicher, 1 = kippt leicht, z. B. hohe schmale Pflanzen in "
    "kleinen Töpfen). Leite sie aus Art, Fotos und Beschreibung ab und gib eine ehrliche Sicherheit an; "
    "was nicht ableitbar ist, ist null.\n"
)

DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {
    "message_intake": {
        "version": 2,
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
            + TRAIT_RULES
            + "- Weglänge und Gewicht sind meist unsicher: niedrige Sicherheit, wenn nicht ausdrücklich genannt.\n"
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
        "version": 2,
        "system": (
            "Du schätzt aus Fotos die Maße von Kübelpflanzen und die Eigenschaften des Wegs. Ein A4-Blatt "
            "(21,0 × 29,7 cm) am Stamm dient als Maßstab; wenn eine lokale Erkennung den Maßstab (cm pro Pixel) "
            "mitliefert, nutze ihn. Gib zu jedem Wert eine Sicherheit zwischen 0 und 1 an. Gewicht nur schätzen, "
            "wenn der Topf gut erkennbar ist; Erde wiegt etwa 1,2–1,6 kg pro Liter. Unbekanntes ist null.\n"
            + TRAIT_RULES
        ),
        "instructions": "Antworte als JSON nach dem vorgegebenen Schema.",
    },
    "vehicle_photo": {
        "version": 1,
        "system": (
            "Du leitest aus Fotos des Laderaums eines Transporters, Lkw oder Anhängers das Fahrzeugmodell für "
            "die Ladeplanung einer Gärtnerei ab. Maßstab ist ein A4-Blatt (21,0 × 29,7 cm) oder ein Zollstock im "
            "Bild; wenn eine lokale Erkennung den Maßstab (cm pro Pixel) mitliefert, nutze ihn. Bestimme "
            "Laderaum (Länge von der Stirnwand bis zur Tür, Breite, Höhe), Türbreite und -höhe, Radkästen "
            "(Abstand von der Stirnwand, Länge, Breite je Seite, Höhe), Regale (Lage von der Stirnwand und der "
            "linken Wand, Länge, Tiefe, Höhe der Ebene, freie Höhe darüber) und die Ladekante. Alle Maße in cm. "
            "Gib zu jedem Wert eine ehrliche Sicherheit zwischen 0 und 1; ohne Maßstab höchstens 0,4. Werte, "
            "die man auf Fotos nicht sieht (Nutzlast, Achslasten, Kosten), sind null, außer der Text nennt sie. "
            "questions: kurze deutsche Rückfragen zu fehlenden oder unsicheren Werten (Sie-Form), z. B. "
            "„Wie hoch ist die zulässige Nutzlast laut Fahrzeugschein?“. reply: eine kurze Zusammenfassung."
        ),
        "instructions": "Antworte als JSON nach dem vorgegebenen Schema.",
    },
    "vehicle_chat": {
        "version": 1,
        "system": (
            "Du legst mit dem Inhaber einer Gärtnerei im Gespräch ein Fahrzeug für die Touren- und Ladeplanung "
            "an oder änderst es. Du bekommst den bisherigen Verlauf, den aktuellen Entwurf (Werte mit "
            "Sicherheit) und die neue Nachricht, optional Fotos und Angaben aus dem Fahrzeugschein. Gib den "
            "vollständigen, aktualisierten Entwurf zurück: übernimm alle bisherigen Werte, ändere nur, was die "
            "Nachricht ändert oder ergänzt. Bekannte Modelle (z. B. Mercedes Sprinter L2H2, VW Crafter, Ford "
            "Transit, Fiat Ducato) darfst du mit typischen Werten füllen, aber mit Sicherheit höchstens 0,6. "
            "Maße in cm, Gewichte in kg, Kosten in € (pro km, pro Stunde), Verbrauch in l/100 km. kind: van, "
            "truck, trailer oder car; required_licence: B, BE, C1, C1E, C oder CE. Regale als shelves mit Lage "
            "von der Stirnwand (x_cm) und der linken Wand (y_cm). questions: höchstens drei kurze Rückfragen zu "
            "den wichtigsten Lücken (Laderaum, Nutzlast, Türmaße zuerst). reply: freundliche, kurze Antwort "
            "auf Deutsch in Sie-Form, die sagt, was du eingetragen oder geändert hast."
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
