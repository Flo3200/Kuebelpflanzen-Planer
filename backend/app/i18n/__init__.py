"""Server-side translations. All user-facing text lives in <lang>.json next to this file."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent
DEFAULT_LANG = "de"


@lru_cache
def catalog(lang: str = DEFAULT_LANG) -> dict[str, Any]:
    path = _DIR / f"{lang}.json"
    if not path.exists():
        path = _DIR / f"{DEFAULT_LANG}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lookup(key: str, lang: str = DEFAULT_LANG) -> Any:
    node: Any = catalog(lang)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def t(msgkey: str, /, *, _lang: str = DEFAULT_LANG, _default: str | None = None, **params: Any) -> str:
    """Translate a dotted key. Unknown keys return the default or the key itself.
    Parameters are inserted with str.format (e.g. {key}, {min})."""
    value = lookup(msgkey, _lang)
    if not isinstance(value, str):
        value = _default if _default is not None else msgkey
    if params:
        try:
            value = value.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return value
