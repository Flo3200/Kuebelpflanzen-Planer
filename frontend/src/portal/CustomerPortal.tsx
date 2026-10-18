// Customer portal (/kunde): own orders, progress and appointment, offer, guided photos with consent,
// location on the map, spring return wish, online payment.
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { api, ApiError } from "../api/client";
import { Botanical } from "../components/Botanical";
import { Badge, Spinner, useToast } from "../components/ui";
import { fmtDate, fmtMoney, t } from "../i18n";
import "./portal.css";

interface Me {
  customer: { id: string; name: string; email: string | null; phone: string | null };
  tenant: { name: string; phone: string | null; email: string | null; street: string | null; postal_code: string | null; city: string | null };
  consent: { given: boolean; at: string | null; text: string };
  payments: "off" | "test" | "stripe";
}

const PLANT_KINDS = ["plant_front", "plant_side", "plant_top", "pot"];
const PATH_KINDS = ["path_start", "path_segment", "path_end"];

export default function CustomerPortal() {
  useEffect(() => {
    document.title = t("portal.title");
  }, []);
  return (
    <div className="portal">
      <Routes>
        <Route path="login/:code" element={<LinkLogin />} />
        <Route path="*" element={<Gate />} />
      </Routes>
    </div>
  );
}

function LinkLogin() {
  const { code } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .post(`/api/auth/customer/${code}`)
      .then(() => {
        qc.invalidateQueries();
        nav("/kunde", { replace: true });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [code, nav, qc]);
  return (
    <div className="portal-center">
      {error ? (
        <div className="portal-card">
          <h1>{t("portal.title")}</h1>
          <p>{t("portal.link_invalid")}</p>
        </div>
      ) : (
        <Spinner label={t("portal.logging_in")} />
      )}
    </div>
  );
}

function Gate() {
  const q = useQuery({
    queryKey: ["portal-me"],
    queryFn: async () => {
      try {
        return await api.get<Me>("/api/portal/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
    retry: false,
  });
  if (q.isLoading) return <div className="portal-center"><Spinner /></div>;
  if (!q.data)
    return (
      <div className="portal-center">
        <div className="portal-card">
          <Botanical variant="fern" style={{ right: -40, top: -30, width: 220 }} />
          <h1>{t("portal.title")}</h1>
          <p>{t("portal.need_link")}</p>
        </div>
      </div>
    );
  const me = q.data;
  return (
    <>
      <header className="portal-header">
        <Link to="/kunde" className="portal-brand">
          {me.tenant.name}
        </Link>
        <span className="small muted">{me.customer.name}</span>
      </header>
      <main className="portal-main">
        <Routes>
          <Route index element={<Overview me={me} />} />
          <Route path="auftraege/:id" element={<OrderPage me={me} />} />
          <Route path="zahlung/:id" element={<TestCheckout />} />
          <Route path="*" element={<Navigate to="/kunde" replace />} />
        </Routes>
      </main>
      <footer className="portal-footer small muted">
        {me.tenant.name} · {[me.tenant.street, `${me.tenant.postal_code ?? ""} ${me.tenant.city ?? ""}`.trim()].filter(Boolean).join(", ")}
        {me.tenant.phone && <> · <a href={`tel:${me.tenant.phone}`}>{me.tenant.phone}</a></>}
        {me.tenant.email && <> · <a href={`mailto:${me.tenant.email}`}>{me.tenant.email}</a></>}
      </footer>
    </>
  );
}

function StatusChip({ o }: { o: any }) {
  const tone = o.status === "returned" || o.status === "stored" ? "green" : o.status === "draft" ? "amber" : undefined;
  return <Badge tone={tone}>{t(`portal.steps.${o.progress.current}`)}</Badge>;
}

function Overview({ me }: { me: Me }) {
  const q = useQuery({ queryKey: ["portal-orders"], queryFn: () => api.get<any[]>("/api/portal/orders") });
  return (
    <div className="portal-stack">
      <section className="portal-hero">
        <Botanical variant="leaf" style={{ right: -20, bottom: -30, width: 200 }} />
        <h1>{t("portal.hello", { name: me.customer.name })}</h1>
        <p>{t("portal.intro", { tenant: me.tenant.name })}</p>
      </section>
      {q.isLoading && <Spinner />}
      {(q.data ?? []).length === 0 && !q.isLoading && <p className="muted">{t("portal.no_orders")}</p>}
      {(q.data ?? []).map((o) => (
        <Link key={o.id} to={`auftraege/${o.id}`} className="portal-card link">
          <div className="row between">
            <strong>
              {t(`portal.direction.${o.direction}`)} · {o.number}
            </strong>
            <StatusChip o={o} />
          </div>
          {o.appointment ? (
            <p>{t("portal.appointment", { date: fmtDate(o.appointment.date), from: o.appointment.from, to: o.appointment.to })}</p>
          ) : (
            o.earliest_date && <p className="muted">{t("portal.window", { from: fmtDate(o.earliest_date), to: fmtDate(o.latest_date) })}</p>
          )}
          {o.price?.gross != null && <p className="small muted">{t("portal.price", { price: fmtMoney(o.price.gross) })}</p>}
        </Link>
      ))}
    </div>
  );
}

function Progress({ p }: { p: { steps: string[]; current: string; index: number } }) {
  return (
    <ol className="portal-progress" aria-label={t("portal.progress")}>
      {p.steps.map((s, i) => (
        <li key={s} className={i < p.index ? "done" : i === p.index ? "current" : ""}>
          <span className="dot">{i < p.index ? "✓" : i + 1}</span>
          <span>{t(`portal.steps.${s}`)}</span>
        </li>
      ))}
    </ol>
  );
}

function OrderPage({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const [params] = useSearchParams();
  const q = useQuery({ queryKey: ["portal-order", id], queryFn: () => api.get<any>(`/api/portal/orders/${id}`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["portal-order", id] });
    qc.invalidateQueries({ queryKey: ["portal-orders"] });
  };
  if (q.isLoading || !q.data) return <Spinner />;
  const o = q.data;
  const accept = async (quoteId: string) => {
    try {
      await api.post(`/api/portal/quotes/${quoteId}/accept`);
      toast({ text: t("portal.accepted") });
      refresh();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const pay = async (body: { invoice_id?: string; quote_id?: string }) => {
    try {
      const p = await api.post<any>("/api/portal/payments", body);
      window.location.href = p.checkout_url;
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const result = params.get("zahlung");
  return (
    <div className="portal-stack">
      <Link to="/kunde" className="small">
        ← {t("portal.back")}
      </Link>
      <h1>
        {t(`portal.direction.${o.direction}`)} · {o.number}
      </h1>
      {result === "ok" && <div className="alert ok">{t("portal.paid_thanks")}</div>}
      {result === "abgebrochen" && <div className="alert warn">{t("portal.pay_cancelled")}</div>}
      <section className="portal-card">
        <Progress p={o.progress} />
        {o.appointment ? (
          <p className="portal-appointment">{t("portal.appointment", { date: fmtDate(o.appointment.date), from: o.appointment.from, to: o.appointment.to })}</p>
        ) : (
          <p className="muted">{o.earliest_date ? t("portal.window", { from: fmtDate(o.earliest_date), to: fmtDate(o.latest_date) }) : t("portal.no_date_yet")}</p>
        )}
      </section>

      {o.quotes.length > 0 && (
        <section className="portal-card">
          <h2>{t("portal.offer")}</h2>
          {o.quotes.map((q: any) => (
            <div key={q.id} className="row between">
              <span>
                {q.number} · {fmtMoney(q.gross)} · {t(`portal.quote_status.${q.status}`)}
                {q.valid_until && q.status === "created" && <span className="small muted"> · {t("portal.valid_until", { date: fmtDate(q.valid_until) })}</span>}
              </span>
              <span className="row" style={{ gap: 6 }}>
                {q.pdf_url && (
                  <a className="btn ghost small" href={q.pdf_url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                )}
                {(q.status === "created" || q.status === "sent") && (
                  <button className="btn small" onClick={() => accept(q.id)}>
                    {t("portal.accept")}
                  </button>
                )}
              </span>
            </div>
          ))}
        </section>
      )}

      {o.invoices.length > 0 && (
        <section className="portal-card">
          <h2>{t("portal.invoices")}</h2>
          {o.invoices.map((i: any) => (
            <div key={i.id} className="row between">
              <span>
                {i.number} · {fmtMoney(i.gross)} · {t(`portal.invoice_status.${i.status}`)}
                {i.due_date && i.status === "issued" && <span className="small muted"> · {t("portal.due", { date: fmtDate(i.due_date) })}</span>}
              </span>
              <span className="row" style={{ gap: 6 }}>
                {i.pdf_url && (
                  <a className="btn ghost small" href={i.pdf_url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                )}
                {i.status === "issued" && me.payments !== "off" && (
                  <button className="btn small" onClick={() => pay({ invoice_id: i.id })}>
                    {t("portal.pay_online")}
                  </button>
                )}
              </span>
            </div>
          ))}
        </section>
      )}

      {o.direction === "pickup" && ["draft", "confirmed", "planned"].includes(o.status) && <Photos order={o} me={me} onChange={refresh} />}
      {o.address && o.direction === "pickup" && ["draft", "confirmed", "planned"].includes(o.status) && <Location order={o} onSaved={refresh} />}
      {o.direction === "pickup" && o.status !== "returned" && <ReturnWish order={o} onSaved={refresh} />}
    </div>
  );
}

function Photos({ order, me, onChange }: { order: any; me: Me; onChange: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const consent = async () => {
    await api.post("/api/portal/consent", { accept: true });
    qc.invalidateQueries({ queryKey: ["portal-me"] });
  };
  const upload = async (file: File, kind: string, plantId?: string) => {
    const key = `${plantId ?? "path"}-${kind}`;
    setBusy(key);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (plantId) form.append("plant_id", plantId);
    try {
      await api.upload(`/api/portal/orders/${order.id}/photos`, form);
      onChange();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="portal-card">
      <h2>{t("portal.photos")}</h2>
      <p className="small muted">{t("portal.photos_help")}</p>
      {!me.consent.given ? (
        <div className="portal-consent">
          <p className="small">{me.consent.text || t("portal.consent_default")}</p>
          <button className="btn" onClick={consent}>
            {t("portal.consent_accept")}
          </button>
        </div>
      ) : (
        <>
          {(order.photo_check?.feedback ?? []).length > 0 && (
            <div className={`alert ${order.photo_check.overall_ok ? "ok" : "warn"}`}>
              <strong>{t("portal.check_feedback")}</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {(order.photo_check.feedback as string[]).map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          )}
          {order.plants.map((p: any) => (
            <div key={p.id} className="portal-plant">
              <strong>
                #{p.number} {p.name}
              </strong>
              <div className="portal-slots">
                {PLANT_KINDS.map((k) => (
                  <PhotoSlot key={k} kind={k} photo={p.photos.find((x: any) => x.kind === k)} busy={busy === `${p.id}-${k}`} onFile={(f) => upload(f, k, p.id)} />
                ))}
              </div>
            </div>
          ))}
          <div className="portal-plant">
            <strong>{t("portal.path")}</strong>
            <p className="small muted">{t("portal.path_help")}</p>
            <div className="portal-slots">
              {PATH_KINDS.map((k) => (
                <PhotoSlot key={k} kind={k} photo={k === "path_segment" ? undefined : order.path_photos.find((x: any) => x.kind === k)} busy={busy === `path-${k}`} onFile={(f) => upload(f, k)} />
              ))}
            </div>
            {order.path_photos.length > 0 && (
              <div className="portal-thumbs">
                {order.path_photos.map((ph: any) => (
                  <img key={ph.id} src={ph.url} alt={t(`portal.kinds.${ph.kind}`)} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function PhotoSlot({ kind, photo, busy, onFile }: { kind: string; photo?: any; busy: boolean; onFile: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <button type="button" className={`portal-slot ${photo ? "done" : ""}`} onClick={() => ref.current?.click()} disabled={busy}>
      {photo ? <img src={photo.url} alt="" /> : <span className="portal-slot-icon">📷</span>}
      <span className="small">{busy ? t("portal.uploading") : t(`portal.kinds.${kind}`)}</span>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </button>
  );
}

function PinPicker({ value, onChange }: { value: [number, number]; onChange: (v: [number, number]) => void }) {
  useMapEvents({ click: (e) => onChange([e.latlng.lat, e.latlng.lng]) });
  return <CircleMarker center={value} radius={10} pathOptions={{ color: "#c2693e", fillColor: "#c2693e", fillOpacity: 0.8 }} />;
}

function Location({ order, onSaved }: { order: any; onSaved: () => void }) {
  const toast = useToast();
  const a = order.address;
  const [pos, setPos] = useState<[number, number]>([a.lat ?? 48.78, a.lon ?? 9.18]);
  const [notes, setNotes] = useState({ parking_notes: a.parking_notes ?? "", bell_notes: a.bell_notes ?? "", access_notes: a.access_notes ?? "" });
  const save = async () => {
    try {
      await api.put(`/api/portal/orders/${order.id}/location`, { lat: pos[0], lon: pos[1], ...notes });
      toast({ text: t("portal.saved") });
      onSaved();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <section className="portal-card">
      <h2>{t("portal.location")}</h2>
      <p className="small muted">{t("portal.location_help")}</p>
      <div className="portal-map">
        <MapContainer center={pos} zoom={a.lat ? 18 : 12} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
          <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <PinPicker value={pos} onChange={setPos} />
        </MapContainer>
      </div>
      <div className="grid cols-3" style={{ marginTop: 12 }}>
        {(["parking_notes", "bell_notes", "access_notes"] as const).map((k) => (
          <div key={k} className="field">
            <label htmlFor={`loc-${k}`}>{t(`portal.${k}`)}</label>
            <input id={`loc-${k}`} className="input" value={notes[k]} onChange={(e) => setNotes({ ...notes, [k]: e.target.value })} />
          </div>
        ))}
      </div>
      <button className="btn" onClick={save}>
        {t("portal.save_location")}
      </button>
    </section>
  );
}

function ReturnWish({ order, onSaved }: { order: any; onSaved: () => void }) {
  const toast = useToast();
  const w = order.return_wish ?? {};
  const [form, setForm] = useState({ earliest_date: w.earliest_date ?? "", latest_date: w.latest_date ?? "", notes: w.notes ?? "" });
  const save = async () => {
    try {
      await api.put(`/api/portal/orders/${order.id}/return-wish`, {
        earliest_date: form.earliest_date || null,
        latest_date: form.latest_date || null,
        notes: form.notes || null,
      });
      toast({ text: t("portal.saved") });
      onSaved();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <section className="portal-card">
      <h2>{t("portal.return_wish")}</h2>
      <p className="small muted">{t("portal.return_wish_help")}</p>
      <div className="grid cols-3">
        <div className="field">
          <label htmlFor="rw-from">{t("portal.from")}</label>
          <input id="rw-from" type="date" className="input" value={form.earliest_date} onChange={(e) => setForm({ ...form, earliest_date: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="rw-to">{t("portal.to")}</label>
          <input id="rw-to" type="date" className="input" value={form.latest_date} onChange={(e) => setForm({ ...form, latest_date: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="rw-notes">{t("portal.notes")}</label>
          <input id="rw-notes" className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
      </div>
      <button className="btn" onClick={save}>
        {t("portal.save_wish")}
      </button>
    </section>
  );
}

function TestCheckout() {
  const { id } = useParams();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["portal-payment", id], queryFn: () => api.get<any>(`/api/portal/payments/${id}`) });
  const finish = async (success: boolean) => {
    const p = await api.post<any>(`/api/portal/payments/${id}/simulate`, { success });
    nav(`/kunde/auftraege/${p.order_id}?zahlung=${success ? "ok" : "abgebrochen"}`);
  };
  if (!q.data) return <Spinner />;
  return (
    <section className="portal-card" style={{ maxWidth: 480, margin: "0 auto" }}>
      <h1>{t("portal.test_checkout")}</h1>
      <p className="small muted">{t("portal.test_checkout_help")}</p>
      <p>
        {q.data.description}: <strong>{fmtMoney(q.data.amount)}</strong>
      </p>
      <div className="row">
        <button className="btn" onClick={() => finish(true)} disabled={q.data.status !== "pending"}>
          {t("portal.test_pay")}
        </button>
        <button className="btn ghost" onClick={() => finish(false)} disabled={q.data.status !== "pending"}>
          {t("portal.test_cancel")}
        </button>
      </div>
    </section>
  );
}
