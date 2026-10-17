"""Database engine, sessions and the row-level-security context.

Every transaction gets two transaction-local settings:
  app.tenant_id   – the tenant whose rows are visible ('' = none)
  app.bypass_rls  – 'on' for platform admin and system processes
They are applied in the `after_begin` hook, so they survive intermediate commits.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_config


@dataclass(frozen=True)
class RlsContext:
    tenant_id: uuid.UUID | None = None
    bypass: bool = False


SYSTEM = RlsContext(bypass=True)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def configure_engine(url: str | None = None) -> Engine:
    """(Re)create the global engine. Tests call this with the test database URL."""
    global _engine, _session_factory
    cfg = get_config()
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(
        url or cfg.database_url,
        pool_pre_ping=True,
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_pool_size,
    )
    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def new_session(ctx: RlsContext) -> Session:
    if _session_factory is None:
        configure_engine()
    assert _session_factory is not None
    session = _session_factory()
    session.info["rls"] = ctx
    return session


@contextmanager
def session_scope(ctx: RlsContext, commit: bool = True) -> Iterator[Session]:
    session = new_session(ctx)
    try:
        yield session
        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def system_session(commit: bool = True):
    return session_scope(SYSTEM, commit=commit)


def tenant_session(tenant_id: uuid.UUID, commit: bool = True):
    return session_scope(RlsContext(tenant_id=tenant_id), commit=commit)


def set_rls(session: Session, ctx: RlsContext) -> None:
    """Change the context of an open session; takes effect immediately."""
    session.info["rls"] = ctx
    if session.in_transaction():
        _apply(session.connection(), ctx)


def _apply(connection, ctx: RlsContext) -> None:
    connection.exec_driver_sql(
        "SELECT set_config('app.tenant_id', %s, true), set_config('app.bypass_rls', %s, true)",
        (str(ctx.tenant_id) if ctx.tenant_id else "", "on" if ctx.bypass else "off"),
    )


@event.listens_for(Session, "after_begin")
def _after_begin(session: Session, transaction, connection) -> None:
    ctx = session.info.get("rls") or RlsContext()
    _apply(connection, ctx)
