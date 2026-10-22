"""FastAPI application: API routers, error handling, static frontend, bootstrap."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_config
from app.core.db import system_session
from app.core.errors import AppError
from app.core.security import hash_password
from app.i18n import t
from app.models.core import User

log = logging.getLogger("kp")

API_ROUTER_MODULES = (
    "app.api.auth",
    "app.api.tenants",
    "app.api.settings",
    "app.api.audit",
    "app.api.jobs",
    "app.api.meta",
    "app.api.dashboard",
    "app.api.masterdata",
    "app.api.fleet",
    "app.api.orders",
    "app.api.files",
    "app.api.storage",
    "app.api.ai",
    "app.api.drafts",
    "app.api.formulas",
    "app.api.estimates",
    "app.api.planning",
    "app.api.loading",
    "app.api.driver",
    "app.api.field",
    "app.api.learning",
    "app.api.billing",
    "app.api.agents",
    "app.api.assistant",
    "app.api.privacy",
    "app.api.portal",
    # round 2
    "app.api.notifications",
    "app.api.share",
    "app.api.voice",
    "app.api.tables",
    "app.api.plant_images",
    "app.api.spontaneous",
    "app.api.debates",
)


def bootstrap_admin() -> None:
    cfg = get_config()
    with system_session() as db:
        exists = db.scalar(select(User.id).where(User.role == "admin", User.deleted_at.is_(None)).limit(1))
        if exists is None and cfg.initial_admin_password:
            db.add(
                User(
                    tenant_id=None,
                    email=cfg.initial_admin_email.lower(),
                    name="Plattform-Admin",
                    role="admin",
                    password_hash=hash_password(cfg.initial_admin_password),
                    extra_permissions=[],
                    revoked_permissions=[],
                )
            )
            log.info("initial admin %s created", cfg.initial_admin_email)
        from app.ai.bootstrap import seed_ai
        from app.demo.species_catalog import seed_species

        seed_ai(db)
        from app.ai.bootstrap import seed_eval_sets

        seed_eval_sets(db)
        seed_species(db)
        from app.formula.defaults import seed_formulas

        seed_formulas(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.jobs import worker

    worker.load_handlers()
    try:
        bootstrap_admin()
    except Exception:  # noqa: BLE001 - database may not be migrated yet
        log.exception("bootstrap failed")
    if get_config().embedded_worker:
        worker.start_embedded()
    yield
    worker.stop()


def error_body(code: str, params: dict | None = None, status: int = 400) -> JSONResponse:
    params = params or {}
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": t(code, **params), "params": params}},
    )


def create_app() -> FastAPI:
    import importlib

    app = FastAPI(
        title="Kübelpflanzen-Planer API",
        version="0.1.0",
        description="REST-API der Planungsplattform. Agenten-Anleitung: /agent/README.md",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # agents: bearer tokens and a log entry for every call
    from app.agents.tokens import authenticate as agent_authenticate
    from app.agents.tokens import log_call
    from app.api.deps import BEARER_AUTHENTICATORS

    if agent_authenticate not in BEARER_AUTHENTICATORS:
        BEARER_AUTHENTICATORS.append(agent_authenticate)

    @app.middleware("http")
    async def agent_call_log(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        token_id = getattr(request.state, "agent_token_id", None)
        if token_id is not None:
            actor = getattr(request.state, "actor", None)
            try:
                log_call(
                    token_id,
                    getattr(actor, "tenant_id", None) if actor and actor.role == "agent" else None,
                    getattr(actor, "tenant_id", None),
                    request.method,
                    request.url.path,
                    response.status_code,
                    int((time.monotonic() - started) * 1000),
                )
            except Exception:  # noqa: BLE001 - logging must never break the answer
                logging.getLogger("kp.agents").exception("agent call log failed")
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        resp = error_body(exc.code, {k: str(v) for k, v in exc.params.items()}, exc.status_code)
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        resp = error_body("errors.validation", status=422)
        body = resp.body
        import json

        data = json.loads(body)
        data["error"]["details"] = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=data)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/agent/")):
            index = get_config().frontend_dist_path / "index.html"
            if index.exists() and request.method == "GET":
                return FileResponse(index)
        code = {401: "errors.unauthorized", 403: "errors.forbidden", 404: "errors.not_found"}.get(
            exc.status_code, "errors.validation"
        )
        return error_body(code, status=exc.status_code)

    for mod_name in API_ROUTER_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:
            if exc.name == mod_name:
                continue  # module of a later phase not present
            raise
        for attr in ("router", "health_router", "public_router"):
            r = getattr(mod, attr, None)
            if r is not None:
                app.include_router(r)

    dist = get_config().frontend_dist_path
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        path = dist / "index.html"
        if path.exists():
            return FileResponse(path)
        return JSONResponse({"message": "Frontend nicht gebaut. Siehe README (npm run build)."})

    @app.get("/{name}", include_in_schema=False)
    def root_file(name: str) -> Response:
        """Top-level files of the built frontend (manifest, service worker, icons)."""
        path = (dist / name).resolve()
        if path.is_file() and Path(dist).resolve() in path.parents:
            headers = {"Cache-Control": "no-cache"} if name in ("sw.js", "index.html") else None
            return FileResponse(path, headers=headers)
        index_path = dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return error_body("errors.not_found", status=404)

    return app


app = create_app()
