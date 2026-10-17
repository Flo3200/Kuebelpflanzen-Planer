import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { EntityForm, EntityTable } from "../../components/EntityForm";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Badge, ConfirmButton, Modal, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { t } from "../../i18n";

export function SpeciesPage({ admin = false }: { admin?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<any | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"data" | "settings">("data");
  const list = useQuery({ queryKey: ["species", q], queryFn: () => api.get<any[]>("/api/species", { q: q || undefined }) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["species"] });
  return (
    <>
      <PageHeader
        title={t("nav.species")}
        description={admin ? t("species.admin_description") : t("species.description")}
        actions={
          <>
            <input className="input" style={{ width: 220 }} placeholder={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
            <button className="btn" onClick={() => setCreating(true)}>
              {t("species.new")}
            </button>
          </>
        }
      />
      {list.isLoading && <Spinner />}
      {list.data && (
        <EntityTable
          entity="species"
          rows={list.data}
          columns={["name", "botanical_name", "crown_shape", "crown_density", "frost_sensitivity"]}
          labels={{ name: t("common.name") }}
          render={{
            name: (r) => (
              <span>
                {r.name} {!admin && (r.is_global ? <Badge>{t("species.global")}</Badge> : r.is_override ? <Badge tone="terra">{t("species.override")}</Badge> : <Badge tone="green">{t("species.own")}</Badge>)}
              </span>
            ),
          }}
          onRowClick={(r) => {
            setSelected(r);
            setTab("data");
          }}
        />
      )}
      {creating && (
        <Modal title={t("species.new")} onClose={() => setCreating(false)} wide>
          <EntityForm
            entity="species"
            onCancel={() => setCreating(false)}
            onSubmit={async (v) => {
              await api.post("/api/species", v);
              setCreating(false);
              refresh();
            }}
          />
        </Modal>
      )}
      {selected && (
        <Modal title={selected.name} onClose={() => setSelected(null)} wide>
          {!admin && selected.is_global && <div className="alert" style={{ marginBottom: 16 }}>{t("species.override_hint")}</div>}
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { key: "data", label: t("resource.tab_data") },
              { key: "settings", label: t("resource.tab_settings") },
            ]}
          />
          {tab === "data" && (
            <EntityForm
              key={selected.id + selected.updated_at}
              entity="species"
              initial={selected}
              extra={
                (selected.is_override || (!selected.is_global && !admin) || admin) && (
                  <ConfirmButton
                    onConfirm={async () => {
                      await api.del(`/api/species/${selected.id}`);
                      setSelected(null);
                      refresh();
                    }}
                  >
                    {selected.is_override ? t("species.reset_override") : t("common.delete")}
                  </ConfirmButton>
                )
              }
              onSubmit={async (v) => {
                const row = await api.patch(`/api/species/${selected.id}`, v);
                setSelected(row);
                refresh();
                toast({ text: row.is_override && selected.is_global ? t("species.override_created") : t("common.saved") });
              }}
            />
          )}
          {tab === "settings" && <SettingsEditor scope="species" objectId={selected.id} compact />}
        </Modal>
      )}
    </>
  );
}
