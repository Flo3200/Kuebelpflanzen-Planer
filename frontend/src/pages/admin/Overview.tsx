import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Botanical } from "../../components/Botanical";
import { Card, Kpi } from "../../components/ui";
import { fmtNumber, t } from "../../i18n";
import type { Job } from "../common/Jobs";
import { JobStatus } from "../common/Jobs";

export function AdminOverviewPage() {
  const tenants = useQuery({ queryKey: ["admin-tenants"], queryFn: () => api.get<any[]>("/api/admin/tenants") });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<Job[]>("/api/jobs", { limit: 8 }) });
  const mode = useQuery({
    queryKey: ["settings", "platform", null, null],
    queryFn: () => api.get<any>("/api/settings", { scope: "platform" }),
  });
  const platformMode = mode.data?.values?.find((v: any) => v.key === "platform.mode")?.value;
  const active = tenants.data?.filter((x) => x.status === "active").length ?? 0;
  return (
    <>
      <div className="hero">
        <Botanical variant="olive" style={{ right: -40, top: -30, width: 520 }} strokeWidth={1.1} />
        <h1>{t("admin.overview_title")}</h1>
        <p>{t("admin.overview_description")}</p>
      </div>
      <div className="grid cols-4" style={{ marginBottom: 24 }}>
        <Kpi label={t("admin.tenants_title")} value={fmtNumber(tenants.data?.length)} sub={`${active} ${t("admin.status_active")}`} />
        <Kpi
          label={t("settings_labels.platform_mode")}
          value={platformMode === "production" ? t("settings_labels.production") : t("settings_labels.test")}
        />
        <Kpi label={t("nav.jobs")} value={fmtNumber(jobs.data?.filter((j) => j.status === "running" || j.status === "queued").length)} />
        <Kpi label={t("jobs.status.failed")} value={fmtNumber(jobs.data?.filter((j) => j.status === "failed").length)} />
      </div>
      <div className="grid cols-2">
        <Card title={t("admin.tenants_title")} actions={<Link to="/admin/betriebe">{t("common.open")}</Link>}>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 8 }}>
            {(tenants.data ?? []).slice(0, 8).map((x) => (
              <li key={x.id} className="row between">
                <Link to={`/admin/betriebe/${x.id}`}>{x.name}</Link>
                <span className="small muted">{x.city}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={t("nav.jobs")} actions={<Link to="/admin/system">{t("common.open")}</Link>}>
          <div className="stack">
            {(jobs.data ?? []).slice(0, 6).map((j) => (
              <div key={j.id} className="row between top">
                <span className="small">{j.kind}</span>
                <JobStatus job={j} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
