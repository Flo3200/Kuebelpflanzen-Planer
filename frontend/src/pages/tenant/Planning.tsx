import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../../api/client";
import { LoadStatusBadge } from "../../components/loadplan/LoadPlanView";
import { Badge, Card, ConfirmButton, Empty, ErrorBox, Kpi, Modal, PageHeader, Progress, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtDate, fmtMinutes, fmtMoney, fmtNumber, t, tMaybe } from "../../i18n";

export function hm(min: number | null | undefined): string {
  if (min == null) return "–";
  const m = Math.round(min);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function usePlan(planId: string | null) {
  return useQuery({
    queryKey: ["plan", planId],
    queryFn: () => api.get<any>(`/api/plans/${planId}`),
    enabled: !!planId,
    refetchInterval: (q) => (q.state.data?.status === "computing" ? 1500 : false),
  });
}

export function PlanningPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.get<any[]>("/api/plans"), refetchInterval: 5000 });
  const [planId, setPlanId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"map" | "timeline" | "tours" | "unassigned">("timeline");
  const current = planId ?? plans.data?.find((p) => p.is_active)?.id ?? plans.data?.[0]?.id ?? null;
  const plan = usePlan(current);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["plan", current] });
    qc.invalidateQueries({ queryKey: ["plans"] });
  };
  const p = plan.data;

  return (
    <>
      <PageHeader
        title={t("planning.title")}
        description={t("planning.description")}
        actions={
          <>
            {(plans.data ?? []).length > 0 && (
              <select className="input" style={{ width: 260 }} value={current ?? ""} onChange={(e) => setPlanId(e.target.value)} aria-label={t("planning.plan")}>
                {(plans.data ?? []).map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} {x.is_active ? `· ${t("planning.active")}` : ""}
                  </option>
                ))}
              </select>
            )}
            <button className="btn" onClick={() => setCreating(true)}>
              {t("planning.new")}
            </button>
          </>
        }
      />
      {plans.isLoading && <Spinner />}
      {plans.data && plans.data.length === 0 && (
        <Empty title={t("planning.empty")} text={t("planning.empty_text")} action={<button className="btn" onClick={() => setCreating(true)}>{t("planning.new")}</button>} />
      )}
      {p && (
        <div className="stack lg">
          <div className="row between">
            <div className="row">
              {p.is_active ? <Badge tone="green">{t("planning.active")}</Badge> : <Badge>{t("planning.inactive")}</Badge>}
              <span className="small muted">
                {fmtDate(p.start_date)} · {t("planning.days_n", { n: p.days })} · {t(`orders.direction.${p.direction}`)}
                {p.computed_at && ` · ${t("planning.computed", { at: fmtDate(p.computed_at, true) })}`}
              </span>
            </div>
            <div className="row">
              {!p.is_active && p.status === "ready" && (
                <button className="btn secondary" onClick={async () => (await api.post(`/api/plans/${p.id}/activate`), refresh())}>
                  {t("planning.activate")}
                </button>
              )}
              <button
                className="btn ghost"
                disabled={p.status === "computing"}
                onClick={async () => {
                  await api.post(`/api/plans/${p.id}/replan`, {});
                  refresh();
                  toast({ text: t("planning.replanning") });
                }}
              >
                {t("planning.replan")}
              </button>
              <Link className="btn ghost" to={`/betrieb/szenarien?plan=${p.id}`}>
                {t("nav.scenarios")}
              </Link>
              <ConfirmButton
                onConfirm={async () => {
                  await api.del(`/api/plans/${p.id}`);
                  setPlanId(null);
                  refresh();
                }}
              >
                {t("common.delete")}
              </ConfirmButton>
            </div>
          </div>
          {p.needs_replan?.length > 0 && (
            <div className="alert warn">
              {t("planning.needs_replan")}{" "}
              <span className="small">
                {p.needs_replan
                  .map((r: string) => {
                    const [code, ...rest] = r.split(":");
                    return `${tMaybe(`planning.replan_reasons.${code}`) ?? code} ${rest.join(":")}`;
                  })
                  .join(" · ")}
              </span>
            </div>
          )}
          {p.status === "computing" && (
            <Card>
              <Spinner label={p.job?.message ?? t("planning.computing")} />
              {p.job && <div style={{ marginTop: 12 }}><Progress value={p.job.progress} /></div>}
            </Card>
          )}
          {p.status === "failed" && <div className="alert error">{t("planning.failed")}: {p.error}</div>}
          {p.status === "ready" && <PlanView plan={p} tab={tab} setTab={setTab} onChange={refresh} />}
        </div>
      )}
      {creating && (
        <NewPlanModal
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setPlanId(id);
            refresh();
          }}
        />
      )}
    </>
  );
}

function NewPlanModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const nextMonday = () => {
    const d = new Date();
    d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
    return d.toISOString().slice(0, 10);
  };
  const [form, setForm] = useState({ name: "", start_date: nextMonday(), days: 10, direction: "pickup", time_limit_s: "" });
  const [error, setError] = useState<unknown>(null);
  const create = async () => {
    try {
      const r = await api.post("/api/plans", {
        name: form.name || null, start_date: form.start_date, days: Number(form.days), direction: form.direction,
        time_limit_s: form.time_limit_s ? Number(form.time_limit_s) : null,
      });
      onCreated(r.id);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal
      title={t("planning.new")}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn" onClick={create}>
            {t("planning.compute")}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <div className="field">
          <label htmlFor="pl-name">{t("common.name")}</label>
          <input id="pl-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t("planning.name_placeholder")} />
        </div>
        <div className="field">
          <label htmlFor="pl-start">{t("planning.start_date")}</label>
          <input id="pl-start" type="date" className="input" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pl-days">{t("planning.days")}</label>
          <input id="pl-days" type="number" min={1} max={90} className="input num" value={form.days} onChange={(e) => setForm({ ...form, days: Number(e.target.value) })} />
        </div>
        <div className="field">
          <label htmlFor="pl-dir">{t("orders.direction_label")}</label>
          <select id="pl-dir" className="input" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
            <option value="pickup">{t("orders.direction.pickup")}</option>
            <option value="return">{t("orders.direction.return")}</option>
          </select>
          {form.direction === "return" && <p className="xs muted">{t("returns.plan_hint")}</p>}
        </div>
        <div className="field">
          <label htmlFor="pl-limit">{t("planning.time_limit")}</label>
          <input id="pl-limit" type="number" className="input num" value={form.time_limit_s} onChange={(e) => setForm({ ...form, time_limit_s: e.target.value })} placeholder={t("planning.time_limit_default")} />
        </div>
      </div>
      <p className="small muted" style={{ marginTop: 12 }}>{t("planning.new_help")}</p>
      <ErrorBox error={error} />
    </Modal>
  );
}

function PlanView({ plan, tab, setTab, onChange }: { plan: any; tab: any; setTab: (t: any) => void; onChange: () => void }) {
  const k = plan.kpis ?? {};
  return (
    <>
      <div className="grid cols-4">
        <Kpi label={t("planning.kpi_days")} value={fmtNumber(k.days_until_done)} sub={t("planning.kpi_days_sub", { work: k.work_days ?? 0, last: k.last_date ? fmtDate(k.last_date) : "–" })} />
        <Kpi label={t("planning.kpi_stops")} value={`${fmtNumber(k.stops_planned)} / ${fmtNumber((k.stops_planned ?? 0) + (k.stops_unassigned ?? 0))}`} sub={t("planning.kpi_plants", { n: fmtNumber(k.plants_planned) })} />
        <Kpi label={t("planning.kpi_cost")} value={fmtMoney(k.total_cost)} sub={k.cost_per_plant != null ? t("planning.kpi_cost_plant", { c: fmtMoney(k.cost_per_plant) }) : undefined} />
        <Kpi label={t("planning.kpi_utilisation")} value={k.utilisation_pct != null ? `${fmtNumber(k.utilisation_pct)} %` : "–"} sub={t("planning.kpi_km", { km: fmtNumber(k.distance_km), ot: fmtMinutes(k.overtime_min) })} />
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "timeline", label: t("planning.tab_timeline") },
          { key: "map", label: t("planning.tab_map") },
          { key: "tours", label: t("planning.tab_tours") },
          { key: "unassigned", label: `${t("planning.tab_unassigned")} (${plan.unassigned?.length ?? 0})` },
        ]}
      />
      {tab === "map" && <PlanMap plan={plan} />}
      {tab === "timeline" && <Timeline plan={plan} onChange={onChange} />}
      {tab === "tours" && <ToursList plan={plan} onChange={onChange} />}
      {tab === "unassigned" && <Unassigned plan={plan} />}
    </>
  );
}

// ----------------------------------------------------------------------------- map

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length > 1) map.fitBounds(points, { padding: [30, 30] });
  }, [map, points]);
  return null;
}

export function PlanMap({ plan }: { plan: any }) {
  const [day, setDay] = useState<string>("");
  const dates = Array.from(new Set(plan.tours.map((tr: any) => tr.date))) as string[];
  const tours = plan.tours.filter((tr: any) => !day || tr.date === day);
  const depot: [number, number] = [plan.depot.lat ?? 48.78, plan.depot.lon ?? 9.18];
  const points = useMemo(() => {
    const pts: [number, number][] = [depot];
    tours.forEach((tr: any) => tr.stops.forEach((s: any) => s.lat && pts.push([s.lat, s.lon])));
    return pts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, plan.computed_at]);
  return (
    <div className="stack">
      <div className="row">
        <select className="input" style={{ width: 220 }} value={day} onChange={(e) => setDay(e.target.value)} aria-label={t("common.date")}>
          <option value="">{t("planning.all_days")}</option>
          {dates.map((d) => (
            <option key={d} value={d}>
              {fmtDate(d)}
            </option>
          ))}
        </select>
        <span className="small muted">{t("planning.map_hint")}</span>
      </div>
      <div style={{ height: 560 }}>
        <MapContainer center={depot} zoom={11} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
          <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <FitBounds points={points} />
          <CircleMarker center={depot} radius={10} pathOptions={{ color: "#142a1e", fillColor: "#f4eee3", fillOpacity: 1, weight: 3 }}>
            <Tooltip>{plan.depot.name}</Tooltip>
          </CircleMarker>
          {tours.map((tr: any) => {
            const line: [number, number][] = [depot, ...tr.stops.filter((s: any) => s.lat).map((s: any) => [s.lat, s.lon] as [number, number]), depot];
            return (
              <Polyline key={tr.id} positions={line} pathOptions={{ color: tr.color, weight: 3, opacity: 0.8 }}>
                <Tooltip sticky>
                  {fmtDate(tr.date)} · {tr.label} · {t("planning.trip", { n: tr.trip_no })}
                </Tooltip>
              </Polyline>
            );
          })}
          {tours.flatMap((tr: any) =>
            tr.stops
              .filter((s: any) => s.lat)
              .map((s: any) => (
                <CircleMarker key={s.id} center={[s.lat, s.lon]} radius={7} pathOptions={{ color: tr.color, fillColor: tr.color, fillOpacity: 0.9, weight: 2 }}>
                  <Tooltip>
                    {s.position}. {s.number} · {s.customer} · {s.plants} {t("orders.plants_short")} · {hm(s.start_min)}
                  </Tooltip>
                </CircleMarker>
              )),
          )}
          {!day &&
            plan.unassigned
              .filter((u: any) => u.lat)
              .map((u: any) => (
                <CircleMarker key={u.order_id} center={[u.lat, u.lon]} radius={6} pathOptions={{ color: "#888", fillColor: "#fff", fillOpacity: 1, weight: 2, dashArray: "3" }}>
                  <Tooltip>
                    {u.number} · {t(`planning.reasons.${u.reason}`)}
                  </Tooltip>
                </CircleMarker>
              ))}
        </MapContainer>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- timeline

function Timeline({ plan, onChange }: { plan: any; onChange: () => void }) {
  const toast = useToast();
  const [drag, setDrag] = useState<string | null>(null);
  const days = useMemo(() => {
    const m = new Map<string, any[]>();
    plan.tours.forEach((tr: any) => m.set(tr.date, [...(m.get(tr.date) ?? []), tr]));
    return Array.from(m.entries());
  }, [plan]);
  const startMin = 6 * 60;
  const endMin = 20 * 60;
  const pct = (m: number) => `${((Math.max(startMin, Math.min(endMin, m)) - startMin) / (endMin - startMin)) * 100}%`;
  const width = (a: number, b: number) => `${(Math.max(0, Math.min(endMin, b) - Math.max(startMin, a)) / (endMin - startMin)) * 100}%`;
  const move = async (stopId: string, tourId: string) => {
    try {
      await api.post(`/api/tour-stops/${stopId}/move`, { tour_id: tourId });
      onChange();
      toast({ text: t("planning.moved") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  if (!plan.tours.length) return <Empty title={t("planning.no_tours")} />;
  return (
    <div className="stack lg">
      <p className="small muted">{t("planning.timeline_hint")}</p>
      {days.map(([d, tours]) => (
        <Card key={d} title={fmtDate(d)}>
          <div style={{ position: "relative", marginLeft: 220 }}>
            <div className="row xs muted" style={{ justifyContent: "space-between" }}>
              {Array.from({ length: 8 }, (_, i) => (
                <span key={i}>{hm(startMin + i * 120)}</span>
              ))}
            </div>
          </div>
          <div className="stack" style={{ gap: 6, marginTop: 4 }}>
            {tours.map((tr: any) => (
              <div
                key={tr.id}
                className="row"
                style={{ gap: 0, alignItems: "stretch" }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (drag) move(drag, tr.id);
                  setDrag(null);
                }}
              >
                <div style={{ width: 220, paddingRight: 8 }} className="small">
                  <div className="row" style={{ gap: 6 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: tr.color, display: "inline-block" }} />
                    <strong>{tr.vehicle}</strong>
                    {tr.trip_no > 1 && <Badge>{t("planning.trip", { n: tr.trip_no })}</Badge>}
                  </div>
                  <div className="xs muted">{tr.members.map((m: any) => m.name.split(" ")[0]).join(", ")}</div>
                  <div className="row" style={{ gap: 4 }}>
                    {tr.fixed && <Badge tone="blue">{t("planning.fixed")}</Badge>}
                    {tr.warnings.length > 0 && <Badge tone="red">{tr.warnings.length} ⚠</Badge>}
                    {tr.load_status === "failed" && (
                      <Link to={`/betrieb/planung/touren/${tr.id}/ladeplan`} title={tr.load_message ?? ""}>
                        <Badge tone="red">{t("planning.load_failed")}</Badge>
                      </Link>
                    )}
                  </div>
                </div>
                <div style={{ position: "relative", flex: 1, height: 44, background: "var(--surface-2)", borderRadius: 8 }}>
                  <div title={t("planning.working_window")} style={{ position: "absolute", left: pct(tr.unit.start), width: width(tr.unit.start, tr.unit.end), top: 0, bottom: 0, background: "var(--success-soft)", borderRadius: 8, opacity: 0.6 }} />
                  <div style={{ position: "absolute", left: pct(tr.start_min), width: width(tr.start_min, tr.end_min), top: 20, height: 4, background: tr.color, opacity: 0.4 }} />
                  {tr.breaks.map((b: any, i: number) => (
                    <div key={i} title={t("planning.break")} style={{ position: "absolute", left: pct(b.start), width: width(b.start, b.end), top: 4, bottom: 4, background: "repeating-linear-gradient(45deg, var(--surface-3), var(--surface-3) 4px, transparent 4px, transparent 8px)", borderRadius: 4 }} />
                  ))}
                  {tr.stops.map((s: any) => (
                    <div
                      key={s.id}
                      draggable
                      onDragStart={() => setDrag(s.id)}
                      title={`${s.position}. ${s.number} · ${s.customer} · ${hm(s.start_min)}–${hm(s.end_min)} · ${s.plants} ${t("orders.plants_short")}${s.warnings?.length ? " · ⚠ " + s.warnings.map((w: string) => t(`planning.warnings.${w}`)).join(", ") : ""}`}
                      style={{
                        position: "absolute", left: pct(s.start_min), width: width(s.start_min, s.end_min), top: 6, bottom: 6, minWidth: 6,
                        background: tr.color, borderRadius: 6, cursor: "grab", color: "#fff", fontSize: 11, overflow: "hidden", whiteSpace: "nowrap",
                        padding: "2px 4px", outline: s.warnings?.length ? "2px solid var(--danger)" : s.fixed ? "2px solid var(--info)" : undefined,
                      }}
                    >
                      {s.position}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------- tours

function ToursList({ plan, onChange }: { plan: any; onChange: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const fix = async (url: string, fixed: boolean) => {
    await api.patch(url, { fixed });
    onChange();
  };
  return (
    <div className="stack">
      {plan.tours.map((tr: any) => (
        <div key={tr.id} className="card tight">
          <div className="row between" style={{ cursor: "pointer" }} onClick={() => setOpen(open === tr.id ? null : tr.id)}>
            <div className="row">
              <span style={{ width: 12, height: 12, borderRadius: 3, background: tr.color, display: "inline-block" }} />
              <strong>{fmtDate(tr.date)}</strong>
              <span>{tr.label}</span>
              {tr.trip_no > 1 && <Badge>{t("planning.trip", { n: tr.trip_no })}</Badge>}
              {tr.changed_at && <Badge tone="amber">{t("planning.changed")}</Badge>}
            </div>
            <div className="row small">
              <span className="num">
                {hm(tr.start_min)}–{hm(tr.end_min)} · {tr.stops.length} {t("planning.stops")} · {fmtNumber(tr.distance_km)} km · {fmtNumber(tr.load.weight)}/{fmtNumber(tr.load.cap_weight)} kg · {fmtMoney(tr.costs.self_cost)}
              </span>
              <Link className="btn ghost small" to={`/betrieb/planung/touren/${tr.id}/ladeplan`} onClick={(e) => e.stopPropagation()} title={tr.load_message ?? ""}>
                {t("loadplan.open")} <LoadStatusBadge status={tr.load_status} />
              </Link>
              <label className="checkbox" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={tr.fixed} onChange={(e) => fix(`/api/tours/${tr.id}`, e.target.checked)} />
                {t("planning.fix")}
              </label>
            </div>
          </div>
          {tr.warnings.length > 0 && (
            <div className="small" style={{ color: "var(--danger)", marginTop: 6 }}>
              {tr.warnings.map((w: string) => t(`planning.warnings.${w.split(":")[0]}`) + (w.includes(":") ? ` (${w.split(":")[1]})` : "")).join(" · ")}
            </div>
          )}
          {open === tr.id && (
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t("orders.number")}</th>
                    <th>{t("orders.customer")}</th>
                    <th>{t("orders.place")}</th>
                    <th className="num">{t("planning.arrival")}</th>
                    <th className="num">{t("planning.on_site")}</th>
                    <th className="num">{t("orders.plants")}</th>
                    <th>{t("planning.move_to")}</th>
                    <th>{t("planning.fix")}</th>
                  </tr>
                </thead>
                <tbody>
                  {tr.stops.map((s: any) => (
                    <tr key={s.id}>
                      <td className="num">{s.position}</td>
                      <td>
                        <Link to={`/betrieb/auftraege/${s.order_id}`}>{s.number}</Link>
                        {s.experiment && <Badge tone="blue">{t("planning.experiment")}</Badge>}
                      </td>
                      <td>{s.customer}</td>
                      <td className="small">{s.city}</td>
                      <td className="num">{hm(s.start_min)}</td>
                      <td className="num">{fmtMinutes(s.service_min)}</td>
                      <td className="num">{s.plants}</td>
                      <td>
                        <select
                          className="input"
                          style={{ width: 200 }}
                          value=""
                          onChange={async (e) => {
                            if (!e.target.value) return;
                            await api.post(`/api/tour-stops/${s.id}/move`, { tour_id: e.target.value });
                            onChange();
                          }}
                          aria-label={t("planning.move_to")}
                        >
                          <option value="">–</option>
                          {plan.tours
                            .filter((o: any) => o.id !== tr.id)
                            .map((o: any) => (
                              <option key={o.id} value={o.id}>
                                {fmtDate(o.date)} · {o.vehicle} #{o.trip_no}
                              </option>
                            ))}
                        </select>
                      </td>
                      <td>
                        <input type="checkbox" checked={s.fixed} onChange={(e) => fix(`/api/tour-stops/${s.id}`, e.target.checked)} aria-label={t("planning.fix")} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="row small muted" style={{ marginTop: 8 }}>
                {t("planning.costs_line", { labour: fmtMoney(tr.costs.labour), vehicle: fmtMoney(tr.costs.vehicle), overtime: fmtMoney(tr.costs.overtime) })}
                {tr.breaks.map((b: any, i: number) => (
                  <span key={i}>· {t("planning.break_at", { from: hm(b.start), to: hm(b.end) })}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** A hint {code, params} for an unplanned stop or a fixed team (package D), translated. */
export function hintText(h: { code: string; params: Record<string, any> }): string {
  return tMaybe(`planning.hints.${h.code}`, h.params) ?? h.code;
}

function TeamIssues({ plan }: { plan: any }) {
  const issues: any[] = plan.solver?.team_issues ?? [];
  if (plan.solver?.team_mode !== "fixed" || !issues.length) return null;
  return (
    <div className="alert warn" style={{ marginBottom: 16 }}>
      <strong>{t("planning.team_issues_title")}</strong>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {issues.map((h, i) => (
          <li key={i} className="small">
            {hintText(h)}
          </li>
        ))}
      </ul>
      <div className="xs muted" style={{ marginTop: 6 }}>
        {t("planning.team_issues_help")} <Link to="/betrieb/verfuegbarkeit">{t("nav.availability")}</Link> · <Link to="/betrieb/teams">{t("resources.teams")}</Link>
      </div>
    </div>
  );
}

function Unassigned({ plan }: { plan: any }) {
  if (!plan.unassigned.length)
    return (
      <>
        <TeamIssues plan={plan} />
        <Empty title={t("planning.all_assigned")} />
      </>
    );
  return (
    <>
    <TeamIssues plan={plan} />
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t("orders.number")}</th>
            <th>{t("orders.customer")}</th>
            <th>{t("orders.place")}</th>
            <th className="num">{t("orders.plants")}</th>
            <th>{t("planning.reason")}</th>
          </tr>
        </thead>
        <tbody>
          {plan.unassigned.map((u: any) => (
            <tr key={u.order_id}>
              <td>
                <Link to={`/betrieb/auftraege/${u.order_id}`}>{u.number}</Link>
              </td>
              <td>{u.customer}</td>
              <td className="small">{u.city}</td>
              <td className="num">{u.plants ?? "–"}</td>
              <td>
                <Badge tone="amber">{t(`planning.reasons.${u.reason}`)}</Badge>
                {u.need != null && <span className="xs muted"> · {t("planning.need_persons", { n: u.need })}</span>}
                <div className="xs muted">{tMaybe(`planning.reason_help.${u.reason}`)}</div>
                {(u.hints ?? []).map((h: any, i: number) => (
                  <div key={i} className="small" style={{ marginTop: 4 }}>
                    → {hintText(h)}
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
