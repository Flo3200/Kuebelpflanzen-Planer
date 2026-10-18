// Load plan of one tour: 3D view, top view and the loading steps (also used by the driver app).
import { lazy, Suspense, useMemo, useState } from "react";
import { fmtNumber, t, tMaybe } from "../../i18n";
import { Badge, Card, Spinner, Tabs } from "../ui";
import { LoadPlanTop } from "./LoadPlanTop";
import type { LoadPlanPayload, LPPlacement } from "./types";
import { stopColor } from "./types";

// three.js is large: only loaded when the 3D tab is opened
const LoadPlan3D = lazy(() => import("./LoadPlan3D").then((m) => ({ default: m.LoadPlan3D })));

export interface TourHead {
  id: string;
  label: string;
  date: string;
  load_status: "unknown" | "ok" | "failed";
  load_message: string | null;
  direction?: string;
  vehicle?: string;
  trailer?: string | null;
  stops: { position: number; order_id: string; number: string; customer: string; city: string }[];
}

export function LoadStatusBadge({ status }: { status: string }) {
  const tone = status === "ok" ? "green" : status === "failed" ? "red" : undefined;
  return <Badge tone={tone}>{t(`loadplan.status.${status}`)}</Badge>;
}

function Metrics({ plan }: { plan: LoadPlanPayload }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {plan.spaces.map((sp) => {
        const m = plan.metrics.spaces?.[sp.id];
        if (!m) return null;
        return (
          <div key={sp.id} className="small">
            <strong>{sp.name}</strong>
            <div className="loadplan-metrics">
              <span>{t("loadplan.m_weight")}</span>
              <span className="num">
                {fmtNumber(m.weight)} / {fmtNumber(sp.payload)} kg
              </span>
              {m.axle_front != null && (
                <>
                  <span>{t("loadplan.m_axles")}</span>
                  <span className="num">
                    {fmtNumber(m.axle_front)} / {fmtNumber(m.axle_rear)} kg
                  </span>
                </>
              )}
              {m.tongue_load != null && (
                <>
                  <span>{t("loadplan.m_tongue")}</span>
                  <span className="num">{fmtNumber(m.tongue_load)} kg</span>
                </>
              )}
              <span>{t("loadplan.m_lateral")}</span>
              <span className="num">{fmtNumber((m.lateral_offset ?? 0) * 100)} %</span>
              <span>{t("loadplan.m_length")}</span>
              <span className="num">{fmtNumber((m.used_length ?? 0) * 100)} %</span>
              <span>{t("loadplan.m_floor")}</span>
              <span className="num">{fmtNumber((m.floor_use ?? 0) * 100)} %</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function violationText(v: string): string {
  const [code, ref] = v.split(":");
  const text = tMaybe(`loadplan.violations.${code}`) ?? code;
  return code === "sensitive_behind_heavy" || code === "order_blocked" ? `${text} (#${ref})` : text;
}

export function LoadPlanView(props: {
  tour: TourHead;
  plan: LoadPlanPayload | null;
  compact?: boolean;
  actions?: React.ReactNode;
  notes?: Record<string, string>; // extra line per plant, e.g. its place in the storage
}) {
  const { tour, plan } = props;
  const [view, setView] = useState<"3d" | "top" | "steps">(props.compact ? "steps" : "top");
  const [step, setStep] = useState<number | null>(null);
  const steps = useMemo(() => (plan ? [...plan.placements].sort((a, b) => a.sequence - b.sequence) : []), [plan]);
  const stopsByPos = useMemo(() => new Map(tour.stops.map((s) => [s.position, s])), [tour]);
  const pick = (p: LPPlacement) => setStep(p.sequence);
  const current = step != null ? steps.find((p) => p.sequence === step) : undefined;
  const idx = current ? steps.indexOf(current) : -1;
  const go = (d: number) => {
    if (!steps.length) return;
    const next = idx < 0 ? (d > 0 ? 0 : steps.length - 1) : Math.max(0, Math.min(steps.length - 1, idx + d));
    setStep(steps[next].sequence);
  };

  if (!plan || !plan.spaces?.length) {
    return (
      <Card title={t("loadplan.title")} actions={props.actions}>
        <p className="muted">{tour.load_message || t("loadplan.none")}</p>
      </Card>
    );
  }

  return (
    <div className="stack lg">
      <div className="row between wrap">
        <div className="row wrap">
          <LoadStatusBadge status={tour.load_status} />
          {tour.load_status !== "ok" && tour.load_message && <span className="small" style={{ color: "var(--danger)" }}>{tour.load_message}</span>}
          <span className="small muted">{t(`loadplan.direction.${tour.direction ?? "pickup"}`)}</span>
        </div>
        <div className="row">{props.actions}</div>
      </div>

      <div className="row wrap" style={{ gap: 6 }}>
        {tour.stops.map((s) => (
          <span key={s.position} className="badge" style={{ background: stopColor(s.position), color: "#fff" }} title={`${s.customer}, ${s.city}`}>
            {s.position}. {s.number}
          </span>
        ))}
      </div>

      <Tabs
        value={view}
        onChange={setView}
        items={[
          { key: "top", label: t("loadplan.view_top") },
          { key: "3d", label: t("loadplan.view_3d") },
          { key: "steps", label: t("loadplan.view_steps") },
        ]}
      />

      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn secondary small" onClick={() => go(-1)} disabled={idx === 0}>
          ← {t("loadplan.prev")}
        </button>
        <button className="btn secondary small" onClick={() => go(1)} disabled={idx === steps.length - 1}>
          {t("loadplan.next")} →
        </button>
        <button className="btn ghost small" onClick={() => setStep(null)} disabled={step == null}>
          {t("loadplan.show_all")}
        </button>
        <span className="small muted">
          {current ? t("loadplan.step_of", { n: idx + 1, total: steps.length }) : t("loadplan.steps_total", { n: steps.length })}
        </span>
      </div>

      {current && (
        <div className="alert info loadplan-current">
          <strong>
            {idx + 1}. {current.label}
          </strong>{" "}
          · {t("loadplan.from_stop", { n: current.stop_position, number: stopsByPos.get(current.stop_position)?.number ?? "" })}
          <div>{current.instruction}</div>
          {props.notes?.[current.plant_id] && <div className="small">{props.notes[current.plant_id]}</div>}
          {current.secure && <Badge tone="amber">{t("loadplan.secure")}</Badge>}
        </div>
      )}

      <div className={props.compact ? "stack" : "loadplan-grid"}>
        <div>
          {view === "3d" && (
            <Suspense fallback={<Spinner />}>
              <LoadPlan3D plan={plan} step={step} onPick={pick} height={props.compact ? 320 : 460} />
              <p className="xs muted">{t("loadplan.hint_3d")}</p>
            </Suspense>
          )}
          {view === "top" && <LoadPlanTop plan={plan} step={step} onPick={pick} />}
          {view === "steps" && (
            <ol className="loadplan-steps">
              {steps.map((p, i) => (
                <li key={p.plant_id} className={p.sequence === step ? "current" : ""} onClick={() => setStep(p.sequence)}>
                  <span className="dot" style={{ background: stopColor(p.stop_position) }}>
                    {i + 1}
                  </span>
                  <div>
                    <div>
                      <strong>{p.label}</strong> <span className="xs muted">· {fmtNumber(p.dims.weight)} kg · {t(`loadplan.orientation.${p.orientation}`)}</span>
                    </div>
                    <div className="small">{p.instruction}</div>
                    {props.notes?.[p.plant_id] && <div className="small muted">{props.notes[p.plant_id]}</div>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
        {!props.compact && (
          <div className="stack">
            <Card title={t("loadplan.metrics")}>
              <Metrics plan={plan} />
            </Card>
            <AiInfo plan={plan} />
            {(plan.unplaced.length > 0 || plan.violations.length > 0) && (
              <Card title={t("loadplan.problems")}>
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  {plan.unplaced.map((u) => (
                    <li key={u.plant_id}>
                      {u.label ?? `#${u.number}`}: {t(`loadplan.reasons.${u.reason}`)}
                    </li>
                  ))}
                  {plan.violations.map((v) => (
                    <li key={v}>{violationText(v)}</li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Package G: how the AI proposal was used (start solution, comparison with the rules). */
function AiInfo({ plan }: { plan: LoadPlanPayload }) {
  const m = plan.metrics;
  if (!m.mode && !m.ai_error) return null;
  const row = (key: string, r: Record<string, any>) => (
    <tr key={key}>
      <td>{t(`loadplan.ai.${key}`)}</td>
      <td className="num">{r.ok ? "✓" : "✕"}</td>
      <td className="num">{r.unplaced}</td>
      <td className="num">{r.violations}</td>
      <td className="num">{r.score}</td>
      <td className="num">{r.seconds} s</td>
    </tr>
  );
  return (
    <Card title={t("loadplan.ai.title")}>
      {m.ai_error && <p className="small muted">{t("loadplan.ai.error")}</p>}
      {m.start && (
        <p className="small muted">
          {t("loadplan.ai.start", { valid: m.start.positions_valid, n: m.start.positions_proposed, model: m.ai?.model ?? "" })}
        </p>
      )}
      {m.compare && (
        <div className="table-wrap">
          <table className="table small">
            <thead>
              <tr>
                <th />
                <th className="num">{t("loadplan.ai.ok")}</th>
                <th className="num">{t("loadplan.ai.unplaced")}</th>
                <th className="num">{t("loadplan.ai.violations")}</th>
                <th className="num">{t("loadplan.ai.score")}</th>
                <th className="num">{t("loadplan.ai.time")}</th>
              </tr>
            </thead>
            <tbody>
              {row("rules", m.compare.rules)}
              {row("ai_start", m.compare.ai_start)}
            </tbody>
          </table>
        </div>
      )}
      {m.compare && <p className="small">{t("loadplan.ai.winner", { w: t(`loadplan.ai.${m.compare.winner}`) })}</p>}
      <p className="xs muted">{t("loadplan.ai.checked")}</p>
    </Card>
  );
}
