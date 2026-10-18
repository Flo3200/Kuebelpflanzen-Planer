// Reports from the field (plant heavier/bigger, path different, customer absent, damage): apply or dismiss.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtDate, fmtNumber, t } from "../../i18n";

interface Deviation {
  id: string;
  kind: string;
  status: string;
  note: string | null;
  values: Record<string, number>;
  order_id: string;
  order_number: string | null;
  plant_id: string | null;
  plant_number: number | null;
  plant: Record<string, number | null> | null;
  reported_by: string | null;
  reported_at: string;
  photos: { id: string; url: string }[];
}

export function DeviationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const auth = useAuth();
  const [status, setStatus] = useState<"open" | "applied" | "dismissed">("open");
  const q = useQuery({ queryKey: ["deviations", status], queryFn: () => api.get<Deviation[]>("/api/deviations", { status }) });
  const decide = async (d: Deviation, action: "apply" | "dismiss") => {
    try {
      await api.post(`/api/deviations/${d.id}/decide`, { action });
      toast({ text: t(action === "apply" ? "deviations.applied" : "deviations.dismissed") });
      qc.invalidateQueries({ queryKey: ["deviations"] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <>
      <PageHeader title={t("deviations.title")} description={t("deviations.description")} />
      <Tabs
        value={status}
        onChange={setStatus}
        items={(["open", "applied", "dismissed"] as const).map((s) => ({ key: s, label: t(`deviations.status.${s}`) }))}
      />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {q.data && q.data.length === 0 && <Empty title={t("deviations.empty")} />}
      <div className="stack">
        {(q.data ?? []).map((d) => (
          <Card
            key={d.id}
            title={
              <span className="row" style={{ gap: 8 }}>
                <Badge tone={d.kind === "damage" ? "red" : d.kind === "customer_absent" ? "amber" : "terra"}>{t(`deviations.kinds.${d.kind}`)}</Badge>
                <Link to={`/betrieb/auftraege/${d.order_id}`}>{d.order_number}</Link>
                {d.plant_number != null && <span>· #{d.plant_number}</span>}
              </span>
            }
            actions={<span className="small muted">{t("deviations.by", { name: d.reported_by ?? "–", at: fmtDate(d.reported_at, true) })}</span>}
          >
            {d.note && <p>{d.note}</p>}
            {Object.keys(d.values).length > 0 && (
              <table className="table small" style={{ maxWidth: 480 }}>
                <thead>
                  <tr>
                    <th>{t("deviations.value")}</th>
                    <th className="num">{t("deviations.before")}</th>
                    <th className="num">{t("deviations.reported")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(d.values).map(([k, v]) => (
                    <tr key={k}>
                      <td>{t(`driverapp.values.${k}`)}</td>
                      <td className="num">{d.plant?.[k] != null ? fmtNumber(d.plant[k] as number, 1) : "–"}</td>
                      <td className="num">{fmtNumber(v, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {d.photos.length > 0 && (
              <div className="row" style={{ gap: 8 }}>
                {d.photos.map((p) => (
                  <a key={p.id} href={p.url} target="_blank" rel="noreferrer">
                    <img src={p.url} alt="" style={{ width: 120, height: 90, objectFit: "cover", borderRadius: 8 }} />
                  </a>
                ))}
              </div>
            )}
            {d.status === "open" && auth.has("orders.write") && (
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={() => decide(d, "apply")}>
                  {t(`deviations.apply_${["plant_heavier", "plant_bigger", "path_different", "customer_absent"].includes(d.kind) ? d.kind : "other"}`)}
                </button>
                <button className="btn ghost" onClick={() => decide(d, "dismiss")}>
                  {t("deviations.dismiss")}
                </button>
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
