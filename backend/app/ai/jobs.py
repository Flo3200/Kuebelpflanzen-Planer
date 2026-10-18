"""Background jobs of the AI layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.ai import intake
from app.core.errors import AppError
from app.jobs.queue import JobContext, handler
from app.models.orders import Draft, Photo, PickupOrder, Plant
from app.settings.service import SettingsResolver


@handler("ai.process_draft")
def process_draft_job(ctx: JobContext) -> dict:
    draft_id = uuid.UUID(ctx.payload["draft_id"])
    ctx.progress(0.1, "KI wertet die Nachricht aus …")
    try:
        draft = intake.process_draft(ctx.db, ctx.tenant_id, draft_id, job_id=ctx.job_id)
    except AppError as exc:
        draft = ctx.db.get(Draft, draft_id)
        if draft is not None:
            draft.status = "failed"
            draft.error = exc.code
        ctx.db.commit()
        raise
    return {"draft_id": str(draft.id), "review_fields": len(draft.review_fields or [])}


@handler("ai.check_order_photos")
def check_order_photos_job(ctx: JobContext) -> dict:
    order = ctx.db.get(PickupOrder, uuid.UUID(ctx.payload["order_id"]))
    photos = intake.order_photos(ctx.db, order)
    ctx.progress(0.2, "Fotos werden geprüft …")
    result = intake.completeness(ctx.db, ctx.tenant_id, photos, job_id=ctx.job_id)
    est = dict(order.estimate or {})
    est["photo_check"] = result
    order.estimate = est
    return result


@handler("ai.analyse_order_photos")
def analyse_order_photos_job(ctx: JobContext) -> dict:
    order = ctx.db.get(PickupOrder, uuid.UUID(ctx.payload["order_id"]))
    threshold = float(SettingsResolver(ctx.db, ctx.tenant_id).get("photos.min_confidence"))
    plants = list(ctx.db.scalars(select(Plant).where(Plant.order_id == order.id, Plant.deleted_at.is_(None))))
    changed: dict[str, list[str]] = {}
    for i, plant in enumerate(plants):
        ctx.progress((i + 0.5) / max(1, len(plants)), f"Pflanze #{plant.number} wird ausgewertet …")
        photos = list(ctx.db.scalars(select(Photo).where(Photo.plant_id == plant.id)))
        if not photos:
            continue
        analysis = intake.analyse_photos(ctx.db, ctx.tenant_id, photos, job_id=ctx.job_id)
        changed[str(plant.id)] = intake.apply_analysis_to_plant(ctx.db, plant, analysis, threshold)
    try:
        from app.timemodel.service import refresh_order_estimate

        refresh_order_estimate(ctx.db, order)
    except ModuleNotFoundError:
        pass
    return {"changed": changed}


@handler("ai.eval_run")
def eval_run_job(ctx: JobContext) -> dict:
    """Run photo analysis with one model on every item of a test set; mean absolute error per quantity."""
    from sqlalchemy import func as sa_func

    from app.ai import service as ai
    from app.ai.providers import AIImage
    from app.models.ai import AIUsage, EvalItem, EvalRun, EvalSet
    from app.models.orders import StoredFile
    from app.storage.backend import get_storage

    run = ctx.db.get(EvalRun, uuid.UUID(ctx.payload["run_id"]))
    run.status = "running"
    function = (
        (ctx.db.get(EvalSet, run.set_id).function or "photo_analysis") if run.set_id else "photo_analysis"
    )
    items = list(ctx.db.scalars(select(EvalItem).where(EvalItem.set_id == run.set_id)))
    errors: dict[str, list[float]] = {}
    details = []
    for i, item in enumerate(items):
        ctx.progress(i / max(1, len(items)), f"{item.label}")
        images = []
        context_photos = []
        for ref in item.photo_file_ids:
            stored = ctx.db.get(StoredFile, uuid.UUID(ref["file_id"]))
            data = get_storage().get(stored.key)
            from app.ai.imagecheck import analyse as local

            q = local(data)
            images.append(AIImage(data=data, label=ref.get("kind")))
            context_photos.append(
                {
                    "kind": ref.get("kind"),
                    "a4": q["a4"],
                    "width": ref.get("width"),
                    "height": ref.get("height"),
                }
            )
        try:
            if function == "vehicle_chat":
                text = item.input_text or ""
                context = {"message": text, "messages": [{"role": "user", "text": text}], "threshold": 0.6}
            elif function == "vehicle_photo":
                text = "Fotos des Laderaums:\n" + "\n".join(
                    f"Bild {n}: {p['width']}×{p['height']} px"
                    + (f", A4-Maßstab {p['a4'].get('cm_per_px')} cm/px" if p["a4"].get("detected") else "")
                    for n, p in enumerate(context_photos, start=1)
                )
                if item.input_text:
                    text += f"\n\nAngaben dazu: {item.input_text}"
                context = {"photos": context_photos, "note": item.input_text or "", "threshold": 0.6}
            else:
                text, context = "Bitte auswerten.", {"photos": context_photos}
            resp, _ = ai.call(
                ctx.db,
                None,
                function,
                text,
                images=images,
                context=context,
                job_id=ctx.job_id,
                model_id=run.model_id,
            )
            section = "plant" if function == "photo_analysis" else "vehicle"
            plant = (resp.data or {}).get(section) or {}
        except AppError as exc:
            details.append({"item": item.label, "error": exc.code})
            continue
        row = {"item": item.label}
        for field, truth in (item.truth or {}).items():
            pred = (plant.get(field) or {}).get("value")
            if pred is None or truth is None:
                continue
            err = abs(float(pred) - float(truth))
            errors.setdefault(field, []).append(err)
            row[field] = {"truth": truth, "pred": pred, "abs_error": round(err, 1)}
        details.append(row)
    cost = (
        ctx.db.scalar(
            select(sa_func.coalesce(sa_func.sum(AIUsage.cost_eur), 0)).where(AIUsage.job_id == ctx.job_id)
        )
        or 0
    )
    run.metrics = {
        "mae": {k: round(sum(v) / len(v), 2) for k, v in errors.items()},
        "n": {k: len(v) for k, v in errors.items()},
        "items": len(items),
        "cost_eur": round(float(cost), 4),
        "cost_per_item_eur": round(float(cost) / max(1, len(items)), 5),
    }
    run.items = details
    run.status = "done"
    return run.metrics
