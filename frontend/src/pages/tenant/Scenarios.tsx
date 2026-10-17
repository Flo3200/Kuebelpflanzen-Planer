import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../api/client";
import { Badge, Card, Empty, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtMinutes, fmtMoney, fmtNumber, t } from "../../i18n";

const PRESETS = ["plus_person", "minus_person", "plus_vehicle", "minus_vehicle", "plus_day", "minus_day", "teams_of_3"];

function Delta({ value, unit = "", invert = false, money = false }: { value: number | null | undefined; unit?: string; invert?: boolean; money?: boolean }) {
  if (value == null) return <span className="faint">–</span>;
  if (value === 0) return <span className="muted">±0</span>;
  const good = invert ? value > 0 : value < 0;
  const text = money ? fmtMoney(value) : `${fmtNumber(value, Number.isInteger(value) ? 0 : 1)}${unit}`;
  return <span style={{ color: good ? "var(--success)" : "var(--danger)", fontWeight: 560 }}>{value > 0 ? "+" : ""}{text}</span>;
}

export function ScenariosPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.get<any[]>("/api/plans") });
  const planId = params.get("plan") ?? plans.data?.find((p) => p.is_active)?.id ?? plans.data?.[0]?.id;
  const cmp = useQuery({
    queryKey: ["scenarios", planId],
    queryFn: () => api.get<any>(`/api/plans/${planId}/scenarios`),
    enabled: !!planId,
    refetchInterval: (q) => ((q.state.data?.variants ?? []).some((v: any) => v.status === "computing" || v.status === "draft") ? 2000 : false),
  });
  const [chosen, setChosen] = useState<string[]>(["plus_person", "plus_vehicle", "plus_day"]);
  const [custom, setCustom] = useState({ add_staff: 0, remove_staff: 0, days_delta: 0, team_size: "" });
  const run = async () => {
    const variants: any[] = chosen.map((preset) => ({ preset, name: t(`scenarios.presets.${preset}`) }));
    if (custom.add_staff || custom.remove_staff || custom.days_delta || custom.team_size) {
      variants.push({
        name: t("scenarios.custom"),
        scenario: { add_staff: custom.add_staff, remove_staff: custom.remove_staff, days_delta: custom.days_delta, ...(custom.team_size ? { team_size: Number(custom.team_size) } : {}) },
      });
    }
    await api.post(`/api/plans/${planId}/scenarios`, { variants });
    qc.invalidateQueries({ queryKey: ["scenarios", planId] });
    toast({ text: t("scenarios.started", { n: variants.length }) });
  };
  if (plans.isLoading) return <Spinner />;
  if (!planId) return <Empty title={t("scenarios.no_plan")} text={t("scenarios.no_plan_text")} />;
  const base = cmp.data?.base;
  const variants: any[] = cmp.data?.variants ?? [];
  const chart = [
    { name: t("scenarios.base"), cost: base?.kpis?.total_cost ?? 0, days: base?.kpis?.days_until_done ?? 0 },
    ...variants.filter((v) => v.status === "ready").map((v) => ({ name: v.name, cost: v.kpis.total_cost, days: v.kpis.days_until_done })),
  ];
  return (
    <>
      <PageHeader
        title={t("nav.scenarios")}
        description={t("scenarios.description")}
        actions={
          <select className="input" style={{ width: 260 }} value={planId} onChange={(e) => setParams({ plan: e.target.value })} aria-label={t("planning.plan")}>
            {(plans.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        }
      />
      <div className="stack lg">
        <Card title={t("scenarios.variants")}>
          <div className="row" style={{ flexWrap: "wrap", gap: 14 }}>
            {PRESETS.map((p) => (
              <label key={p} className="checkbox">
                <input type="checkbox" checked={chosen.includes(p)} onChange={(e) => setChosen(e.target.checked ? [...chosen, p] : chosen.filter((x) => x !== p))} />
                {t(`scenarios.presets.${p}`)}
              </label>
            ))}
          </div>
          <div className="divider" />
          <div className="row">
            <span className="small">{t("scenarios.custom")}:</span>
            <label className="small row" style={{ gap: 4 }}>
              {t("scenarios.add_staff")}
              <input className="input num" style={{ width: 60 }} type="number" min={0} value={custom.add_staff} onChange={(e) => setCustom({ ...custom, add_staff: Number(e.target.value) })} />
            </label>
            <label className="small row" style={{ gap: 4 }}>
              {t("scenarios.remove_staff")}
              <input className="input num" style={{ width: 60 }} type="number" min={0} value={custom.remove_staff} onChange={(e) => setCustom({ ...custom, remove_staff: Number(e.target.value) })} />
            </label>
            <label className="small row" style={{ gap: 4 }}>
              {t("scenarios.days_delta")}
              <input className="input num" style={{ width: 60 }} type="number" value={custom.days_delta} onChange={(e) => setCustom({ ...custom, days_delta: Number(e.target.value) })} />
            </label>
            <label className="small row" style={{ gap: 4 }}>
              {t("scenarios.team_size")}
              <input className="input num" style={{ width: 60 }} type="number" min={1} max={8} value={custom.team_size} onChange={(e) => setCustom({ ...custom, team_size: e.target.value })} />
            </label>
            <span className="grow" />
            <button className="btn" onClick={run}>
              {t("scenarios.run")}
            </button>
          </div>
        </Card>
        {base && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("scenarios.variant")}</th>
                  <th className="num">{t("planning.kpi_days")}</th>
                  <th className="num">{t("planning.kpi_cost")}</th>
                  <th className="num">{t("scenarios.cost_per_plant")}</th>
                  <th className="num">{t("planning.tab_unassigned")}</th>
                  <th className="num">{t("scenarios.overtime")}</th>
                  <th>{t("scenarios.marginal")}</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ fontWeight: 600 }}>
                  <td>
                    {t("scenarios.base")}: {base.name}
                  </td>
                  <td className="num">{fmtNumber(base.kpis?.days_until_done)}</td>
                  <td className="num">{fmtMoney(base.kpis?.total_cost)}</td>
                  <td className="num">{fmtMoney(base.kpis?.cost_per_plant)}</td>
                  <td className="num">{fmtNumber(base.kpis?.stops_unassigned)}</td>
                  <td className="num">{fmtMinutes(base.kpis?.overtime_min)}</td>
                  <td />
                </tr>
                {variants.map((v) => (
                  <tr key={v.id}>
                    <td>
                      {v.name} {v.status !== "ready" && <Badge tone={v.status === "failed" ? "red" : "blue"}>{t(`planning.status.${v.status}`)}</Badge>}
                    </td>
                    {v.status === "ready" ? (
                      <>
                        <td className="num">
                          {fmtNumber(v.kpis.days_until_done)} <Delta value={v.delta.days_until_done} />
                        </td>
                        <td className="num">
                          {fmtMoney(v.kpis.total_cost)} <Delta value={v.delta.total_cost} money />
                        </td>
                        <td className="num">
                          {fmtMoney(v.kpis.cost_per_plant)} <Delta value={v.delta.cost_per_plant} money />
                        </td>
                        <td className="num">
                          {fmtNumber(v.kpis.stops_unassigned)} <Delta value={v.delta.stops_unassigned} />
                        </td>
                        <td className="num">
                          {fmtMinutes(v.kpis.overtime_min)} <Delta value={v.delta.overtime_min} unit=" min" />
                        </td>
                        <td className="small">
                          {v.marginal.cost_per_day_saved != null && <div>{t("scenarios.cost_per_day_saved", { c: fmtMoney(v.marginal.cost_per_day_saved) })}</div>}
                          {v.marginal.cost_per_day_added != null && <div>{t("scenarios.cost_per_day_added", { c: fmtMoney(v.marginal.cost_per_day_added) })}</div>}
                          {v.marginal.cost_per_extra_stop != null && <div>{t("scenarios.cost_per_extra_stop", { c: fmtMoney(v.marginal.cost_per_extra_stop) })}</div>}
                        </td>
                      </>
                    ) : (
                      <td colSpan={6} className="small muted">
                        {v.job?.message ?? ""}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {chart.length > 1 && (
          <Card title={t("scenarios.chart")}>
            <div style={{ height: 320 }}>
              <ResponsiveContainer>
                <BarChart data={chart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="cost" tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="days" orientation="right" tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Legend />
                  <Bar yAxisId="cost" dataKey="cost" name={t("planning.kpi_cost")} fill="#2b5139" radius={[6, 6, 0, 0]} />
                  <Bar yAxisId="days" dataKey="days" name={t("planning.kpi_days")} fill="#c2693e" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
      </div>
    </>
  );
}
