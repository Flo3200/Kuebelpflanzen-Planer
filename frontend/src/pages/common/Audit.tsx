import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Empty, ErrorBox, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtDate, t, tMaybe } from "../../i18n";

type Entry = {
  id: string;
  actor_label: string | null;
  via: string;
  entity: string;
  entity_id: string | null;
  action: string;
  old_value: any;
  new_value: any;
  undoable: boolean;
  undone: boolean;
  created_at: string;
  batch_id: string | null;
};

function short(value: any): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "object" && "value" in value && Object.keys(value).length === 1) return short(value.value);
  const s = typeof value === "string" ? value : JSON.stringify(value);
  return s.length > 90 ? s.slice(0, 90) + " …" : s;
}

function describe(e: Entry, labels: Record<string, string>): string {
  if (e.entity === "setting" && e.entity_id) {
    const [scope, , key] = e.entity_id.split(":");
    return `${labels[key] ?? key} (${tMaybe(`scopes.${scope}`) ?? scope})`;
  }
  return `${tMaybe(`entities.${e.entity}`) ?? e.entity}`;
}

export function AuditPage({ platformOnly = false }: { platformOnly?: boolean }) {
  const [entity, setEntity] = useState("");
  const [page, setPage] = useState(0);
  const qc = useQueryClient();
  const toast = useToast();
  const limit = 50;
  const q = useQuery({
    queryKey: ["audit", entity, page, platformOnly],
    queryFn: () => api.get<{ total: number; items: Entry[] }>("/api/audit", { entity, limit, offset: page * limit, platform_only: platformOnly || undefined }),
  });
  const registry = useQuery({ queryKey: ["settings-registry"], queryFn: () => api.get<any>("/api/settings/registry"), staleTime: Infinity });
  const labels: Record<string, string> = {};
  registry.data?.settings.forEach((s: any) => (labels[s.key] = s.label));

  const undo = async (e: Entry) => {
    try {
      await api.post(`/api/audit/${e.id}/undo`);
      qc.invalidateQueries();
      toast({ text: t("settings.undone") });
    } catch (err) {
      toast({ text: (err as Error).message, tone: "error" });
    }
  };

  return (
    <>
      <PageHeader
        title={t("audit.title")}
        description={t("audit.description")}
        actions={
          <select className="input" style={{ width: 220 }} value={entity} onChange={(e) => (setEntity(e.target.value), setPage(0))} aria-label={t("audit.filter_entity")}>
            <option value="">{t("common.all")}</option>
            {["setting", "tenant", "user", "staff", "vehicle", "equipment", "customer", "order", "plant", "species", "formula", "draft", "plan"].map((x) => (
              <option key={x} value={x}>
                {tMaybe(`entities.${x}`) ?? x}
              </option>
            ))}
          </select>
        }
      />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {q.data && q.data.items.length === 0 && <Empty title={t("audit.empty")} />}
      {q.data && q.data.items.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("audit.when")}</th>
                  <th>{t("audit.who")}</th>
                  <th>{t("audit.via")}</th>
                  <th>{t("audit.what")}</th>
                  <th>{t("audit.change")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="num small">{fmtDate(e.created_at, true)}</td>
                    <td>{e.actor_label ?? "–"}</td>
                    <td>
                      <Badge tone={e.via === "settings_ai" ? "terra" : e.via === "agent" ? "blue" : undefined}>{t(`audit.via_labels.${e.via}`)}</Badge>
                    </td>
                    <td>
                      <div>{describe(e, labels)}</div>
                      <div className="xs muted">{tMaybe(`audit.actions.${e.action}`) ?? e.action}</div>
                    </td>
                    <td className="small mono">
                      {e.action === "create" ? short(e.new_value) : `${short(e.old_value)} → ${short(e.new_value)}`}
                    </td>
                    <td className="num">
                      {e.undone && <Badge>{t("audit.undone")}</Badge>}
                      {e.undoable && (
                        <button className="btn small ghost" onClick={() => undo(e)}>
                          {t("common.undo")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row between" style={{ marginTop: 12 }}>
            <span className="small muted">
              {page * limit + 1}–{Math.min((page + 1) * limit, q.data.total)} {t("common.from")} {q.data.total}
            </span>
            <div className="row">
              <button className="btn small ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
                {t("common.previous")}
              </button>
              <button className="btn small ghost" disabled={(page + 1) * limit >= q.data.total} onClick={() => setPage(page + 1)}>
                {t("common.next")}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
