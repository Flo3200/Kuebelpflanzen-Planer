import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Badge, Card, Kpi, useToast } from "../../components/ui";
import { fmtDate, fmtMinutes, fmtMoney, fmtNumber, t, tMaybe } from "../../i18n";
import { OrderInvoices } from "../common/Billing";
import { coverageTone } from "./Pricing";

export function EstimateDetails({ orderId, estimate, onChange }: { orderId: string; estimate: any; onChange: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { mod } = useAuth();
  const billing = mod("customer_billing");
  const quotes = useQuery({ queryKey: ["quotes", orderId], queryFn: () => api.get<any[]>(`/api/orders/${orderId}/quotes`), enabled: billing });
  const e = estimate;
  const price = e.price ?? {};
  const costs = e.costs ?? {};
  const plan = e.plan_costs;
  const createQuote = async () => {
    try {
      const q = await api.post(`/api/orders/${orderId}/quote`);
      qc.invalidateQueries({ queryKey: ["quotes", orderId] });
      onChange();
      window.open(q.url, "_blank");
    } catch (err) {
      toast({ text: (err as Error).message, tone: "error" });
    }
  };
  const byTeam = Object.entries(e.durations_by_team ?? {}).map(([m, d]) => [Number(m), d as number] as const);
  return (
    <div className="stack lg">
      {e.error && <div className="alert error">{e.error}</div>}
      {(e.warnings ?? []).length > 0 && (
        <div className="alert warn">
          {(e.warnings as string[]).map((w) => {
            const [code, arg] = w.split(":");
            return <div key={w}>{t(`estimate.warnings.${code}`, { n: arg })}</div>;
          })}
        </div>
      )}
      <div className="grid cols-4">
        <Kpi label={t("estimate.team")} value={t("estimate.persons", { n: e.team_size })} />
        <Kpi label={t("estimate.duration")} value={fmtMinutes(e.duration_min)} sub={t("estimate.planned_with", { m: fmtMinutes(e.planning_duration_min) })} />
        <Kpi label={t("estimate.labour")} value={fmtMinutes(e.labour_min)} sub={t("estimate.labour_help")} />
        {billing ? (
          <Kpi
            label={t("estimate.price")}
            value={fmtMoney(price.gross)}
            sub={price.coverage_pct != null ? <Badge tone={coverageTone(price.coverage_pct)}>{t("estimate.coverage", { pct: fmtNumber(price.coverage_pct) })}</Badge> : undefined}
          />
        ) : (
          <Kpi label={t("estimate.self_cost")} value={fmtMoney(plan?.self_cost ?? costs.self_cost)} sub={plan ? t("orders.cost_from_plan") : t("orders.cost_estimated")} />
        )}
      </div>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Card title={t("estimate.plants_title")}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("plants.number")}</th>
                  <th className="num">{t("plants.weight")}</th>
                  <th className="num">{t("estimate.crew")}</th>
                  <th>{t("estimate.reasons")}</th>
                  <th className="num">{t("estimate.work")}</th>
                </tr>
              </thead>
              <tbody>
                {(e.plants ?? []).map((p: any) => (
                  <tr key={p.id}>
                    <td className="num">#{p.number}</td>
                    <td className="num">{fmtNumber(p.weight)} kg</td>
                    <td className="num">
                      {p.crew}
                      {p.needed > p.crew && <span className="xs" style={{ color: "var(--danger)" }}> ({p.needed})</span>}
                    </td>
                    <td>
                      <div className="chip-list">
                        {(p.reasons ?? []).map((r: string) => (
                          <Badge key={r} tone={r === "max_size" ? "red" : r === "equipment" ? "green" : undefined}>
                            {tMaybe(`estimate.reason.${r}`) ?? r}
                          </Badge>
                        ))}
                        {p.equipment && <Badge tone="blue">{p.equipment}</Badge>}
                        {p.narrow && <Badge tone="amber">{t("estimate.reason.narrow_time")}</Badge>}
                      </div>
                    </td>
                    <td className="num">{fmtNumber(p.work, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="xs muted" style={{ marginTop: 8 }}>{t("estimate.work_help")}</p>
        </Card>
        <div className="stack lg">
          <Card title={t("estimate.team_variants")}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("estimate.team")}</th>
                    <th className="num">{t("estimate.duration")}</th>
                    <th className="num">{t("estimate.labour")}</th>
                  </tr>
                </thead>
                <tbody>
                  {byTeam.map(([m, d]) => (
                    <tr key={m} style={m === e.team_size ? { fontWeight: 600 } : undefined}>
                      <td>{t("estimate.persons", { n: m })}</td>
                      <td className="num">{fmtMinutes(d)}</td>
                      <td className="num">{fmtMinutes(d * m)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={billing ? t("estimate.costs_title") : t("estimate.costs_title_logistics")}>
            <dl className="dl">
              <dt>{t("estimate.cost_labour")}</dt>
              <dd className="num">{fmtMoney(costs.labour)}</dd>
              <dt>{t("estimate.cost_drive_labour")}</dt>
              <dd className="num">{fmtMoney(costs.drive_labour)}</dd>
              <dt>{t("estimate.cost_vehicle")}</dt>
              <dd className="num">{fmtMoney(costs.vehicle)}</dd>
              <dt>{t("estimate.cost_equipment")}</dt>
              <dd className="num">{fmtMoney(costs.equipment)}</dd>
              <dt>{t("estimate.cost_custom")}</dt>
              <dd className="num">
                {fmtMoney(costs.custom ?? 0)}
                {(costs.custom_items ?? []).length > 0 && (
                  <div className="xs muted">{costs.custom_items.map((x: any) => `${x.name} ${fmtMoney(x.amount)}`).join(" · ")}</div>
                )}
              </dd>
              <dt>{t("estimate.self_cost")}</dt>
              <dd className="num">
                <strong>{fmtMoney(costs.self_cost)}</strong>
              </dd>
              {billing && (
                <>
                  <dt>{t("estimate.target_price")}</dt>
                  <dd className="num">{fmtMoney(costs.target_price_net)}</dd>
                  <dt>{t("estimate.price_net")}</dt>
                  <dd className="num">{fmtMoney(price.net)}</dd>
                </>
              )}
              <dt>{t("estimate.distance")}</dt>
              <dd className="num">
                {e.distance_km != null ? `${fmtNumber(e.distance_km, 1)} km` : "–"} · {t("estimate.drive_share", { km: fmtNumber(e.drive?.share_km, 1), min: fmtMinutes(e.drive?.share_min) })}
              </dd>
              {plan && (
                <>
                  <dt>{t("estimate.plan_self_cost")}</dt>
                  <dd className="num">
                    {fmtMoney(plan.self_cost)}
                    {billing && (
                      <>
                        {" "}· <Badge tone={coverageTone(plan.coverage_pct)}>{fmtNumber(plan.coverage_pct)} %</Badge>
                      </>
                    )}
                  </dd>
                </>
              )}
            </dl>
            <p className="xs muted" style={{ marginTop: 8 }}>
              {t("estimate.formula_info", { name: e.formula?.time?.name, v: e.formula?.time?.version, q: Math.round((e.formula?.quantile ?? 0.8) * 100) })} · {fmtDate(e.computed_at, true)}
            </p>
          </Card>
          {billing && (
          <Card
            title={t("estimate.quotes")}
            actions={
              <button className="btn small" onClick={createQuote}>
                {t("estimate.create_quote")}
              </button>
            }
          >
            {(quotes.data ?? []).length === 0 && <p className="muted small">{t("estimate.no_quotes")}</p>}
            <div className="stack" style={{ gap: 6 }}>
              {(quotes.data ?? []).map((q) => (
                <div key={q.id} className="row between">
                  <span className="small">
                    {q.number} · {fmtDate(q.created_at)} · {fmtMoney(q.gross_eur)}
                  </span>
                  <a className="btn small ghost" href={q.url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                </div>
              ))}
            </div>
          </Card>
          )}
          {billing && <OrderInvoices orderId={orderId} />}
        </div>
      </div>
    </div>
  );
}
