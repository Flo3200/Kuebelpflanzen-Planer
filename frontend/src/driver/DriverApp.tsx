// Driver PWA: own tours of the day, works offline (IndexedDB queue), large buttons, high contrast.
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { LoadPlanView } from "../components/loadplan/LoadPlanView";
import { t } from "../i18n";
import { idb } from "./idb";
import {
  clock,
  hm,
  localDate,
  onBreak,
  stopProgress,
  tourEvents,
  useDay,
  useDriverMe,
  type DriverMe,
  type DStop,
  type DTour,
} from "./data";
import { addDeviation, addEvent, addPhoto, discardFailed, flush, queuedItems, startSync, useSyncStatus } from "./sync";
import "./driver.css";

type DayState = ReturnType<typeof useDay>;
const Ctx = createContext<{ me: DriverMe; day: DayState } | null>(null);

function useDriver() {
  const c = useContext(Ctx);
  if (!c) throw new Error("driver context missing");
  return c;
}

function useTour(): DTour | undefined {
  const { tourId } = useParams();
  const { day } = useDriver();
  return day.day?.tours.find((x) => x.id === tourId);
}

// ----------------------------------------------------------------------------- shell

export default function DriverApp() {
  const [contrast, setContrast] = useState<string>(() => {
    try {
      return localStorage.getItem("kp-driver-contrast") ?? "dark";
    } catch {
      return "dark";
    }
  });
  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/fahrer" }).catch(() => undefined);
    const link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
    const old = link?.getAttribute("href");
    link?.setAttribute("href", "/fahrer.webmanifest");
    document.title = t("driverapp.title");
    return () => {
      if (link && old) link.setAttribute("href", old);
    };
  }, []);
  const toggle = () => {
    const next = contrast === "dark" ? "light" : "dark";
    setContrast(next);
    try {
      localStorage.setItem("kp-driver-contrast", next);
    } catch {
      /* private mode */
    }
  };
  return (
    <div className="driver-theme driver-app" data-contrast={contrast}>
      <Routes>
        <Route path="login/:code" element={<LinkLogin />} />
        <Route path="*" element={<Gate onContrast={toggle} />} />
      </Routes>
    </div>
  );
}

function Gate({ onContrast }: { onContrast: () => void }) {
  const { me, reload } = useDriverMe();
  if (me === undefined) return <div className="d-center">{t("common.loading")}</div>;
  if (me === null) return <PinLogin onDone={reload} />;
  return <Shell me={me} onContrast={onContrast} />;
}

function Shell({ me, onContrast }: { me: DriverMe; onContrast: () => void }) {
  const day = useDay();
  useEffect(() => startSync(), []);
  return (
    <Ctx.Provider value={{ me, day }}>
      <Header onContrast={onContrast} />
      <main className="d-main">
        {day.error && <div className="d-alert error">{day.error}</div>}
        <Routes>
          <Route index element={<Home />} />
          <Route path="tour/:tourId" element={<TourScreen />} />
          <Route path="tour/:tourId/laden" element={<LoadScreen />} />
          <Route path="tour/:tourId/stopp/:stopId" element={<StopScreen />} />
          <Route path="tour/:tourId/stopp/:stopId/meldung" element={<ReportScreen />} />
          <Route path="*" element={<Navigate to="/fahrer" replace />} />
        </Routes>
      </main>
    </Ctx.Provider>
  );
}

function Header({ onContrast }: { onContrast: () => void }) {
  const { me } = useDriver();
  const s = useSyncStatus();
  const [failed, setFailed] = useState<{ client_id: string; kind: string; error?: string }[]>([]);
  const [open, setOpen] = useState(false);
  const logout = async () => {
    const pending = (await queuedItems()).length;
    if (pending && !window.confirm(t("driverapp.logout_pending", { n: pending }))) return;
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* offline: the local data is removed anyway */
    }
    await idb.clear("kv");
    window.location.href = "/fahrer";
  };
  const showFailed = async () => {
    setFailed((await queuedItems()).filter((i) => i.error).map((i) => ({ client_id: i.client_id, kind: i.kind, error: i.error })));
    setOpen(!open);
  };
  return (
    <header className="d-header">
      <Link to="/fahrer" className="d-brand">
        {me.name}
      </Link>
      <div className="d-header-actions">
        <button className={`d-sync ${s.online ? "on" : "off"}`} onClick={() => void flush()} title={s.lastError ?? ""}>
          {s.online ? t("driverapp.online") : t("driverapp.offline")}
          {s.pending > 0 && ` · ${t("driverapp.pending", { n: s.pending })}`}
          {s.syncing && " …"}
        </button>
        {s.failed > 0 && (
          <button className="d-sync off" onClick={showFailed}>
            {t("driverapp.failed", { n: s.failed })}
          </button>
        )}
        <button className="d-icon" onClick={onContrast} aria-label={t("driverapp.contrast")}>
          ◐
        </button>
        <button className="d-icon" onClick={logout} aria-label={t("driverapp.logout")}>
          ⎋
        </button>
      </div>
      {open && (
        <div className="d-failed">
          <p>{t("driverapp.failed_text")}</p>
          {failed.map((f) => (
            <div key={f.client_id} className="d-row">
              <span>
                {t(`driverapp.kinds.${f.kind}`)}: {t(f.error ?? "errors.http")}
              </span>
              <button className="d-btn small" onClick={async () => (await discardFailed(f.client_id), showFailed())}>
                {t("driverapp.discard")}
              </button>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}

// ----------------------------------------------------------------------------- login

function PinLogin({ onDone }: { onDone: () => void }) {
  const [tenant, setTenant] = useState(() => {
    try {
      return localStorage.getItem("kp-driver-tenant") ?? "";
    } catch {
      return "";
    }
  });
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/driver/pin", { tenant: tenant.trim(), pin: pin.trim() });
      try {
        localStorage.setItem("kp-driver-tenant", tenant.trim());
      } catch {
        /* ignore */
      }
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("driverapp.offline_login"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="d-login" onSubmit={submit}>
      <h1>{t("driverapp.title")}</h1>
      <p>{t("driverapp.login_text")}</p>
      <label>
        {t("driverapp.tenant_code")}
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} autoCapitalize="none" autoComplete="organization" required />
      </label>
      <label>
        {t("driverapp.pin")}
        <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} inputMode="numeric" autoComplete="one-time-code" maxLength={8} required />
      </label>
      {error && <div className="d-alert error">{error}</div>}
      <button className="d-btn primary big" disabled={busy}>
        {busy ? t("common.loading") : t("driverapp.login")}
      </button>
    </form>
  );
}

function LinkLogin() {
  const { code } = useParams();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .post(`/api/auth/link/${code}`)
      .then(() => nav("/fahrer", { replace: true }))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [code, nav]);
  return <div className="d-center">{error ? <div className="d-alert error">{error}</div> : t("driverapp.logging_in")}</div>;
}

// ----------------------------------------------------------------------------- day

function Home() {
  const { day } = useDriver();
  const today = localDate();
  const dates = useMemo(() => Array.from(new Set((day.day?.tours ?? []).map((x) => x.date))).sort(), [day.day]);
  const [sel, setSel] = useState<string | null>(null);
  const current = sel ?? (dates.includes(today) ? today : dates[0] ?? today);
  const tours = (day.day?.tours ?? []).filter((x) => x.date === current);
  return (
    <div className="d-stack">
      {day.offline && <div className="d-alert warn">{t("driverapp.offline_data", { at: day.day ? clock(day.day.generated_at) : "–" })}</div>}
      {dates.length > 1 && (
        <div className="d-tabs">
          {dates.map((d) => (
            <button key={d} className={d === current ? "active" : ""} onClick={() => setSel(d)}>
              {d === today ? t("driverapp.today") : new Date(d).toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "numeric" })}
            </button>
          ))}
        </div>
      )}
      {!day.day && <div className="d-center">{t("common.loading")}</div>}
      {day.day && tours.length === 0 && <div className="d-empty">{t("driverapp.no_tours")}</div>}
      {tours.map((tr) => {
        const evs = tourEvents(tr, day.queued);
        const done = tr.stops.filter((s) => stopProgress(evs, s.id).leave).length;
        return (
          <Link key={tr.id} to={`tour/${tr.id}`} className="d-card link" style={{ borderLeftColor: tr.color }}>
            <div className="d-card-title">
              {tr.vehicle.name}
              {tr.trailer ? ` + ${tr.trailer.name}` : ""}
              {tr.trip_no > 1 && ` · ${t("driverapp.trip", { n: tr.trip_no })}`}
            </div>
            <div className="d-muted">
              {hm(tr.start_min)}–{hm(tr.end_min)} · {t("driverapp.stops_done", { done, n: tr.stops.length })} · {Math.round(tr.distance_km)} km
            </div>
            <div className="d-muted">{tr.members.map((m) => m.name).join(", ")}</div>
          </Link>
        );
      })}
      <button className="d-btn" onClick={() => void day.reload()}>
        {t("driverapp.refresh")}
      </button>
    </div>
  );
}

// ----------------------------------------------------------------------------- tour

function BreakButton({ tour }: { tour: DTour }) {
  const { day } = useDriver();
  const evs = tourEvents(tour, day.queued);
  const paused = onBreak(evs);
  return (
    <button className={`d-btn ${paused ? "warn" : ""}`} onClick={() => void addEvent({ tour_id: tour.id, kind: paused ? "break_end" : "break_start" })}>
      {paused ? t("driverapp.break_end") : t("driverapp.break_start")}
    </button>
  );
}

function TourScreen() {
  const tour = useTour();
  const { day } = useDriver();
  if (!tour) return <Missing />;
  const evs = tourEvents(tour, day.queued);
  const has = (k: string) => evs.some((e) => e.kind === k);
  const nextStop = tour.stops.find((s) => !stopProgress(evs, s.id).leave);
  return (
    <div className="d-stack">
      <Link to="/fahrer" className="d-back">
        ← {t("driverapp.back_day")}
      </Link>
      <div className="d-card" style={{ borderLeftColor: tour.color }}>
        <div className="d-card-title">
          {tour.vehicle.name} {tour.vehicle.plate && <span className="d-muted">({tour.vehicle.plate})</span>}
        </div>
        {tour.trailer && <div>+ {tour.trailer.name}</div>}
        <div className="d-muted">
          {hm(tour.start_min)}–{hm(tour.end_min)}
          {tour.breaks.length > 0 && ` · ${t("driverapp.break_plan", { at: tour.breaks.map((b) => hm(b.start)).join(", ") })}`}
        </div>
        <div className="d-team">
          {tour.members.map((m) => (
            <span key={m.id}>
              {m.name}
              {m.driver && ` (${t("driverapp.driver")})`}
              {m.phone && (
                <a href={`tel:${m.phone}`} className="d-link">
                  {" "}☎
                </a>
              )}
            </span>
          ))}
        </div>
      </div>
      <div className="d-grid2">
        {!has("shift_start") && (
          <button className="d-btn primary big" onClick={() => void addEvent({ tour_id: tour.id, kind: "shift_start" })}>
            {t("driverapp.kinds.shift_start")}
          </button>
        )}
        <button className="d-btn big" onClick={() => void addEvent({ tour_id: tour.id, kind: "depart" })}>
          {t("driverapp.kinds.depart")}
        </button>
        <BreakButton tour={tour} />
        <Link className="d-btn" to="laden">
          {t("driverapp.load_plan")}
        </Link>
      </div>
      <h2 className="d-h2">{t("driverapp.stops")}</h2>
      {tour.stops.map((s) => {
        const p = stopProgress(evs, s.id);
        const state = p.leave ? "done" : p.arrive ? "active" : "";
        return (
          <Link key={s.id} to={`stopp/${s.id}`} className={`d-card link stop ${state} ${nextStop?.id === s.id ? "next" : ""}`}>
            <div className="d-card-title">
              {s.position}. {s.customer?.name}
            </div>
            <div className="d-muted">
              {s.address?.street}, {s.address?.city}
            </div>
            <div className="d-muted">
              {hm(s.arrival_min)} · {s.plants.length} {t("driverapp.plants_short")} · {t("driverapp.team_n", { n: s.team_size })}
              {p.leave ? ` · ✓ ${clock(p.leave)}` : p.arrive ? ` · ${t("driverapp.on_site_since", { at: clock(p.arrive) })}` : ""}
            </div>
          </Link>
        );
      })}
      <div className="d-grid2">
        <button className="d-btn big" onClick={() => void addEvent({ tour_id: tour.id, kind: "unload" })}>
          {t("driverapp.kinds.unload")}
        </button>
        <button className="d-btn big" onClick={() => window.confirm(t("driverapp.end_confirm")) && void addEvent({ tour_id: tour.id, kind: "shift_end" })}>
          {t("driverapp.kinds.shift_end")}
        </button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- stop

function PhotoButton({ label, onPhoto, primary }: { label: string; onPhoto: (f: File) => void; primary?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <button className={`d-btn big ${primary ? "primary" : ""}`} onClick={() => ref.current?.click()}>
        📷 {label}
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPhoto(f);
          e.target.value = "";
        }}
      />
    </>
  );
}

function StopScreen() {
  const tour = useTour();
  const { stopId } = useParams();
  const { me, day } = useDriver();
  const nav = useNavigate();
  const stop = tour?.stops.find((s) => s.id === stopId);
  if (!tour || !stop) return <Missing />;
  const evs = tourEvents(tour, day.queued);
  const p = stopProgress(evs, stop.id);
  const plantDone = new Set(evs.filter((e) => e.stop_id === stop.id && e.kind === "plant_done").map((e) => e.plant_id));
  const next = !p.arrive ? "arrive" : !p.carry_start ? "carry_start" : !p.loaded ? "loaded" : !p.leave ? "leave" : null;
  const ev = (kind: string, extra: Record<string, unknown> = {}) => addEvent({ tour_id: tour.id, stop_id: stop.id, kind, ...extra });
  const loadedWithPhoto = async (f: File) => {
    const photo_client_id = await addPhoto(f, { stop_id: stop.id, kind: "pickup_proof" });
    await ev("loaded", { photo_client_id });
  };
  const leave = async () => {
    await ev("leave");
    const idx = tour.stops.findIndex((s) => s.id === stop.id);
    const following = tour.stops[idx + 1];
    nav(following ? `/fahrer/tour/${tour.id}/stopp/${following.id}` : `/fahrer/tour/${tour.id}`);
  };
  const a = stop.address;
  return (
    <div className="d-stack">
      <Link to={`/fahrer/tour/${tour.id}`} className="d-back">
        ← {t("driverapp.back_tour")}
      </Link>
      <div className="d-card">
        <div className="d-card-title">
          {stop.position}. {stop.customer?.name}
        </div>
        {a && (
          <div>
            {a.street}, {a.postal_code} {a.city}
          </div>
        )}
        <div className="d-grid2">
          {stop.nav.google && (
            <a className="d-btn" href={stop.nav.google} target="_blank" rel="noreferrer">
              {t("driverapp.nav_google")}
            </a>
          )}
          {stop.nav.apple && (
            <a className="d-btn" href={stop.nav.apple} target="_blank" rel="noreferrer">
              {t("driverapp.nav_apple")}
            </a>
          )}
          {stop.customer?.phone && (
            <a className="d-btn" href={`tel:${stop.customer.phone}`}>
              ☎ {t("driverapp.call")}
            </a>
          )}
        </div>
        <Notes stop={stop} />
      </div>

      <div className="d-steps">
        {(["arrive", "carry_start", "loaded", "leave"] as const).map((k, i) => {
          const done = p[k];
          const isNext = next === k;
          if (done)
            return (
              <div key={k} className="d-step done">
                ✓ {i + 1}. {t(`driverapp.kinds.${k}`)} · {clock(done)}
              </div>
            );
          if (!isNext)
            return (
              <div key={k} className="d-step">
                {i + 1}. {t(`driverapp.kinds.${k}`)}
              </div>
            );
          if (k === "loaded")
            return me.settings.require_pickup_photo ? (
              <PhotoButton key={k} primary label={`${i + 1}. ${t("driverapp.loaded_photo")}`} onPhoto={(f) => void loadedWithPhoto(f)} />
            ) : (
              <div key={k} className="d-grid2">
                <button className="d-btn primary big" onClick={() => void ev("loaded")}>
                  {i + 1}. {t("driverapp.kinds.loaded")}
                </button>
                <PhotoButton label={t("driverapp.with_photo")} onPhoto={(f) => void loadedWithPhoto(f)} />
              </div>
            );
          return (
            <button key={k} className="d-btn primary big" onClick={() => void (k === "leave" ? leave() : ev(k))}>
              {i + 1}. {t(`driverapp.kinds.${k}`)}
            </button>
          );
        })}
        {stop.experiment && <div className="d-alert warn">{t("driverapp.experiment")}</div>}
      </div>

      <div className="d-grid2">
        <BreakButton tour={tour} />
        <Link className="d-btn" to={`/fahrer/tour/${tour.id}/laden`}>
          {t("driverapp.load_plan")}
        </Link>
        <Link className="d-btn warn" to="meldung">
          {t("driverapp.report")}
        </Link>
      </div>

      <h2 className="d-h2">
        {t("driverapp.plants")} ({stop.plants.length}) · {t("driverapp.team_n", { n: stop.team_size })}
        {stop.equipment.length > 0 && ` · ${stop.equipment.join(", ")}`}
      </h2>
      {stop.plants.map((pl) => (
        <div key={pl.id} className="d-card plant">
          <div className="d-plant-head">
            <span className="d-num">#{pl.number}</span>
            <div>
              <div className="d-card-title">{pl.name || pl.label}</div>
              <div className="d-muted">
                {t("driverapp.dims", { pot: pl.pot_d, h: pl.height, crown: pl.crown_w })}
                {pl.weight != null && ` · ${Math.round(pl.weight)} kg`}
                {pl.crew && ` · ${t("driverapp.crew_n", { n: pl.crew })}`}
                {pl.equipment && ` · ${pl.equipment}`}
              </div>
              <div className="d-flags">
                {pl.sensitive && <span>{t("driverapp.sensitive")}</span>}
                {pl.must_secure && <span>{t("driverapp.secure")}</span>}
                {pl.can_tilt === false && <span>{t("driverapp.no_tilt")}</span>}
              </div>
              {pl.notes && <div>{pl.notes}</div>}
            </div>
          </div>
          {pl.photos.length > 0 && (
            <div className="d-photos">
              {pl.photos.slice(0, 4).map((ph) => (
                <a key={ph.id} href={ph.url} target="_blank" rel="noreferrer">
                  <img src={ph.url} alt="" loading="lazy" />
                </a>
              ))}
            </div>
          )}
          {me.settings.per_plant_events && p.carry_start && !p.loaded && (
            <button className={`d-btn ${plantDone.has(pl.id) ? "" : "primary"}`} disabled={plantDone.has(pl.id)} onClick={() => void ev("plant_done", { plant_id: pl.id })}>
              {plantDone.has(pl.id) ? `✓ ${t("driverapp.plant_done")}` : t("driverapp.kinds.plant_done")}
            </button>
          )}
        </div>
      ))}

      {stop.paths.map((path) => (
        <div key={path.id} className="d-card">
          <div className="d-card-title">
            {t("driverapp.path")}: {path.name} · {Math.round(path.length_m)} m
          </div>
          {path.notes && <div>{path.notes}</div>}
          <ol className="d-segments">
            {path.segments.map((sg, i) => (
              <li key={i}>
                {t(`driverapp.segments.${sg.kind}`)} · {Math.round(sg.length_m)} m
                {sg.steps > 0 && ` · ${t("driverapp.steps_n", { n: sg.steps })}`}
                {sg.min_width_cm && ` · ${t("driverapp.width", { cm: sg.min_width_cm })}`}
                {sg.elevator && ` · ${t("driverapp.elevator")}`}
                {sg.notes && ` – ${sg.notes}`}
              </li>
            ))}
          </ol>
          {path.photos.length > 0 && (
            <div className="d-photos">
              {path.photos.slice(0, 6).map((ph) => (
                <a key={ph.id} href={ph.url} target="_blank" rel="noreferrer">
                  <img src={ph.url} alt="" loading="lazy" />
                </a>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Notes({ stop }: { stop: DStop }) {
  const a = stop.address;
  const items = [
    [t("driverapp.note_bell"), a?.bell_notes],
    [t("driverapp.note_parking"), a?.parking_notes],
    [t("driverapp.note_access"), a?.access_notes],
    [t("driverapp.note_customer"), stop.customer?.notes],
    [t("driverapp.note_order"), stop.order?.notes],
  ].filter(([, v]) => v);
  if (!items.length) return null;
  return (
    <dl className="d-notes">
      {items.map(([k, v]) => (
        <div key={k as string}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// ----------------------------------------------------------------------------- load plan + QR

function LoadScreen() {
  const tour = useTour();
  const { me } = useDriver();
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (!tour) return <Missing />;
  const confirm = async (plantId: string) => {
    const place = tour.load.plan?.placements.find((p) => p.plant_id === plantId);
    if (!place) {
      setMsg(t("driverapp.qr_unknown"));
      return;
    }
    const stop = tour.stops.find((s) => s.position === place.stop_position);
    await addEvent({ tour_id: tour.id, stop_id: stop?.id, kind: "qr_scan", plant_id: plantId });
    setMsg(t("driverapp.qr_ok", { label: place.label, where: place.instruction }));
  };
  const byNumber = (n: string) => {
    const place = tour.load.plan?.placements.find((p) => String(p.number) === n.replace("#", "").trim());
    if (place) void confirm(place.plant_id);
    else setMsg(t("driverapp.qr_unknown"));
  };
  return (
    <div className="d-stack">
      <Link to={`/fahrer/tour/${tour.id}`} className="d-back">
        ← {t("driverapp.back_tour")}
      </Link>
      {me.settings.qr_module && (
        <div className="d-card">
          <div className="d-grid2">
            <button className="d-btn primary big" onClick={() => setScanning(!scanning)}>
              {scanning ? t("driverapp.qr_stop") : t("driverapp.qr_scan")}
            </button>
            <NumberEntry onEnter={byNumber} />
          </div>
          {scanning && (
            <Scanner
              onCode={(code) => {
                setScanning(false);
                if (code.startsWith("KP1:")) void confirm(code.slice(4));
                else setMsg(t("driverapp.qr_unknown"));
              }}
            />
          )}
          {msg && <div className="d-alert">{msg}</div>}
        </div>
      )}
      <LoadPlanView tour={tour.load.tour} plan={tour.load.plan} compact />
    </div>
  );
}

function NumberEntry({ onEnter }: { onEnter: (n: string) => void }) {
  const [v, setV] = useState("");
  return (
    <form
      className="d-inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        onEnter(v);
        setV("");
      }}
    >
      <input value={v} onChange={(e) => setV(e.target.value)} inputMode="numeric" placeholder={t("driverapp.plant_number")} />
      <button className="d-btn">{t("driverapp.confirm")}</button>
    </form>
  );
}

type Detector = { detect: (v: HTMLVideoElement) => Promise<{ rawValue: string }[]> };

function Scanner({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const BD = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
    if (!BD || !navigator.mediaDevices?.getUserMedia) {
      setError(t("driverapp.qr_unsupported"));
      return;
    }
    let stream: MediaStream | null = null;
    let stop = false;
    const detector = new BD({ formats: ["qr_code"] });
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        while (!stop) {
          const codes = await detector.detect(video.current);
          if (codes.length) {
            onCode(codes[0].rawValue);
            return;
          }
          await new Promise((r) => setTimeout(r, 250));
        }
      } catch {
        setError(t("driverapp.qr_camera"));
      }
    })();
    return () => {
      stop = true;
      stream?.getTracks().forEach((tr) => tr.stop());
    };
  }, [onCode]);
  return error ? <div className="d-alert warn">{error}</div> : <video ref={video} className="d-video" muted playsInline />;
}

// ----------------------------------------------------------------------------- deviation report

const REPORT_KINDS = ["plant_heavier", "plant_bigger", "path_different", "customer_absent", "damage", "other"] as const;
const VALUE_FIELDS: Record<string, string[]> = {
  plant_heavier: ["weight_kg"],
  plant_bigger: ["height_cm", "crown_width_cm", "pot_diameter_cm"],
  path_different: ["path_length_m", "steps", "min_width_cm"],
};

function ReportScreen() {
  const tour = useTour();
  const { stopId } = useParams();
  const nav = useNavigate();
  const stop = tour?.stops.find((s) => s.id === stopId);
  const [kind, setKind] = useState<string | null>(null);
  const [plantId, setPlantId] = useState<string>("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  if (!tour || !stop) return <Missing />;
  const needsPlant = kind === "plant_heavier" || kind === "plant_bigger";
  const needsPhoto = kind === "damage";
  const canSend = kind && (!needsPlant || plantId) && (!needsPhoto || photos.length > 0);
  const send = async () => {
    if (!kind) return;
    setBusy(true);
    const ids = [];
    for (const f of photos) ids.push(await addPhoto(f, { stop_id: stop.id, plant_id: plantId || null, kind: kind === "damage" ? "damage" : "other" }));
    const vals: Record<string, number> = {};
    for (const [k, v] of Object.entries(values)) if (v && !Number.isNaN(Number(v.replace(",", ".")))) vals[k] = Number(v.replace(",", "."));
    await addDeviation({ tour_id: tour.id, stop_id: stop.id, plant_id: plantId || null, kind, note: note || undefined, values: vals, photo_client_ids: ids });
    setBusy(false);
    nav(`/fahrer/tour/${tour.id}/stopp/${stop.id}`);
  };
  return (
    <div className="d-stack">
      <Link to={`/fahrer/tour/${tour.id}/stopp/${stop.id}`} className="d-back">
        ← {t("driverapp.back_stop")}
      </Link>
      <h2 className="d-h2">{t("driverapp.report_title", { name: stop.customer?.name ?? "" })}</h2>
      <div className="d-grid2">
        {REPORT_KINDS.map((k) => (
          <button key={k} className={`d-btn ${kind === k ? "primary" : ""}`} onClick={() => setKind(k)}>
            {t(`driverapp.deviation.${k}`)}
          </button>
        ))}
      </div>
      {kind && (
        <div className="d-card d-form">
          {(needsPlant || kind === "damage" || kind === "other") && (
            <label>
              {t("driverapp.plant")}
              <select value={plantId} onChange={(e) => setPlantId(e.target.value)}>
                <option value="">{needsPlant ? t("driverapp.choose") : t("driverapp.none")}</option>
                {stop.plants.map((pl) => (
                  <option key={pl.id} value={pl.id}>
                    #{pl.number} {pl.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(VALUE_FIELDS[kind] ?? []).map((f) => (
            <label key={f}>
              {t(`driverapp.values.${f}`)}
              <input inputMode="decimal" value={values[f] ?? ""} onChange={(e) => setValues({ ...values, [f]: e.target.value })} />
            </label>
          ))}
          <label>
            {t("driverapp.note")}
            <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <PhotoButton label={needsPhoto ? t("driverapp.photo_required") : t("driverapp.photo_optional")} onPhoto={(f) => setPhotos([...photos, f])} />
          {photos.length > 0 && <div className="d-muted">{t("driverapp.photos_n", { n: photos.length })}</div>}
          <button className="d-btn primary big" disabled={!canSend || busy} onClick={() => void send()}>
            {t("driverapp.send_report")}
          </button>
          <p className="d-muted">{t("driverapp.report_offline")}</p>
        </div>
      )}
    </div>
  );
}

function Missing(): ReactNode {
  return (
    <div className="d-stack">
      <div className="d-empty">{t("driverapp.not_found")}</div>
      <Link className="d-btn" to="/fahrer">
        {t("driverapp.back_day")}
      </Link>
    </div>
  );
}
