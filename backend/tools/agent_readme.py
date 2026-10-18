"""Writes agent/README.md from the running API (the server also serves it live at /agent/README.md).

Usage: uv run python tools/agent_readme.py ../agent/README.md
"""

import sys

from app.agents.readme import render
from app.core.config import get_config
from app.main import create_app

path = sys.argv[1] if len(sys.argv) > 1 else "../agent/README.md"
text = render(create_app(), get_config().base_url)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print(f"{path}: {len(text.splitlines())} Zeilen")
