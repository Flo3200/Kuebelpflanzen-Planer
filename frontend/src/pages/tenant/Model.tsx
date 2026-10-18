// Model quality: fits of the time formula to measurements (proposal -> adopt/discard), measurements.
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Badge, Card, Empty, ErrorBox, Kpi, PageHeader, Progress, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtDate, fmtNumber, t, tMaybe } from "../../i18n";

type Metrics = { n: number; mae: number; rmse: number; mape: number; bias: number };

interface Fit {
  id: string;
  status: "proposed" | "adopted" | "discarded";
  created_at: string;
  n_measurements: number;
  parameters: Record<string, { old: number; new: number; se: number | null; fitted: boolean; unit: string }>;
  staff_factors: Record<string, { name: string; old: number; new: number; se: number; n: number }>;
  metrics: {
    before: Metrics;
    after: Metrics;
    cv: Record<string, { folds: number; cv?: Metrics; baseline?: Metrics; fitted_params?: string[]; name?: string; n_learnable?: number }>;
    tier: number;
    active_tier: number;
    sigma: { current: number; proposed: number | null; quantile: number; coverage_current: number | null; coverage_proposed: number | null };
    suggestion: { tier: number; mae: number; mae_active: number; enough_data: boolean } | null;
    loss: string;
    excluded: number;
  };
  report?: {
    points: { id: string; order: string; measured: number; before: number; after: number; oof: number | null; team: number; used: boolean; exclude_reason: string | null; experiment: boolean }[];
    histogram: { from: number; to: number; n: number }[];
    by_feature: { feature: string; group: string; n: number; mae_before: number; mae_after: number; bias_after: number }[];
    outliers: { id: string; order: string; residual: number; ratio: number }[];
  };
}

const n1 = (v: number | null | undefined) => (v == null ? "–" : fmtNumber(v, 1));
const n3 = (v: number | null | undefined) => (v == null ? "–" : fmtNumber(v, Math.abs(v) < 1 ? 3 : 2));
const pct = (v: number | null | undefined) => (v == null ? "–" : `${fmtNumber(v * 100)} %`);

export function ModelPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const auth = useAuth();
  const [tab, setTab] = useState<"fits" | "measurements">("fits");
  const [jobId, setJobId] = useState<string | null>(null);
  const fits = useQuery({ queryKey: ["fits"], queryFn: () => api.get<Fit[]>("/api/learning/fits") });
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<any>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ["done", "failed", "cancelled"].includes(q.state.data.status) ? false : 1500),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? fits.data?.[0]?.id ?? null;
  useEffect(() => {
    const j = job.data;
    if (!j) return;
    if (j.status === "done") {
      setJobId(null);
      qc.invalidateQueries({ queryKey: ["fits"] });
      setSelected(j.result?.fit_id ?? null);
      toast({ text: t("model.fit_done") });
    } else if (j.status === "failed") {
      setJobId(null);
      toast({ text: j.error ?? t("model.fit_failed"), tone: "error" });
    }
  }, [job.data, qc, toast]);
  const start = async () => {
    try {
      const r = await api.post<any>("/api/learning/fits", {});
      setJobId(r.job_id);
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const synthetic = async () => {
    try {
      const r = await api.post<any>("/api/learning/synthetic", { n: 150 });
      toast({ text: t("model.synthetic_done", { n: r.created }) });
      qc.invalidateQueries({ queryKey: ["measurements"] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const canFit = auth.has("model.fit");
  return (
    <>
      <PageHeader
        title={t("model.title")}
        description={t("model.description")}
        actions={
          canFit && (
            <>
              <button className="btn ghost" onClick={synthetic} title={t("model.synthetic_help")}>
                {t("model.synthetic")}
              </button>
              <button className="btn" onClick={start} disabled={!!jobId}>
                {jobId ? t("model.fitting") : t("model.start_fit")}
              </button>
            </>
          )
        }
      />
      {jobId && job.data && (
        <Card>
          <div className="small muted">{job.data.message ?? t("model.fitting")}</div>
          <Progress value={job.data.progress ?? 0} />
        </Card>
      )}
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "fits", label: t("model.tab_fits") },
          { key: "measurements", label: t("model.tab_measurements") },
        ]}
      />
      {tab === "fits" && (
        <>
          {fits.isLoading && <Spinner />}
          <ErrorBox error={fits.error} />
          {fits.data && fits.data.length === 0 && <Empty title={t("model.no_fits")} text={t("model.no_fits_text")} />}
          {fits.data && fits.data.length > 0 && (
            <div className="stack lg">
              <div className="row">
                <select className="input" style={{ maxWidth: 420 }} value={current ?? ""} onChange={(e) => setSelected(e.target.value)} aria-label={t("model.fit")}>
                  {fits.data.map((f) => (
                    <option key={f.id} value={f.id}>
                      {fmtDate(f.created_at, true)} · {t(`model.status.${f.status}`)} · {f.n_measurements} {t("model.measurements_short")}
                    </option>
                  ))}
                </select>
              </div>
              {current && <FitDetail id={current} canFit={canFit} />}
            </div>
          )}
        </>
      )}
      {tab === "measurements" && <Measurements canFit={canFit} />}
    </>
  );
}

function FitDetail({ id, canFit }: { id: string; canFit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["fit", id], queryFn: () => api.get<Fit>(`/api/learning/fits/${id}`) });
  const [opts, setOpts] = useState({ parameters: true, staff: true, sigma: true });
  const f = q.data;
  const scatter = useMemo(() => {
    const pts = f?.report?.points ?? [];
    return {
      before: pts.filter((p) => p.used).map((p) => ({ x: p.measured, y: p.before, order: p.order })),
      after: pts.filter((p) => p.used).map((p) => ({ x: p.measured, y: p.after, order: p.order })),
      excluded: pts.filter((p) => !p.used).map((p) => ({ x: p.measured, y: p.after, order: p.order })),
      max: Math.max(10, ...pts.map((p) => Math.max(p.measured, p.after, p.before))),
    };
  }, [f]);
  if (q.isLoading || !f) return <Spinner />;
  const m = f.metrics;
  const decide = async (action: "adopt" | "discard") => {
    try {
      await api.post(`/api/learning/fits/${id}/${action}`, action === "adopt" ? opts : undefined);
      toast({ text: t(action === "adopt" ? "model.adopted" : "model.discarded") });
      qc.invalidateQueries({ queryKey: ["fits"] });
      qc.invalidateQueries({ queryKey: ["fit", id] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const exclude = async (mid: string) => {
    await api.patch(`/api/measurements/${mid}`, { excluded: true, exclude_reason: t("model.outlier") });
    toast({ text: t("model.excluded_hint") });
    qc.invalidateQueries({ queryKey: ["measurements"] });
  };
  const cvActive = m.cv[String(m.tier)]?.cv;
  return (
    <div className="stack lg">
      <div className="grid cols-4">
        <Kpi label={t("model.kpi_n")} value={f.n_measurements} sub={m.excluded ? t("model.kpi_excluded", { n: m.excluded }) : undefined} />
        <Kpi label={t("model.kpi_mae")} value={`${n1(m.before.mae)} → ${n1(m.after.mae)} min`} sub={t("model.kpi_mape", { a: n1(m.before.mape), b: n1(m.after.mape) })} />
        <Kpi label={t("model.kpi_cv")} value={cvActive ? `${n1(cvActive.mae)} min` : "–"} sub={t("model.kpi_cv_sub", { k: m.cv[String(m.tier)]?.folds ?? 0 })} />
        <Kpi label={t("model.kpi_bias")} value={`${n1(m.after.bias)} min`} sub={t("model.kpi_bias_sub")} />
      </div>
      {f.status === "proposed" && canFit ? (
        <Card title={t("model.decision")}>
          <p className="small muted">{t("model.decision_text")}</p>
          <div className="row">
            {(["parameters", "staff", "sigma"] as const).map((k) => (
              <label key={k} className="checkbox">
                <input type="checkbox" checked={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} />
                {t(`model.adopt_${k}`)}
              </label>
            ))}
          </div>
          <div className="row">
            <button className="btn" onClick={() => decide("adopt")}>
              {t("model.adopt")}
            </button>
            <button className="btn ghost" onClick={() => decide("discard")}>
              {t("model.discard")}
            </button>
          </div>
        </Card>
      ) : (
        <div>
          <Badge tone={f.status === "adopted" ? "green" : undefined}>{t(`model.status.${f.status}`)}</Badge>
        </div>
      )}
      {m.suggestion && (
        <div className="alert warn">
          {t("model.suggest_tier", { tier: m.suggestion.tier, mae: n1(m.suggestion.mae), active: n1(m.suggestion.mae_active) })}
          {!m.suggestion.enough_data && ` ${t("model.suggest_more_data")}`}
        </div>
      )}
      <div className="grid cols-2">
        <Card title={t("model.scatter")}>
          <div style={{ height: 320 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
                <CartesianGrid stroke="var(--border)" />
                <XAxis type="number" dataKey="x" name={t("model.measured")} unit=" min" domain={[0, Math.ceil(scatter.max)]} tick={{ fill: "var(--text-muted)", fontSize: 12 }} />
                <YAxis type="number" dataKey="y" name={t("model.predicted")} unit=" min" domain={[0, Math.ceil(scatter.max)]} tick={{ fill: "var(--text-muted)", fontSize: 12 }} />
                <ZAxis range={[28, 28]} />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={(v) => `${fmtNumber(Number(v), 1)} min`} />
                <Legend />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: scatter.max, y: scatter.max }]} stroke="var(--text-faint)" strokeDasharray="4 4" />
                <Scatter name={t("model.before")} data={scatter.before} fill="var(--text-faint)" fillOpacity={0.6} />
                <Scatter name={t("model.after")} data={scatter.after} fill="var(--success)" />
                {scatter.excluded.length > 0 && <Scatter name={t("model.excluded")} data={scatter.excluded} fill="var(--accent)" shape="cross" />}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="xs muted">{t("model.scatter_hint")}</p>
        </Card>
        <Card title={t("model.histogram")}>
          <div style={{ height: 320 }}>
            <ResponsiveContainer>
              <BarChart data={(f.report?.histogram ?? []).map((h) => ({ label: `${fmtNumber(h.from)}…${fmtNumber(h.to)}`, n: h.n }))}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "var(--text-muted)", fontSize: 11 }} interval="preserveStartEnd" />
                <YAxis allowDecimals={false} tick={{ fill: "var(--text-muted)", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="n" name={t("model.count")} fill="var(--success)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="xs muted">{t("model.histogram_hint")}</p>
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title={t("model.parameters")}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("model.param")}</th>
                  <th className="num">{t("model.old")}</th>
                  <th className="num">{t("model.new")}</th>
                  <th className="num">± {t("model.se")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(f.parameters).map(([k, v]) => (
                  <tr key={k}>
                    <td>
                      <code>{k}</code> <span className="xs muted">{v.unit}</span>
                      {!v.fitted && <span className="xs muted"> · {t("model.not_fitted")}</span>}
                    </td>
                    <td className="num">{n3(v.old)}</td>
                    <td className="num" style={{ fontWeight: v.fitted ? 600 : 400 }}>
                      {n3(v.new)}
                    </td>
                    <td className="num">{v.fitted ? n3(v.se) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title={t("model.cv")}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("model.tier")}</th>
                  <th className="num">{t("model.cv_mae")}</th>
                  <th className="num">{t("model.baseline_mae")}</th>
                  <th className="num">{t("model.cv_mape")}</th>
                  <th className="num">{t("model.n_params")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(m.cv).map(([tier, c]) => (
                  <tr key={tier}>
                    <td>
                      {c.name ?? `${t("model.tier")} ${tier}`} {Number(tier) === m.active_tier && <Badge tone="green">{t("model.active")}</Badge>}
                    </td>
                    <td className="num">{n1(c.cv?.mae)}</td>
                    <td className="num">{n1(c.baseline?.mae)}</td>
                    <td className="num">{c.cv ? `${n1(c.cv.mape)} %` : "–"}</td>
                    <td className="num">
                      {c.fitted_params?.length ?? 0}/{c.n_learnable ?? "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="xs muted">{t("model.cv_hint")}</p>
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title={t("model.buffer")}>
          <div className="loadplan-metrics small">
            <span>{t("model.quantile")}</span>
            <span className="num">{pct(m.sigma.quantile)}</span>
            <span>{t("model.sigma_current")}</span>
            <span className="num">{n3(m.sigma.current)}</span>
            <span>{t("model.sigma_proposed")}</span>
            <span className="num">{n3(m.sigma.proposed)}</span>
            <span>{t("model.coverage_current")}</span>
            <span className="num">{pct(m.sigma.coverage_current)}</span>
            <span>{t("model.coverage_proposed")}</span>
            <span className="num">{pct(m.sigma.coverage_proposed)}</span>
          </div>
          <p className="xs muted">{t("model.buffer_hint")}</p>
        </Card>
        <Card title={t("model.staff")}>
          {Object.keys(f.staff_factors).length === 0 ? (
            <p className="small muted">{t("model.no_staff")}</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("model.person")}</th>
                    <th className="num">{t("model.n")}</th>
                    <th className="num">{t("model.old")}</th>
                    <th className="num">{t("model.new")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(f.staff_factors)
                    .sort((a, b) => b[1].new - a[1].new)
                    .map(([sid, s]) => (
                      <tr key={sid}>
                        <td>{s.name}</td>
                        <td className="num">{s.n}</td>
                        <td className="num">{n3(s.old)}</td>
                        <td className="num">{n3(s.new)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="xs muted">{t("model.staff_hint")}</p>
        </Card>
      </div>
      <Card title={t("model.by_feature")}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("model.feature")}</th>
                <th>{t("model.group")}</th>
                <th className="num">{t("model.n")}</th>
                <th className="num">{t("model.mae_before")}</th>
                <th className="num">{t("model.mae_after")}</th>
                <th className="num">{t("model.bias_after")}</th>
              </tr>
            </thead>
            <tbody>
              {(f.report?.by_feature ?? []).map((b) => (
                <tr key={`${b.feature}-${b.group}`}>
                  <td>{tMaybe(`model.features.${b.feature}`) ?? b.feature}</td>
                  <td>{b.group}</td>
                  <td className="num">{b.n}</td>
                  <td className="num">{n1(b.mae_before)}</td>
                  <td className="num">{n1(b.mae_after)}</td>
                  <td className="num" style={{ color: Math.abs(b.bias_after) > 5 ? "var(--danger)" : undefined }}>
                    {n1(b.bias_after)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {(f.report?.outliers ?? []).length > 0 && (
        <Card title={t("model.outliers")}>
          <p className="small muted">{t("model.outliers_text")}</p>
          <div className="stack" style={{ gap: 6 }}>
            {f.report!.outliers.map((o) => (
              <div key={o.id} className="row between small">
                <span>
                  {o.order}: {t("model.outlier_line", { r: n1(o.residual), ratio: n1(o.ratio) })}
                </span>
                {canFit && (
                  <button className="btn ghost small" onClick={() => exclude(o.id)}>
                    {t("model.exclude")}
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function Measurements({ canFit }: { canFit: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["measurements"], queryFn: () => api.get<any>("/api/measurements") });
  const toggle = async (m: any) => {
    await api.patch(`/api/measurements/${m.id}`, { excluded: !m.excluded, exclude_reason: m.excluded ? null : t("model.manual_exclude") });
    qc.invalidateQueries({ queryKey: ["measurements"] });
  };
  if (q.isLoading) return <Spinner />;
  const items: any[] = q.data?.items ?? [];
  if (!items.length) return <Empty title={t("model.no_measurements")} text={t("model.no_measurements_text")} />;
  return (
    <Card>
      <p className="small muted">
        {Object.entries(q.data.counts as Record<string, number>)
          .map(([k, v]) => `${t(`model.sources.${k}`)}: ${v}`)
          .join(" · ")}
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("model.date")}</th>
              <th>{t("orders.number")}</th>
              <th>{t("model.source")}</th>
              <th className="num">{t("model.team")}</th>
              <th className="num">{t("model.duration")}</th>
              <th className="num">{t("model.fixed")}</th>
              <th className="num">{t("model.carry")}</th>
              <th className="num">{t("model.drive")}</th>
              <th className="num">{t("model.planned")}</th>
              <th>{t("model.state")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} style={{ opacity: m.excluded ? 0.55 : 1 }}>
                <td>{fmtDate(m.date)}</td>
                <td>{m.order_number}</td>
                <td>
                  {t(`model.sources.${m.source}`)}
                  {m.experiment && <Badge tone="blue">{t("model.experiment")}</Badge>}
                  {m.deviations > 0 && <Badge tone="amber">{t("model.deviations_n", { n: m.deviations })}</Badge>}
                </td>
                <td className="num">{m.team_size}</td>
                <td className="num">{n1(m.duration_min)}</td>
                <td className="num">{n1(m.fixed_min)}</td>
                <td className="num">{n1(m.carry_min)}</td>
                <td className="num">{n1(m.drive_min)}</td>
                <td className="num">{n1(m.predicted_min)}</td>
                <td>
                  {canFit ? (
                    <label className="checkbox" title={m.exclude_reason ?? ""}>
                      <input type="checkbox" checked={!m.excluded} onChange={() => toggle(m)} />
                      {m.excluded ? t("model.excluded") : t("model.used")}
                    </label>
                  ) : m.excluded ? (
                    t("model.excluded")
                  ) : (
                    t("model.used")
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
