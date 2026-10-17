import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Empty, ErrorBox, PageHeader, Progress, Spinner } from "../../components/ui";
import { fmtDate, t, tMaybe } from "../../i18n";

export type Job = {
  id: string;
  kind: string;
  status: string;
  progress: number;
  message: string | null;
  error: string | null;
  result: any;
  created_at: string;
  finished_at: string | null;
  tenant_id: string | null;
};

const TONES: Record<string, "green" | "red" | "amber" | "blue" | undefined> = {
  done: "green",
  failed: "red",
  running: "blue",
  queued: "amber",
};

export function JobStatus({ job }: { job: Job }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ gap: 8 }}>
        <Badge tone={TONES[job.status]}>{t(`jobs.status.${job.status}`)}</Badge>
        {job.message && <span className="small muted">{job.message}</span>}
      </div>
      {(job.status === "running" || job.status === "queued") && <Progress value={job.progress} />}
      {job.error && <span className="small" style={{ color: "var(--danger)" }}>{job.error}</span>}
    </div>
  );
}

/** Polls a job until it is finished. */
export function useJob(jobId: string | null | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "done" || s === "failed" || s === "cancelled" ? false : 1000;
    },
  });
}

export function JobsPage({ admin = false }: { admin?: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<Job[]>("/api/jobs"), refetchInterval: 3000 });
  return (
    <>
      <PageHeader title={admin ? t("admin.system_title") : t("jobs.title")} description={admin ? t("admin.system_description") : undefined} />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {q.data && q.data.length === 0 && <Empty title={t("jobs.empty")} />}
      {q.data && q.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("jobs.kind")}</th>
                <th>{t("common.status")}</th>
                <th>{t("jobs.created")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.map((j) => (
                <tr key={j.id}>
                  <td>{tMaybe(`jobs.kinds.${j.kind.replace(".", "_")}`) ?? j.kind}</td>
                  <td style={{ minWidth: 260 }}>
                    <JobStatus job={j} />
                  </td>
                  <td className="small num">{fmtDate(j.created_at, true)}</td>
                  <td className="num">
                    {(j.status === "queued" || j.status === "running") && (
                      <button
                        className="btn small ghost"
                        onClick={async () => {
                          await api.post(`/api/jobs/${j.id}/cancel`);
                          qc.invalidateQueries({ queryKey: ["jobs"] });
                        }}
                      >
                        {t("jobs.cancel")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
