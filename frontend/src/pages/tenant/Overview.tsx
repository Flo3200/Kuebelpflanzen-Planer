import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Botanical } from "../../components/Botanical";
import { Card, Kpi } from "../../components/ui";
import { fmtMoney, fmtNumber, t } from "../../i18n";

type Dashboard = {
  season: number;
  counts: Record<string, number>;
  orders_by_status: Record<string, number>;
  plants_total: number;
  plants_picked_up: number;
  drafts_pending: number;
  planned_tours: number;
  revenue_quoted: number | null;
  storage: { used_m2: number; capacity_m2: number; pct: number | null; warn: boolean } | null;
  next_tours: { id: string; date: string; label: string; stops: number }[];
};

export function TenantOverviewPage() {
  const { me, mod } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard"), retry: false });
  const d = q.data;
  const name = me?.user?.name?.split(" ")[0] ?? me?.label ?? "";
  return (
    <>
      <div className="hero">
        <Botanical variant="citrus" style={{ right: 20, top: -40, width: 300 }} strokeWidth={1.2} />
        <Botanical variant="fern" style={{ right: 260, bottom: -80, width: 180 }} />
        <div className="xs" style={{ textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--sage-400)" }}>
          {me?.tenant?.name} · {t("tenant.season", { year: d?.season ?? new Date().getFullYear() })}
        </div>
        <h1 style={{ marginTop: 6 }}>{t("tenant.welcome", { name })}</h1>
        <p>{t("dashboard.intro")}</p>
      </div>
      <div className="grid cols-4" style={{ marginBottom: 24 }}>
        <Kpi
          label={t("dashboard.plants")}
          value={fmtNumber(d?.plants_total)}
          sub={d ? t("dashboard.picked_up", { n: fmtNumber(d.plants_picked_up) }) : undefined}
        />
        <Kpi label={t("dashboard.orders")} value={fmtNumber(d?.counts?.pickup_orders)} sub={d ? t("dashboard.confirmed", { n: fmtNumber(d.orders_by_status?.confirmed ?? 0) }) : undefined} />
        <Kpi label={t("dashboard.drafts")} value={fmtNumber(d?.drafts_pending)} sub={<Link to="/betrieb/posteingang">{t("nav.inbox")}</Link>} />
        {mod("storage") ? (
          <Kpi
            label={t("dashboard.storage")}
            value={d?.storage?.pct != null ? `${fmtNumber(d.storage.pct)} %` : "–"}
            sub={d?.storage ? `${fmtNumber(d.storage.used_m2, 1)} / ${fmtNumber(d.storage.capacity_m2, 0)} m²` : undefined}
          />
        ) : (
          <Kpi label={t("dashboard.planned_tours")} value={fmtNumber(d?.planned_tours)} sub={<Link to="/betrieb/planung">{t("nav.planning")}</Link>} />
        )}
      </div>
      {mod("storage") && d?.storage?.warn && <div className="alert warn" style={{ marginBottom: 24 }}>{t("dashboard.storage_warn")}</div>}
      <div className="grid cols-2">
        <Card title={t("dashboard.status_title")}>
          <div className="stack" style={{ gap: 8 }}>
            {Object.entries(d?.orders_by_status ?? {}).map(([status, n]) => (
              <div key={status} className="row between">
                <span>{t(`orders.status.${status}`)}</span>
                <span className="num">{fmtNumber(n)}</span>
              </div>
            ))}
            {d && d.revenue_quoted != null && <div className="divider" />}
            {d && d.revenue_quoted != null && (
              <div className="row between">
                <span className="muted">{t("dashboard.revenue_quoted")}</span>
                <span className="num">{fmtMoney(d.revenue_quoted)}</span>
              </div>
            )}
          </div>
        </Card>
        <Card title={t("dashboard.next_tours")} actions={<Link to="/betrieb/planung">{t("nav.planning")}</Link>}>
          {(d?.next_tours ?? []).length === 0 && <p className="muted">{t("dashboard.no_tours")}</p>}
          <div className="stack" style={{ gap: 8 }}>
            {(d?.next_tours ?? []).map((tour) => (
              <div key={tour.id} className="row between">
                <span>{tour.label}</span>
                <span className="small muted num">{t("dashboard.stops", { n: tour.stops })}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
