// Charts of the logistics dashboard (package F). Colours are the validated chart tokens
// (--chart-1 … --chart-4, fixed order), text stays in text tokens, every chart has a tooltip, a
// legend for two or more series and a table view (light-mode contrast of two slots is below 3:1).
import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate, fmtMoney, fmtNumber, t } from "../i18n";

export const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];
const AXIS = { fill: "var(--text-muted)", fontSize: 12 };
const TOOLTIP = {
  contentStyle: { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 13 },
  labelStyle: { color: "var(--text)" },
  itemStyle: { color: "var(--text)" },
  cursor: { fill: "var(--surface-2)" },
};

export function hm(min: number | null | undefined): string {
  if (min === null || min === undefined) return "–";
  const m = Math.round(min);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

const dayLabel = (d: string) => new Date(d + "T12:00:00").toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });

/** Card with a chart and a table view of the same numbers. */
export function ChartCard(props: { title: string; subtitle?: ReactNode; empty?: boolean; emptyText?: string; table: { head: string[]; rows: ReactNode[][] }; children: ReactNode; wide?: boolean }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="card" style={props.wide ? { gridColumn: "1 / -1" } : undefined}>
      <div className="card-head">
        <div>
          <h3>{props.title}</h3>
          {props.subtitle && <div className="xs muted">{props.subtitle}</div>}
        </div>
        {!props.empty && (
          <button className="btn small ghost" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}>
            {asTable ? t("charts.as_chart") : t("charts.as_table")}
          </button>
        )}
      </div>
      {props.empty ? (
        <p className="muted small">{props.emptyText ?? t("charts.no_data")}</p>
      ) : asTable ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {props.table.head.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {props.table.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} className={j > 0 ? "num" : undefined}>
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        props.children
      )}
    </section>
  );
}

type Util = { date: string; staff_pct: number | null; vehicles_pct: number | null; staff_used: number; staff_available: number; vehicles_used: number; vehicles_available: number };

export function UtilisationChart({ data }: { data: Util[] }) {
  const rows = data.filter((d) => d.staff_available || d.vehicles_available);
  const empty = !rows.some((d) => d.staff_used || d.vehicles_used);
  return (
    <ChartCard
      title={t("charts.utilisation")}
      subtitle={t("charts.utilisation_help")}
      empty={empty}
      table={{
        head: [t("common.date"), t("charts.staff"), t("charts.vehicles")],
        rows: rows.map((d) => [fmtDate(d.date), `${d.staff_used} / ${d.staff_available}`, `${d.vehicles_used} / ${d.vehicles_available}`]),
      }}
    >
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rows.map((d) => ({ ...d, label: dayLabel(d.date) }))} barGap={2} barCategoryGap="25%">
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} unit=" %" tick={AXIS} width={52} />
          <Tooltip
            {...TOOLTIP}
            formatter={(v: any, name: any, item: any) => {
              const p = item.payload as Util;
              return name === t("charts.staff")
                ? [`${fmtNumber(v)} % (${p.staff_used}/${p.staff_available})`, name]
                : [`${fmtNumber(v)} % (${p.vehicles_used}/${p.vehicles_available})`, name];
            }}
          />
          <Legend wrapperStyle={{ color: "var(--text-muted)", fontSize: 12 }} itemSorter={null} />
          <Bar dataKey="staff_pct" name={t("charts.staff")} fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={18} />
          <Bar dataKey="vehicles_pct" name={t("charts.vehicles")} fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

type CostDay = { date: string; cost: number; plants: number; cost_per_plant: number | null };

export function CostPerDayChart({ data }: { data: CostDay[] }) {
  const rows = data.filter((d) => d.cost > 0);
  return (
    <ChartCard
      title={t("charts.cost_per_day")}
      empty={!rows.length}
      table={{ head: [t("common.date"), t("charts.cost"), t("charts.plants")], rows: rows.map((d) => [fmtDate(d.date), fmtMoney(d.cost), fmtNumber(d.plants)]) }}
    >
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={rows.map((d) => ({ ...d, label: dayLabel(d.date) }))}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
          <YAxis tick={AXIS} width={64} tickFormatter={(v) => fmtMoney(v)} />
          <Tooltip {...TOOLTIP} formatter={(v: any) => [fmtMoney(v), t("charts.cost")]} />
          <Bar dataKey="cost" name={t("charts.cost")} fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function CostPerPlantChart({ data }: { data: CostDay[] }) {
  const rows = data.filter((d) => d.cost_per_plant != null);
  return (
    <ChartCard
      title={t("charts.cost_per_plant")}
      empty={!rows.length}
      table={{ head: [t("common.date"), t("charts.cost_per_plant_short")], rows: rows.map((d) => [fmtDate(d.date), fmtMoney(d.cost_per_plant)]) }}
    >
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows.map((d) => ({ ...d, label: dayLabel(d.date) }))}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
          <YAxis tick={AXIS} width={64} tickFormatter={(v) => fmtMoney(v)} />
          <Tooltip {...TOOLTIP} cursor={{ stroke: "var(--border-strong)" }} formatter={(v: any) => [fmtMoney(v), t("charts.cost_per_plant_short")]} />
          <Line dataKey="cost_per_plant" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function AccuracyChart({ data }: { data: { week: string; mape: number; n: number }[] }) {
  return (
    <ChartCard
      title={t("charts.accuracy")}
      subtitle={t("charts.accuracy_help")}
      empty={!data.length}
      emptyText={t("charts.no_measurements")}
      table={{ head: [t("charts.week"), t("charts.error"), t("charts.measurements")], rows: data.map((d) => [d.week, `${fmtNumber(d.mape, 1)} %`, fmtNumber(d.n)]) }}
    >
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="week" tick={AXIS} interval="preserveStartEnd" />
          <YAxis tick={AXIS} width={52} unit=" %" />
          <Tooltip {...TOOLTIP} cursor={{ stroke: "var(--border-strong)" }} formatter={(v: any, _n: any, item: any) => [`${fmtNumber(v, 1)} % (${item.payload.n} ${t("charts.measurements")})`, t("charts.error")]} />
          <Line dataKey="mape" stroke={SERIES[2]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

type TL = { id: string; vehicle: string; members: string[]; trip_no: number; start_min: number; end_min: number; depot_start_min: number | null; depot_end_min: number | null; stops: number; plants: number };

/** Tours of one day on a time axis, with the unloading windows at the depot. */
export function TourTimelineChart(props: {
  day: string | null;
  days: string[];
  onDay: (d: string) => void;
  tours: TL[];
  unload: { windows: any[]; curve: { min: number; n: number }[]; max_parallel: number };
}) {
  const { tours } = props;
  const lo = tours.length ? Math.floor(Math.min(...tours.map((x) => x.start_min)) / 60) * 60 : 7 * 60;
  const hi = tours.length ? Math.ceil(Math.max(...tours.map((x) => x.depot_end_min ?? x.end_min)) / 60) * 60 : 18 * 60;
  const span = Math.max(60, hi - lo);
  const pct = (m: number) => `${((m - lo) / span) * 100}%`;
  const wid = (a: number, b: number) => `${(Math.max(0, b - a) / span) * 100}%`;
  const hours = Array.from({ length: span / 60 + 1 }, (_, i) => lo + i * 60);
  return (
    <ChartCard
      wide
      title={t("charts.timeline")}
      subtitle={
        <span className="row" style={{ gap: 12 }}>
          {props.days.length > 0 && (
            <select className="input" style={{ width: 170, padding: "2px 8px" }} value={props.day ?? ""} onChange={(e) => props.onDay(e.target.value)} aria-label={t("common.date")}>
              {props.days.map((d) => (
                <option key={d} value={d}>
                  {fmtDate(d)}
                </option>
              ))}
            </select>
          )}
          {props.unload.max_parallel > 0 && <span>{t("charts.max_parallel", { n: props.unload.max_parallel })}</span>}
        </span>
      }
      empty={!tours.length}
      table={{
        head: [t("charts.vehicle"), t("charts.on_tour"), t("charts.unloading"), t("charts.stops")],
        rows: tours.map((x) => [`${x.vehicle} · ${x.members.join(", ")}`, `${hm(x.start_min)}–${hm(x.end_min)}`, x.depot_start_min != null ? `${hm(x.depot_start_min)}–${hm(x.depot_end_min)}` : "–", fmtNumber(x.stops)]),
      }}
    >
      <div className="stack" style={{ gap: 6 }}>
        <div style={{ position: "relative", marginLeft: 180, height: 16 }}>
          {hours.map((m) => (
            <span key={m} className="xs muted" style={{ position: "absolute", left: pct(m), transform: "translateX(-50%)" }}>
              {hm(m)}
            </span>
          ))}
        </div>
        {tours.map((x) => (
          <div key={x.id} className="row" style={{ gap: 0 }}>
            <div className="small" style={{ width: 180, paddingRight: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={x.members.join(", ")}>
              {x.vehicle}
              {x.trip_no > 1 && <span className="xs muted"> · {t("planning.trip", { n: x.trip_no })}</span>}
            </div>
            <div style={{ position: "relative", flex: 1, height: 26, background: "var(--surface-2)", borderRadius: 6 }}>
              <div
                title={`${t("charts.on_tour")} ${hm(x.start_min)}–${hm(x.end_min)} · ${x.stops} ${t("charts.stops")}`}
                style={{ position: "absolute", left: pct(x.start_min), width: wid(x.start_min, x.end_min), top: 4, bottom: 4, background: SERIES[0], borderRadius: 4 }}
              />
              {x.depot_start_min != null && x.depot_end_min != null && (
                <div
                  title={`${t("charts.unloading")} ${hm(x.depot_start_min)}–${hm(x.depot_end_min)}`}
                  style={{ position: "absolute", left: pct(x.depot_start_min), width: wid(x.depot_start_min, x.depot_end_min), minWidth: 4, top: 4, bottom: 4, background: SERIES[1], borderRadius: 4, boxShadow: "0 0 0 2px var(--surface-2)" }}
                />
              )}
            </div>
          </div>
        ))}
        {props.unload.curve.length > 0 && (
          <div className="row" style={{ gap: 0, marginTop: 4 }}>
            <div className="small muted" style={{ width: 180, paddingRight: 8 }}>
              {t("charts.at_depot")}
            </div>
            <div style={{ position: "relative", flex: 1, height: 26 }}>
              {props.unload.curve
                .filter((c) => c.n > 0)
                .map((c) => (
                  <div
                    key={c.min}
                    title={`${hm(c.min)}: ${t("charts.vehicles_unloading", { n: c.n })}`}
                    style={{
                      position: "absolute", left: pct(c.min), width: wid(c.min, c.min + 15), bottom: 0,
                      height: `${(c.n / Math.max(1, props.unload.max_parallel)) * 100}%`, background: SERIES[1], opacity: 0.85,
                      borderRadius: "3px 3px 0 0", boxShadow: "0 0 0 1px var(--surface)",
                    }}
                  />
                ))}
            </div>
          </div>
        )}
        <div className="row xs muted" style={{ gap: 16, marginLeft: 180 }}>
          <span className="row" style={{ gap: 6 }}>
            <span style={{ width: 12, height: 8, borderRadius: 2, background: SERIES[0], display: "inline-block" }} /> {t("charts.on_tour")}
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span style={{ width: 12, height: 8, borderRadius: 2, background: SERIES[1], display: "inline-block" }} /> {t("charts.unloading")}
          </span>
        </div>
      </div>
    </ChartCard>
  );
}
