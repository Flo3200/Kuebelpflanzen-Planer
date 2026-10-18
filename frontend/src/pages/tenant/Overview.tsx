// Logistics dashboard (package F): today and tomorrow, open drafts, orders that could not be planned,
// costs of the week and the charts. Storage, offers and invoices only with their modules.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Botanical } from "../../components/Botanical";
import { AccuracyChart, CostPerDayChart, CostPerPlantChart, hm, TourTimelineChart, UtilisationChart } from "../../components/charts";
import { Badge, Card, Kpi } from "../../components/ui";
import { fmtDate, fmtMoney, fmtNumber, t } from "../../i18n";
import { hintText, reasonText } from "./hints";

type TourRow = { id: string; vehicle: string; members: string[]; trip_no: number; start_min: number; end_min: number; depot_start_min: number | null; depot_end_min: number | null; stops: number; plants: number; status: string };
type Dashboard = {
  season: number;
  plants_total: number;
  plants_picked_up: number;
  drafts_pending: number;
  revenue_quoted: number | null;
  storage: { used_m2: number; capacity_m2: number; pct: number | null; warn: boolean } | null;
  logistics?: {
    today: { date: string; tours: TourRow[] };
    tomorrow: { date: string; tours: TourRow[] };
    open_drafts: { orders: number; vehicles: number };
    unplanned: { order_id: string; number: string; reason: string; customer?: string; hints?: { code: string; params: any }[]; direction: string }[];
    unplanned_total: number;
    week: { start: string; cost: number; plants: number; cost_per_plant: number | null; tours: number };
  };
};

function DayCard({ title, day }: { title: string; day: { date: string; tours: TourRow[] } }) {
  return (
    <Card title={`${title} · ${fmtDate(day.date)}`} actions={<Link to="/betrieb/planung">{t("nav.planning")}</Link>}>
      {day.tours.length === 0 && <p className="muted small">{t("dashboard.no_tours_day")}</p>}
      <div className="stack" style={{ gap: 8 }}>
        {day.tours.map((x) => (
          <div key={x.id} className="row between top">
            <div>
              <div>
                {x.vehicle}
                {x.trip_no > 1 && <span className="xs muted"> · {t("planning.trip", { n: x.trip_no })}</span>}
                {x.status === "done" && <Badge tone="green"> ✓</Badge>}
              </div>
              <div className="xs muted">{x.members.join(", ")}</div>
            </div>
            <div className="small num" style={{ textAlign: "right" }}>
              {hm(x.start_min)}–{hm(x.end_min)} · {t("dashboard.stops", { n: x.stops })}
              {x.depot_start_min != null && <div className="xs muted">{t("dashboard.unload_at", { from: hm(x.depot_start_min), to: hm(x.depot_end_min) })}</div>}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function TenantOverviewPage() {
  const { me, mod } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard"), retry: false });
  const [day, setDay] = useState<string | null>(null);
  const charts = useQuery({ queryKey: ["dashboard-charts", day], queryFn: () => api.get<any>("/api/dashboard/charts", { start: isoDay(new Date()), days: 14, day: day ?? undefined }) });
  const d = q.data;
  const L = d?.logistics;
  const c = charts.data;
  const name = me?.user?.name?.split(" ")[0] ?? me?.label ?? "";
  const drafts = (L?.open_drafts.orders ?? 0) + (L?.open_drafts.vehicles ?? 0);
  return (
    <>
      <div className="hero">
        <Botanical variant="citrus" style={{ right: 20, top: -40, width: 300 }} strokeWidth={1.2} />
        <Botanical variant="fern" style={{ right: 260, bottom: -80, width: 180 }} />
        <div className="xs" style={{ textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--sage-400)" }}>
          {me?.tenant?.name} · {t("tenant.season", { year: d?.season ?? new Date().getFullYear() })}
        </div>
        <h1 style={{ marginTop: 6 }}>{t("tenant.welcome", { name })}</h1>
        <p>
          {t("dashboard.intro_logistics")}
          {d ? ` ${t("dashboard.season_plants", { n: fmtNumber(d.plants_total), done: fmtNumber(d.plants_picked_up) })}` : ""}
        </p>
      </div>
      <div className="grid cols-4" style={{ marginBottom: 24 }}>
        <Kpi label={t("dashboard.tours_today")} value={fmtNumber(L?.today.tours.length ?? 0)} sub={L ? t("dashboard.tours_tomorrow", { n: L.tomorrow.tours.length }) : undefined} />
        <Kpi
          label={t("dashboard.drafts")}
          value={fmtNumber(drafts)}
          sub={
            <span>
              <Link to="/betrieb/posteingang">{t("dashboard.drafts_orders", { n: L?.open_drafts.orders ?? 0 })}</Link> ·{" "}
              <Link to="/betrieb/fahrzeuge">{t("dashboard.drafts_vehicles", { n: L?.open_drafts.vehicles ?? 0 })}</Link>
            </span>
          }
        />
        <Kpi label={t("dashboard.unplanned")} value={fmtNumber(L?.unplanned_total ?? 0)} sub={<Link to="/betrieb/planung">{t("nav.planning")}</Link>} />
        <Kpi
          label={t("dashboard.week_costs")}
          value={fmtMoney(L?.week.cost ?? 0)}
          sub={L?.week.cost_per_plant != null ? t("dashboard.per_plant", { c: fmtMoney(L.week.cost_per_plant), n: fmtNumber(L.week.plants) }) : t("dashboard.week_no_tours")}
        />
      </div>
      {mod("storage") && d?.storage && (
        <div className="grid cols-4" style={{ marginBottom: 24 }}>
          <Kpi label={t("dashboard.storage")} value={d.storage.pct != null ? `${fmtNumber(d.storage.pct)} %` : "–"} sub={`${fmtNumber(d.storage.used_m2, 1)} / ${fmtNumber(d.storage.capacity_m2, 0)} m²`} />
          {d.storage.warn && <div className="alert warn" style={{ gridColumn: "span 3" }}>{t("dashboard.storage_warn")}</div>}
        </div>
      )}
      {L && (
        <div className="grid cols-3" style={{ marginBottom: 24, alignItems: "start" }}>
          <DayCard title={t("dashboard.today")} day={L.today} />
          <DayCard title={t("dashboard.tomorrow")} day={L.tomorrow} />
          <Card title={t("dashboard.unplanned_title")} actions={<Link to="/betrieb/planung">{t("nav.planning")}</Link>}>
            {L.unplanned.length === 0 && <p className="muted small">{t("dashboard.all_planned")}</p>}
            <div className="stack" style={{ gap: 8 }}>
              {L.unplanned.map((u) => (
                <div key={u.order_id}>
                  <div className="row between">
                    <Link to={`/betrieb/auftraege/${u.order_id}`}>
                      {u.number} {u.customer ? `· ${u.customer}` : ""}
                    </Link>
                    <Badge tone="amber">{reasonText(u.reason)}</Badge>
                  </div>
                  {u.hints?.[0] && <div className="xs muted">→ {hintText(u.hints[0])}</div>}
                </div>
              ))}
              {L.unplanned_total > L.unplanned.length && <div className="xs muted">{t("dashboard.more", { n: L.unplanned_total - L.unplanned.length })}</div>}
            </div>
          </Card>
        </div>
      )}
      {c && (
        <div className="grid cols-2" style={{ alignItems: "start" }}>
          <TourTimelineChart day={c.day} days={c.tour_days} onDay={setDay} tours={c.timeline} unload={c.unload} />
          <UtilisationChart data={c.utilisation} />
          <CostPerDayChart data={c.costs} />
          <CostPerPlantChart data={c.costs} />
          <AccuracyChart data={c.accuracy} />
        </div>
      )}
      {mod("customer_billing") && d?.revenue_quoted != null && (
        <p className="small muted" style={{ marginTop: 16 }}>
          {t("dashboard.revenue_quoted")}: {fmtMoney(d.revenue_quoted)}
        </p>
      )}
    </>
  );
}
