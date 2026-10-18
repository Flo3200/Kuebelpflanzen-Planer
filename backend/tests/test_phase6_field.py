"""Phase 6 acceptance: synthetic measurements lead to a model fit that approximately recovers the
known true parameters. Plus: driver app flow (PIN login, day package, events with mandatory photo,
breaks, idempotent sync, measurements), deviation reports, outliers, QR labels, experiment mode."""

from __future__ import annotations

import io
import statistics
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import delete, select

from app.core.db import RlsContext, session_scope
from app.formula.store import load_active
from app.learning.fit import FitConfig, fit_params
from app.learning.samples import prepare_samples
from app.learning.synthetic import generate
from app.models.field import Measurement
from app.models.masterdata import StaffMember
from app.models.orders import Plant
from app.models.planning import Tour, TourStop
from app.timemodel.estimate import Estimator

START = date(2026, 10, 19)
TRUE = {"a0": 8.0, "a1": 0.11, "k_height": 0.8, "t_fixed": 14.0}


@pytest.fixture(scope="module")
def field_tenant():
    from app.demo.generator import DEMO_TENANTS, DemoOptions
    from app.demo.generator import generate as demo

    spec = dict(DEMO_TENANTS[0])
    spec["slug"] = f"feld-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Feld Test", f"feld-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Feld", f"dispo-feld-{uuid.uuid4().hex[:6]}@example.com")
    report = demo(DemoOptions(seed=21, orders_per_tenant=40, tenants=[spec]), reset=False)
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1], spec["slug"]


@pytest.fixture
def owner(field_tenant, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(field_tenant[1], DEMO_PASSWORD)
    for key, value in (("planning.time_limit_s", 4), ("learning.cv_folds", 3)):
        api.put("/api/settings", json={"scope": "tenant", "key": key, "value": value})
    return api


def _samples(tid, n, seed, noise=0.12, outliers=0.03, true_staff=None, team_extra=(0, 0, 0, 1, 1, 2)):
    with session_scope(RlsContext(tenant_id=tid)) as db:
        db.execute(delete(Measurement).where(Measurement.tenant_id == tid))
        g = generate(
            db,
            tid,
            n=n,
            true_params=TRUE,
            noise_sigma=noise,
            outlier_share=outliers,
            seed=seed,
            true_staff=true_staff,
            team_extra=team_extra,
        )
        est = Estimator(db, tid)
        samples = prepare_samples(db, tid, est)
        formula = load_active(db, tid, "time", 1)
        db.expunge_all()
        return g, samples, formula


# ---------------------------------------------------------------- acceptance: parameters found again


def test_fit_recovers_true_parameters(field_tenant):
    g, samples, formula = _samples(field_tenant[0], n=220, seed=4)
    out = fit_params(
        samples,
        formula,
        FitConfig(loss="huber", huber_delta=6.0, lam=1.0, min_per_param=15, staff_prior_n=20),
    )
    assert set(out.fitted) == set(TRUE)
    for k, true in TRUE.items():
        assert abs(out.params[k] - true) / true < 0.15, (k, out.params[k], true)
    # personal speed factors: closer to the truth than "everyone 1.0" (shrunk towards 1 by the prior)
    err_fit = statistics.mean(abs(out.staff[k] - g["true_staff"][k]) for k in out.staff)
    err_one = statistics.mean(abs(1.0 - g["true_staff"][k]) for k in out.staff)
    assert err_fit < err_one, (err_fit, err_one)
    # factors are relative to the average worker
    assert abs(statistics.mean(out.staff.values()) - 1.0) < 0.01
    # standard errors are reported and plausible
    assert all(0 < out.se[k] < abs(out.params[k]) for k in TRUE)


def test_personal_factors_found_with_precise_measurements(field_tenant):
    """Each person changes the team speed only by a share, so personal factors need precise data:
    with 5 % noise, small teams and a weak prior they are found again closely."""
    # teams of exactly the required size: light plants are carried alone, so each person shows clearly
    g, samples, formula = _samples(field_tenant[0], n=260, seed=6, noise=0.05, outliers=0, team_extra=(0,))
    out = fit_params(samples, formula, FitConfig(loss="huber", staff_prior_n=1))
    err_fit = statistics.mean(abs(out.staff[k] - g["true_staff"][k]) for k in out.staff)
    err_one = statistics.mean(abs(1.0 - g["true_staff"][k]) for k in out.staff)
    assert err_fit < 0.6 * err_one, (err_fit, err_one)
    for k, true in TRUE.items():
        assert abs(out.params[k] - true) / true < 0.1, (k, out.params[k], true)


def test_huber_resists_outliers_better_than_squares(field_tenant):
    _g, samples, formula = _samples(field_tenant[0], n=180, seed=8, outliers=0.06)
    huber = fit_params(samples, formula, FitConfig(loss="huber"), fit_staff=False)
    plain = fit_params(samples, formula, FitConfig(loss="linear"), fit_staff=False)

    def dist(o):
        return sum(abs(o.params[k] - v) / v for k, v in TRUE.items())

    assert dist(huber) < dist(plain)


def test_few_measurements_fit_only_the_most_influential_parameters(field_tenant):
    _g, samples, formula = _samples(field_tenant[0], n=32, seed=2, outliers=0)
    out = fit_params(samples, formula, FitConfig(min_per_param=15))
    assert len(out.fitted) == 2  # 32 // 15
    # the others keep their current values
    for k, v in formula.version.parameters.items():
        if k not in out.fitted:
            assert out.params[k] == v["value"]


def test_fit_job_report_and_adoption(owner, field_tenant):
    tid = field_tenant[0]
    r = owner.post(
        "/api/learning/synthetic", json={"n": 120, "seed": 5, "true_params": TRUE, "outlier_share": 0.03}
    ).json()
    assert r["created"] == 120
    job = owner.post("/api/learning/fits", expect=201, json={"sync": True}).json()
    assert job["status"] == "done", job
    fit = owner.get(f"/api/learning/fits/{job['result']['fit_id']}").json()
    m = fit["metrics"]
    assert m["after"]["mae"] < 0.6 * m["before"]["mae"]
    assert m["cv"]["1"]["folds"] == 3 and m["cv"]["1"]["cv"]["mae"] < m["cv"]["1"]["baseline"]["mae"]
    assert "2" in m["cv"]  # every formula tier is cross-validated, tier 2 only suggested
    assert m["sigma"]["proposed"] and 0.05 < m["sigma"]["proposed"] < 0.4
    rep = fit["report"]
    assert len(rep["points"]) == 120 and rep["histogram"] and rep["by_feature"]
    assert {b["feature"] for b in rep["by_feature"]} >= {"total_weight", "stairs", "team"}
    # nothing changes before adoption
    before = owner.get("/api/formulas?key=time").json()
    owner.post(
        f"/api/learning/fits/{fit['id']}/adopt", json={"parameters": True, "staff": True, "sigma": True}
    )
    with session_scope(RlsContext(tenant_id=tid)) as db:
        f = load_active(db, tid, "time", 1)
        assert f.formula.tenant_id == tid and f.version.source == "fit"
        for k in ("a0", "t_fixed"):
            assert f.version.parameters[k]["value"] == fit["parameters"][k]["new"]
        from app.settings.service import SettingsResolver

        res = SettingsResolver(db, tid)
        assert float(res.get("time.error_sigma")) == m["sigma"]["proposed"]
        sid, sv = next(iter(fit["staff_factors"].items()))
        assert float(res.get("staff.carry_speed_factor", ("staff", uuid.UUID(sid)))) == sv["new"]
    assert before  # the formula list was readable before
    # a decided fit cannot be adopted twice
    owner.post(f"/api/learning/fits/{fit['id']}/adopt", expect=409, json={})


def test_too_few_measurements_is_explained(owner, field_tenant):
    with session_scope(RlsContext(tenant_id=field_tenant[0])) as db:
        db.execute(delete(Measurement).where(Measurement.tenant_id == field_tenant[0]))
    job = owner.post("/api/learning/fits", expect=201, json={"sync": True}).json()
    assert job["status"] == "failed"
    assert "Zu wenige Messungen" in (job["error"] or "")


def test_outlier_can_be_excluded(owner, field_tenant):
    owner.post("/api/learning/synthetic", json={"n": 40, "seed": 9})
    items = owner.get("/api/measurements?source=synthetic").json()["items"]
    mid = items[0]["id"]
    m = owner.patch(
        f"/api/measurements/{mid}", json={"excluded": True, "exclude_reason": "Messfehler"}
    ).json()
    assert m["excluded"] and m["exclude_reason"] == "Messfehler"
    with session_scope(RlsContext(tenant_id=field_tenant[0])) as db:
        samples = prepare_samples(db, field_tenant[0], Estimator(db, field_tenant[0]))
    s = next(x for x in samples if x.measurement_id == mid)
    assert not s.used and s.exclude_reason == "Messfehler"


def test_synthetic_data_only_for_demo_tenants(new_tenant):
    _t, other = new_tenant()
    other.post("/api/learning/synthetic", expect=403, json={"n": 10})


# ---------------------------------------------------------------- driver app


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (90, 140, 90)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def planned(field_tenant, make_client_module):
    """Active plan; a driver account for a member of the first tour (PIN login)."""
    from app.demo.generator import DEMO_PASSWORD

    tid, owner_email, slug = field_tenant
    api = make_client_module()
    api.login(owner_email, DEMO_PASSWORD)
    api.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 4})
    p = api.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 4, "sync": True, "pack": False}
    ).json()
    api.post(f"/api/plans/{p['id']}/activate")
    plan = api.get(f"/api/plans/{p['id']}").json()
    tour = plan["tours"][0]
    staff_id = tour["members"][0]["id"]
    with session_scope(RlsContext(tenant_id=tid)) as db:
        from app.models.core import User

        existing = db.scalar(
            select(User).where(User.tenant_id == tid, User.staff_member_id == uuid.UUID(staff_id))
        )
        user_id = str(existing.id) if existing else None
        other_staff = db.scalar(
            select(StaffMember.id).where(
                StaffMember.tenant_id == tid,
                StaffMember.id.notin_([uuid.UUID(m["id"]) for m in tour["members"]]),
            )
        )
    if user_id is None:
        user_id = api.post(
            "/api/users",
            expect=201,
            json={"name": "Fahrer Test", "role": "driver", "staff_member_id": staff_id},
        ).json()["id"]
    pin = f"{uuid.uuid4().int % 9000 + 1000}{uuid.uuid4().int % 90 + 10}"
    api.post(f"/api/users/{user_id}/pin", json={"pin": pin})
    other_id = api.post(
        "/api/users",
        expect=201,
        json={"name": "Fremder Fahrer", "role": "driver", "staff_member_id": str(other_staff)},
    ).json()["id"]
    other_pin = f"{uuid.uuid4().int % 9000 + 1000}{uuid.uuid4().int % 90 + 10}"
    api.post(f"/api/users/{other_id}/pin", json={"pin": other_pin})
    return {
        "owner": api,
        "plan": plan,
        "tour": tour,
        "slug": slug,
        "pin": pin,
        "other_pin": other_pin,
        "tid": tid,
    }


@pytest.fixture(scope="module")
def make_client_module(app):
    from fastapi.testclient import TestClient

    from tests.conftest import Api

    clients = []

    def _make():
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return Api(c)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _driver(make_client, planned, pin_key="pin"):
    api = make_client()
    api.post("/api/auth/driver/pin", json={"tenant": planned["slug"], "pin": planned[pin_key]})
    return api


def _ev(tour, kind, at, stop=None, **kw):
    return {
        "client_id": uuid.uuid4().hex,
        "tour_id": tour,
        "stop_id": stop,
        "kind": kind,
        "at": at.isoformat(),
        **kw,
    }


def test_driver_day_package(make_client, planned):
    drv = _driver(make_client, planned)
    me = drv.get("/api/driver/me").json()
    assert me["settings"]["require_pickup_photo"] is True
    day = drv.get(f"/api/driver/day?on={planned['tour']['date']}").json()
    tours = day["tours"]
    assert any(t["id"] == planned["tour"]["id"] for t in tours)
    t = next(t for t in tours if t["id"] == planned["tour"]["id"])
    s = t["stops"][0]
    assert (
        s["nav"]["google"].startswith("https://www.google.com/maps/dir/")
        and "maps.apple.com" in s["nav"]["apple"]
    )
    assert s["plants"] and s["customer"]["name"] and s["address"]["city"]
    assert t["members"] and t["vehicle"]["name"]
    assert "load" in t and t["load"]["tour"]["id"] == t["id"]
    # the driver only sees own tours
    member_ids = {m["id"] for x in tours for m in x["members"]}
    assert all(any(m["id"] == me["staff_id"] for m in x["members"]) for x in tours) and member_ids


def test_driver_events_photo_breaks_measurement(make_client, planned):
    drv = _driver(make_client, planned)
    tour = planned["tour"]
    stop = tour["stops"][0]
    t0 = datetime.now(UTC) - timedelta(hours=3)
    evs = [
        _ev(tour["id"], "shift_start", t0),
        _ev(tour["id"], "depart", t0 + timedelta(minutes=5)),
        _ev(tour["id"], "arrive", t0 + timedelta(minutes=35), stop["id"]),
        _ev(tour["id"], "carry_start", t0 + timedelta(minutes=40), stop["id"]),
        _ev(tour["id"], "break_start", t0 + timedelta(minutes=50)),
        _ev(tour["id"], "break_end", t0 + timedelta(minutes=60)),
    ]
    res = drv.post("/api/driver/events", json={"events": evs}).json()
    assert res["ok"] == 6 and res["failed"] == 0
    # loading without the mandatory photo is refused
    loaded = _ev(
        tour["id"],
        "loaded",
        t0 + timedelta(minutes=80),
        stop["id"],
        photo_client_id="foto-" + uuid.uuid4().hex[:8],
    )
    res = drv.post("/api/driver/events", json={"events": [loaded]}).json()
    assert res["results"][0]["error"] == "errors.event_photo_required"
    # photo first (offline queue order), then the event again
    files = {"file": ("nachweis.jpg", _jpeg(), "image/jpeg")}
    ph = drv.post(
        "/api/driver/photos",
        expect=201,
        files=files,
        data={"client_id": loaded["photo_client_id"], "stop_id": stop["id"]},
    ).json()
    again = drv.post(
        "/api/driver/photos",
        expect=201,
        files=files,
        data={"client_id": loaded["photo_client_id"], "stop_id": stop["id"]},
    ).json()
    assert ph["id"] == again["id"] and ph["kind"] == "pickup_proof"
    leave = _ev(tour["id"], "leave", t0 + timedelta(minutes=85), stop["id"])
    res = drv.post("/api/driver/events", json={"events": [loaded, leave]}).json()
    assert res["ok"] == 2
    # resent after a lost answer: no duplicates
    res = drv.post("/api/driver/events", json={"events": evs + [loaded, leave]}).json()
    assert res["ok"] == 8
    with session_scope(RlsContext(tenant_id=planned["tid"])) as db:
        m = db.scalar(select(Measurement).where(Measurement.stop_id == uuid.UUID(stop["id"])))
        assert m is not None and m.source == "app"
        assert m.duration_min == pytest.approx(80 - 35 - 10, abs=0.01)  # break subtracted
        assert m.fixed_min == pytest.approx(5, abs=0.01)
        assert m.carry_min == pytest.approx(30, abs=0.01)
        assert m.drive_min == pytest.approx(30, abs=0.01)
        assert m.break_min == pytest.approx(10, abs=0.01)
        st = db.get(TourStop, uuid.UUID(stop["id"]))
        assert st.status == "done"
        assert db.get(Tour, uuid.UUID(tour["id"])).status == "in_progress"
        from app.models.field import TourEvent

        n = len(list(db.scalars(select(TourEvent).where(TourEvent.tour_id == uuid.UUID(tour["id"])))))
        assert n == 8


def test_other_driver_cannot_post_for_foreign_tour(make_client, planned):
    other = _driver(make_client, planned, "other_pin")
    ev = _ev(planned["tour"]["id"], "arrive", datetime.now(UTC), planned["tour"]["stops"][-1]["id"])
    res = other.post("/api/driver/events", json={"events": [ev]}).json()
    assert res["results"][0]["error"] == "errors.not_found"
    day = other.get(f"/api/driver/day?on={planned['tour']['date']}").json()
    assert all(t["id"] != planned["tour"]["id"] for t in day["tours"])


def test_bad_events_do_not_block_the_queue(make_client, planned):
    drv = _driver(make_client, planned)
    tour = planned["tour"]
    good = _ev(tour["id"], "break_start", datetime.now(UTC) - timedelta(minutes=2))
    bad = [
        _ev(tour["id"], "teleport", datetime.now(UTC)),
        _ev(tour["id"], "arrive", datetime.now(UTC)),  # no stop
        _ev(tour["id"], "break_end", datetime.now(UTC) + timedelta(days=2)),  # future
    ]
    res = drv.post("/api/driver/events", json={"events": [*bad, good]}).json()
    assert res["ok"] == 1 and res["failed"] == 3
    errors = {r["error"] for r in res["results"] if not r["ok"]}
    assert errors == {"errors.event_kind", "errors.event_stop", "errors.event_time"}


def test_deviation_report_applied_updates_plant(make_client, planned):
    drv = _driver(make_client, planned)
    tour = planned["tour"]
    stop = tour["stops"][-1]
    day = drv.get(f"/api/driver/day?on={tour['date']}").json()
    plant = next(t for t in day["tours"] if t["id"] == tour["id"])["stops"][-1]["plants"][0]
    body = {
        "client_id": uuid.uuid4().hex,
        "tour_id": tour["id"],
        "stop_id": stop["id"],
        "plant_id": plant["id"],
        "kind": "plant_heavier",
        "note": "deutlich schwerer",
        "values": {"weight_kg": 123.0, "evil": "x"},
    }
    d = drv.post("/api/driver/deviations", expect=201, json=body).json()
    assert d["values"] == {"weight_kg": 123.0} and d["status"] == "open"
    assert drv.post("/api/driver/deviations", expect=201, json=body).json()["id"] == d["id"]  # idempotent
    owner = planned["owner"]
    assert any(x["id"] == d["id"] for x in owner.get("/api/deviations").json())
    res = owner.post(f"/api/deviations/{d['id']}/decide", json={"action": "apply"}).json()
    assert res["status"] == "applied" and res["changes"]["weight_measured_kg"]["new"] == 123.0
    with session_scope(RlsContext(tenant_id=planned["tid"])) as db:
        assert db.get(Plant, uuid.UUID(plant["id"])).weight_measured_kg == 123.0
    owner.post(f"/api/deviations/{d['id']}/decide", expect=409, json={"action": "dismiss"})


def test_qr_labels_and_scan(make_client, planned):
    owner = planned["owner"]
    tour = planned["tour"]
    owner.get(f"/api/tours/{tour['id']}/labels.pdf", expect=409)  # module off
    owner.put("/api/settings", json={"scope": "tenant", "key": "driver.qr_module", "value": True})
    r = owner.get(f"/api/tours/{tour['id']}/labels.pdf")
    assert r.content[:4] == b"%PDF" and r.headers["content-type"] == "application/pdf"
    owner.post(f"/api/tours/{tour['id']}/load-plan")
    lp = owner.get(f"/api/tours/{tour['id']}/load-plan").json()["plan"]
    if not lp["placements"]:
        pytest.skip("no placement in this tour")
    place = lp["placements"][0]
    drv = _driver(make_client, planned)
    assert drv.get("/api/driver/me").json()["settings"]["qr_module"] is True
    ev = _ev(
        tour["id"],
        "qr_scan",
        datetime.now(UTC) - timedelta(minutes=1),
        place.get("stop_id")
        or next(s["id"] for s in tour["stops"] if s["position"] == place["stop_position"]),
        plant_id=place["plant_id"],
    )
    assert drv.post("/api/driver/events", json={"events": [ev]}).json()["ok"] == 1
    after = owner.get(f"/api/tours/{tour['id']}/load-plan").json()["plan"]
    assert next(p for p in after["placements"] if p["plant_id"] == place["plant_id"])["loaded_at"]


def test_experiment_mode_marks_stops_with_bigger_team(owner, field_tenant):
    owner.put("/api/settings", json={"scope": "tenant", "key": "learning.experiment_share", "value": 0.5})
    try:
        p = owner.post(
            "/api/plans", expect=201, json={"start_date": str(START), "days": 3, "sync": True, "pack": False}
        ).json()
        plan = owner.get(f"/api/plans/{p['id']}").json()
        stops = [s for t in plan["tours"] for s in t["stops"]]
        exp = [s for s in stops if s.get("experiment")]
        assert exp, "no experiment stop"
        with session_scope(RlsContext(tenant_id=field_tenant[0])) as db:
            for s in exp:
                st = db.get(TourStop, uuid.UUID(s["id"]))
                tour = db.get(Tour, st.tour_id)
                from app.models.orders import PickupOrder

                need = (db.get(PickupOrder, st.order_id).estimate or {}).get("team_size") or 1
                # never below the required team (safety), but bigger than needed
                assert len(tour.member_ids) > need
    finally:
        owner.put("/api/settings", json={"scope": "tenant", "key": "learning.experiment_share", "value": 0.0})
