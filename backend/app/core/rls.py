"""SQL for row-level-security policies and grants, used by the migrations."""

from __future__ import annotations

from sqlalchemy.engine import make_url

CUR = "nullif(current_setting('app.tenant_id', true), '')::uuid"
BYPASS = "coalesce(current_setting('app.bypass_rls', true), '') = 'on'"


def policy_sql(table: str, mode: str) -> list[str]:
    stmts = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]
    for name in ("p_all", "p_sel", "p_ins", "p_upd", "p_del"):
        stmts.append(f"DROP POLICY IF EXISTS {name} ON {table}")
    own = f"({BYPASS} OR tenant_id = {CUR})"
    if mode == "strict":
        stmts.append(f"CREATE POLICY p_all ON {table} USING {own} WITH CHECK {own}")
    elif mode == "shared":
        stmts += [
            f"CREATE POLICY p_sel ON {table} FOR SELECT USING ({BYPASS} OR tenant_id IS NULL OR tenant_id = {CUR})",
            f"CREATE POLICY p_ins ON {table} FOR INSERT WITH CHECK {own}",
            f"CREATE POLICY p_upd ON {table} FOR UPDATE USING {own} WITH CHECK {own}",
            f"CREATE POLICY p_del ON {table} FOR DELETE USING {own}",
        ]
    elif mode == "self":
        mine = f"({BYPASS} OR id = {CUR})"
        stmts += [
            f"CREATE POLICY p_sel ON {table} FOR SELECT USING {mine}",
            f"CREATE POLICY p_ins ON {table} FOR INSERT WITH CHECK ({BYPASS})",
            f"CREATE POLICY p_upd ON {table} FOR UPDATE USING {mine} WITH CHECK {mine}",
            f"CREATE POLICY p_del ON {table} FOR DELETE USING ({BYPASS})",
        ]
    else:
        raise ValueError(f"unknown RLS mode {mode}")
    return stmts


def app_role_name(database_url: str) -> str:
    return make_url(database_url).username or "kp_app"


def grant_sql(app_role: str) -> list[str]:
    return [
        f"GRANT USAGE ON SCHEMA public TO {app_role}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app_role}",
        # the version table is managed by the owner only
        f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {app_role}",
    ]


def apply_all(op, tables: dict[str, str]) -> None:
    """Called at the end of each migration: (re)apply policies for the given tables and grants."""
    import os

    from app.core.config import get_config

    for table, mode in tables.items():
        for stmt in policy_sql(table, mode):
            op.execute(stmt)
    app_url = os.environ.get("KP_APP_URL") or get_config().database_url
    for stmt in grant_sql(app_role_name(app_url)):
        op.execute(stmt)
