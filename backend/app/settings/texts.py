"""Labels and explanations of settings, taken from the translation catalog."""

from __future__ import annotations

from app.i18n import DEFAULT_LANG, catalog


def setting_text(key: str, lang: str = DEFAULT_LANG) -> dict[str, str]:
    entry = catalog(lang).get("settings", {}).get(key, {})
    return {"label": entry.get("label", key), "help": entry.get("help", "")}


def group_label(group: str, lang: str = DEFAULT_LANG) -> str:
    return catalog(lang).get("setting_groups", {}).get(group, group)


def choice_label(key: str, choice: str, lang: str = DEFAULT_LANG) -> str:
    entry = catalog(lang).get("settings", {}).get(key, {})
    return entry.get("choices", {}).get(choice, choice)
