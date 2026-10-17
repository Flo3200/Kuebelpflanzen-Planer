"""Append RLS policies for the tables a migration creates.

Usage after `alembic revision --autogenerate`:  uv run python tools/add_rls.py alembic/versions/<file>.py
"""

import re
import sys

from app.models import rls_tables

path = sys.argv[1]
src = open(path, encoding="utf-8").read()
created = re.findall(r"op\.create_table\(\s*['\"](\w+)['\"]", src)
modes = rls_tables()
tables = {t: modes[t] for t in created if t in modes}
if "apply_all(" in src:
    sys.exit("already contains apply_all")
src = src.replace("from alembic import op\n", "from alembic import op\n\nfrom app.core.rls import apply_all\n", 1)
marker = "    # ### end Alembic commands ###\n"
idx = src.index(marker) + len(marker)
body = "    apply_all(\n        op,\n        {\n" + "".join(f'            "{t}": "{m}",\n' for t, m in tables.items()) + "        },\n    )\n"
src = src[:idx] + body + src[idx:]
open(path, "w", encoding="utf-8").write(src)
print(f"RLS for {len(tables)} tables: {', '.join(tables)}")
