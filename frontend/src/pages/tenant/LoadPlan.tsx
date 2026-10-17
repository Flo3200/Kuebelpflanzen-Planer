import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { ErrorBox, PageHeader, Spinner, useToast } from "../../components/ui";
import { LoadPlanView, type TourHead } from "../../components/loadplan/LoadPlanView";
import type { LoadPlanPayload } from "../../components/loadplan/types";
import { fmtDate, t } from "../../i18n";
import { useState } from "react";

interface LoadPlanResponse {
  tour: TourHead & { plan_id: string; trip_no: number };
  plan: LoadPlanPayload | null;
}

export function LoadPlanPage() {
  const { id } = useParams();
  const auth = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ["load-plan", id], queryFn: () => api.get<LoadPlanResponse>(`/api/tours/${id}/load-plan`) });
  const recompute = async () => {
    setBusy(true);
    try {
      const r = await api.post<LoadPlanResponse>(`/api/tours/${id}/load-plan`);
      qc.setQueryData(["load-plan", id], r);
      qc.invalidateQueries({ queryKey: ["plan", r.tour.plan_id] });
      toast({ text: r.tour.load_status === "ok" ? t("loadplan.recomputed_ok") : t("loadplan.recomputed_failed"), tone: r.tour.load_status === "ok" ? undefined : "error" });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  const d = q.data;
  return (
    <>
      <PageHeader
        eyebrow={t("loadplan.eyebrow")}
        title={d ? `${t("loadplan.title")} · ${d.tour.label}` : t("loadplan.title")}
        description={d ? `${fmtDate(d.tour.date)}${d.tour.trip_no > 1 ? ` · ${t("planning.trip", { n: d.tour.trip_no })}` : ""}` : undefined}
        actions={
          <Link className="btn ghost" to="/betrieb/planung">
            ← {t("loadplan.back")}
          </Link>
        }
      />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {d && (
        <LoadPlanView
          tour={d.tour}
          plan={d.plan}
          actions={
            auth.has("planning.write") && (
              <button className="btn secondary" onClick={recompute} disabled={busy}>
                {busy ? t("loadplan.computing") : t("loadplan.recompute")}
              </button>
            )
          }
        />
      )}
    </>
  );
}
