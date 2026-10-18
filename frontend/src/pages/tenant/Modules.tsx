// Modules (package C): shelves and fixtures reusable in several vehicles, and tow vehicle + trailer
// combinations.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ResourcePage } from "../../components/ResourcePage";
import { Card, useToast } from "../../components/ui";
import { fmtNumber, t } from "../../i18n";

export function ModulesPage() {
  const assign = useQuery({ queryKey: ["module-assignments"], queryFn: () => api.get<Record<string, string[]>>("/api/module-assignments") });
  const vehicles = useQuery({ queryKey: ["fk", "vehicle"], queryFn: () => api.get<any[]>("/api/vehicles") });
  const names = new Map((vehicles.data ?? []).map((v) => [v.id, v.name]));
  return (
    <>
      <ResourcePage
        entity="vehicle_module"
        url="/api/vehicle-modules"
        title={t("modules.title")}
        description={t("modules.description")}
        columns={["name", "kind", "length_cm", "depth_cm", "height_cm", "weight_kg", "id"]}
        labels={{ id: t("modules.vehicles") }}
        createDefaults={{ kind: "shelf", x_cm: 0, y_cm: 0, length_cm: 120, depth_cm: 40, height_cm: 90, clearance_cm: 60, max_load_kg: 60, blocks_floor: true, weight_kg: 0 }}
        render={{ id: (r) => (assign.data?.[r.id] ?? []).map((v) => names.get(v) ?? "?").join(", ") || <span className="faint">–</span> }}
        emptyText={t("modules.empty")}
      />
      <div style={{ marginTop: 24 }}>
        <Combinations />
      </div>
    </>
  );
}

function Combinations() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["vehicle-combinations"], queryFn: () => api.get<any>("/api/vehicle-combinations") });
  if (!q.data) return null;
  const set = async (vehicleId: string, trailerId: string) => {
    try {
      await api.put(`/api/vehicles/${vehicleId}/trailer`, { trailer_id: trailerId || null });
      qc.invalidateQueries({ queryKey: ["vehicle-combinations"] });
      qc.invalidateQueries({ queryKey: ["/api/vehicles"] });
      toast({ text: t("common.saved") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <Card title={t("modules.combinations")}>
      <p className="muted small">{t("modules.combinations_help")}</p>
      {q.data.trailers.length === 0 && <p className="small muted">{t("modules.no_trailers")}</p>}
      {q.data.trailers.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("modules.tow_vehicle")}</th>
                <th>{t("modules.trailer")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.tow_vehicles.map((v: any) => (
                <tr key={v.id}>
                  <td>
                    {v.name} <span className="xs muted">· {t("modules.licence", { l: v.required_licence })}</span>
                  </td>
                  <td>
                    <select className="input" style={{ width: 260 }} value={v.trailer_id ?? ""} onChange={(e) => set(v.id, e.target.value)} aria-label={t("modules.trailer")}>
                      <option value="">{t("modules.no_trailer")}</option>
                      {q.data.trailers.map((tr: any) => (
                        <option key={tr.id} value={tr.id}>
                          {tr.name} ({fmtNumber(tr.payload_kg)} kg)
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Tab on a vehicle: which modules it carries. */
export function VehicleModulesTab({ vehicle }: { vehicle: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const all = useQuery({ queryKey: ["/api/vehicle-modules"], queryFn: () => api.get<any[]>("/api/vehicle-modules") });
  const mine = useQuery({ queryKey: ["vehicle-modules", vehicle.id], queryFn: () => api.get<any[]>(`/api/vehicles/${vehicle.id}/modules`) });
  const [chosen, setChosen] = useState<string[] | null>(null);
  const current = chosen ?? (mine.data ?? []).map((m) => m.id);
  const save = async () => {
    await api.put(`/api/vehicles/${vehicle.id}/modules`, { module_ids: current });
    setChosen(null);
    qc.invalidateQueries({ queryKey: ["vehicle-modules", vehicle.id] });
    qc.invalidateQueries({ queryKey: ["module-assignments"] });
    toast({ text: t("common.saved") });
  };
  return (
    <div className="stack">
      <p className="muted small">{t("modules.vehicle_help")}</p>
      {(all.data ?? []).length === 0 && <p className="small muted">{t("modules.empty")}</p>}
      {(all.data ?? []).map((m) => (
        <label key={m.id} className="checkbox">
          <input type="checkbox" checked={current.includes(m.id)} onChange={(e) => setChosen(e.target.checked ? [...current, m.id] : current.filter((x) => x !== m.id))} />
          <span>
            {m.name} <span className="xs muted">· {t(`modules.kinds.${m.kind}`)} · {fmtNumber(m.length_cm)} × {fmtNumber(m.depth_cm)} cm</span>
          </span>
        </label>
      ))}
      {chosen && (
        <div>
          <button className="btn" onClick={save}>
            {t("common.save")}
          </button>
        </div>
      )}
    </div>
  );
}
