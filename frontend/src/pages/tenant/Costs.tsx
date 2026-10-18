// Own cost items (package E): per nursery, vehicle or person, with a basis (km, hour, trip, day,
// month pro rata, plant). They flow into order estimates, tour costs and scenarios.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { EntityForm, EntityTable } from "../../components/EntityForm";
import { ResourcePage } from "../../components/ResourcePage";
import { ConfirmButton, Modal, useToast } from "../../components/ui";
import { fmtMoney, t } from "../../i18n";

function useNames() {
  const staff = useQuery({ queryKey: ["fk", "staff"], queryFn: () => api.get<any[]>("/api/staff") });
  const vehicles = useQuery({ queryKey: ["fk", "vehicle"], queryFn: () => api.get<any[]>("/api/vehicles") });
  return new Map([...(staff.data ?? []), ...(vehicles.data ?? [])].map((x) => [x.id, x.name]));
}

export function CostsPage() {
  const names = useNames();
  return (
    <ResourcePage
      entity="cost_item"
      url="/api/cost-items"
      title={t("costs.title")}
      description={t("costs.description")}
      columns={["name", "amount_eur", "basis", "vehicle_id", "active"]}
      labels={{ vehicle_id: t("costs.scope") }}
      createDefaults={{ basis: "per_day", active: true }}
      render={{
        amount_eur: (r) => fmtMoney(r.amount_eur),
        vehicle_id: (r) => (r.vehicle_id ? names.get(r.vehicle_id) ?? "?" : r.staff_id ? names.get(r.staff_id) ?? "?" : t("costs.whole_nursery")),
      }}
      emptyText={t("costs.empty")}
    />
  );
}

/** Tab on a vehicle or staff page: the own cost items of exactly this object. */
export function CostItemsFor({ field, id }: { field: "vehicle_id" | "staff_id"; id: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["/api/cost-items", field, id];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<any[]>("/api/cost-items", { filter: [`${field}=${id}`] }) });
  const [editing, setEditing] = useState<any | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["/api/cost-items"] });
  const fields = ["name", "amount_eur", "basis", "active", "notes"];
  return (
    <div className="stack">
      <p className="muted small">{t("costs.object_help")}</p>
      {(q.data ?? []).length > 0 && (
        <EntityTable
          entity="cost_item"
          rows={q.data ?? []}
          columns={["name", "amount_eur", "basis", "active"]}
          render={{ amount_eur: (r) => fmtMoney(r.amount_eur) }}
          onRowClick={(r) => setEditing(r)}
          actions={(r) => (
            <ConfirmButton
              onConfirm={async () => {
                await api.del(`/api/cost-items/${r.id}`);
                refresh();
              }}
            >
              {t("common.delete")}
            </ConfirmButton>
          )}
        />
      )}
      <div>
        <button className="btn secondary" onClick={() => setEditing({ basis: "per_day", active: true })}>
          {t("costs.add")}
        </button>
      </div>
      {editing && (
        <Modal title={editing.id ? editing.name : t("costs.add")} onClose={() => setEditing(null)}>
          <EntityForm
            entity="cost_item"
            initial={editing}
            fields={fields}
            onCancel={() => setEditing(null)}
            onSubmit={async (v) => {
              if (editing.id) await api.patch(`/api/cost-items/${editing.id}`, v);
              else await api.post("/api/cost-items", { ...v, [field]: id });
              setEditing(null);
              refresh();
              toast({ text: t("common.saved") });
            }}
          />
        </Modal>
      )}
    </div>
  );
}
