import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Badge, Card, Kpi, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtMinutes, fmtMoney, fmtNumber, t } from "../../i18n";
import { StatusBadge } from "./Orders";

export function coverageTone(pct: number | null | undefined): "green" | "amber" | "red" | undefined {
  if (pct == null) return undefined;
  return pct >= 120 ? "green" : pct >= 100 ? "amber" : "red";
}

export function PricingPage() {
  const [tab, setTab] = useState<"overview" | "settings" | "weights">("overview");
  return (
    <>
      <PageHeader
        title={t("pricing.title")}
        description={t("pricing.description")}
        actions={
          <Link className="btn ghost" to="/betrieb/formeln">
            {t("pricing.to_formulas")}
          </Link>
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "overview", label: t("pricing.tab_overview") },
          { key: "settings", label: t("pricing.tab_settings") },
          { key: "weights", label: t("pricing.tab_weights") },
        ]}
      />
      {tab === "overview" && <Overview />}
      {tab === "settings" && <SettingsEditor scope="tenant" onlyGroups={["pricing", "costs", "time", "team", "weight"]} compact />}
      {tab === "weights" && <WeightCalibration />}
    </>
  );
}

function Overview() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["pricing-overview"], queryFn: () => api.get<any>("/api/pricing/overview") });
  if (q.isLoading) return <Spinner />;
  const { rows, totals } = q.data;
  return (
    <div className="stack lg">
      <div className="grid cols-4">
        <Kpi label={t("pricing.revenue_gross")} value={fmtMoney(totals.gross)} />
        <Kpi label={t("pricing.self_cost")} value={fmtMoney(totals.self_cost)} />
        <Kpi label={t("pricing.coverage")} value={totals.coverage_pct != null ? `${fmtNumber(totals.coverage_pct)} %` : "–"} sub={t("pricing.coverage_help")} />
        <Kpi label={t("pricing.labour")} value={fmtMinutes(totals.labour_min)} />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("orders.number")}</th>
              <th>{t("orders.customer")}</th>
              <th>{t("common.status")}</th>
              <th className="num">{t("orders.labour")}</th>
              <th className="num">{t("pricing.price_gross")}</th>
              <th className="num">{t("pricing.self_cost")}</th>
              <th className="num">{t("pricing.coverage")}</th>
              <th className="num">{t("pricing.coverage_after_plan")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/betrieb/auftraege/${r.id}`)}>
                <td className="num">{r.number}</td>
                <td>{r.customer}</td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td className="num">{fmtMinutes(r.labour_min)}</td>
                <td className="num">{fmtMoney(r.gross)}</td>
                <td className="num">{fmtMoney(r.self_cost)}</td>
                <td className="num">{r.coverage_pct != null ? <Badge tone={coverageTone(r.coverage_pct)}>{fmtNumber(r.coverage_pct)} %</Badge> : "–"}</td>
                <td className="num">{r.plan_coverage_pct != null ? <Badge tone={coverageTone(r.plan_coverage_pct)}>{fmtNumber(r.plan_coverage_pct)} %</Badge> : <span className="faint">–</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WeightCalibration() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["weight-calibration"], queryFn: () => api.get<any>("/api/weights/calibration") });
  if (q.isLoading) return <Spinner />;
  const d = q.data;
  return (
    <Card title={t("pricing.weights_title")}>
      <p className="muted">{t("pricing.weights_text")}</p>
      {d.proposed == null ? (
        <div className="alert">{t("pricing.weights_too_few", { n: d.n })}</div>
      ) : (
        <div className="stack">
          <dl className="dl">
            <dt>{t("pricing.weighed_plants")}</dt>
            <dd className="num">{d.n}</dd>
            <dt>{t("pricing.factor_current")}</dt>
            <dd className="num">{fmtNumber(d.current, 3)}</dd>
            <dt>{t("pricing.factor_proposed")}</dt>
            <dd className="num">{fmtNumber(d.proposed, 3)}</dd>
            <dt>{t("pricing.mae")}</dt>
            <dd className="num">
              {fmtNumber(d.mae_before_kg, 1)} kg → {fmtNumber(d.mae_after_kg, 1)} kg
            </dd>
          </dl>
          <div>
            <button
              className="btn"
              onClick={async () => {
                await api.post("/api/weights/calibration/apply");
                qc.invalidateQueries();
                toast({ text: t("pricing.weights_applied") });
              }}
            >
              {t("pricing.apply_factor")}
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
