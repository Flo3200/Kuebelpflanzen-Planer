// Generic master-data page: table, create dialog, detail dialog with form, object settings and extra tabs.
import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { t } from "../i18n";
import { EntityForm, EntityTable } from "./EntityForm";
import { SettingsEditor } from "./SettingsEditor";
import { ConfirmButton, Empty, ErrorBox, Modal, PageHeader, Spinner, Tabs, useToast } from "./ui";

export type ExtraTab = { key: string; label: string; render: (row: any, refresh: () => void) => ReactNode };

export function ResourcePage(props: {
  entity: string;
  url: string;
  title: string;
  description?: string;
  columns: string[];
  render?: Record<string, (row: any) => ReactNode>;
  labels?: Record<string, string>;
  settingsScope?: string;
  settingsGroups?: string[];
  extraTabs?: ExtraTab[];
  createDefaults?: Record<string, any>;
  emptyText?: string;
  formFields?: string[];
  headerExtra?: ReactNode;
  /** shown between the page header and the table */
  intro?: ReactNode;
  filter?: (row: any) => boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<any | null>(null);
  const [tab, setTab] = useState("form");
  const [q, setQ] = useState("");
  const list = useQuery({ queryKey: [props.url, q], queryFn: () => api.get<any[]>(props.url, { q: q || undefined }) });
  const refresh = () => qc.invalidateQueries({ queryKey: [props.url] });
  const rows = (list.data ?? []).filter(props.filter ?? (() => true));

  const tabs = [
    { key: "form", label: t("resource.tab_data") },
    ...(props.settingsScope ? [{ key: "settings", label: t("resource.tab_settings") }] : []),
    ...(props.extraTabs ?? []).map((x) => ({ key: x.key, label: x.label })),
  ];

  return (
    <>
      <PageHeader
        title={props.title}
        description={props.description}
        actions={
          <>
            {props.headerExtra}
            <input className="input" style={{ width: 220 }} placeholder={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
            <button className="btn" onClick={() => setCreating(true)}>
              {t("common.create")}
            </button>
          </>
        }
      />
      {props.intro}
      {list.isLoading && <Spinner />}
      <ErrorBox error={list.error} />
      {list.data && rows.length === 0 && <Empty title={props.title} text={props.emptyText ?? t("resource.empty")} />}
      {rows.length > 0 && (
        <EntityTable
          entity={props.entity}
          rows={rows}
          columns={props.columns}
          render={props.render}
          labels={props.labels}
          onRowClick={(row) => {
            setSelected(row);
            setTab("form");
          }}
        />
      )}
      {creating && (
        <Modal title={`${props.title}: ${t("common.create")}`} onClose={() => setCreating(false)} wide>
          <EntityForm
            entity={props.entity}
            initial={props.createDefaults}
            fields={props.formFields}
            submitLabel={t("common.create")}
            onCancel={() => setCreating(false)}
            onSubmit={async (values) => {
              const row = await api.post(props.url, { ...(props.createDefaults ?? {}), ...values });
              refresh();
              setCreating(false);
              setSelected(row);
              toast({ text: t("common.saved") });
            }}
          />
        </Modal>
      )}
      {selected && (
        <Modal title={selected.name ?? selected.display_name ?? props.title} onClose={() => setSelected(null)} wide>
          <Tabs value={tab} onChange={setTab} items={tabs} />
          {tab === "form" && (
            <EntityForm
              key={selected.id + (selected.updated_at ?? "")}
              entity={props.entity}
              initial={selected}
              fields={props.formFields}
              onSubmit={async (values) => {
                const row = await api.patch(`${props.url}/${selected.id}`, values);
                setSelected(row);
                refresh();
                toast({ text: t("common.saved") });
              }}
              extra={
                <div className="row">
                  <ConfirmButton
                    onConfirm={async () => {
                      await api.del(`${props.url}/${selected.id}`);
                      setSelected(null);
                      refresh();
                    }}
                  >
                    {t("common.delete")}
                  </ConfirmButton>
                </div>
              }
            />
          )}
          {tab === "settings" && props.settingsScope && (
            <div>
              <p className="muted small">{t("resource.settings_hint")}</p>
              <SettingsEditor scope={props.settingsScope} objectId={selected.id} compact onlyGroups={props.settingsGroups} />
            </div>
          )}
          {props.extraTabs?.map((x) => (tab === x.key ? <div key={x.key}>{x.render(selected, refresh)}</div> : null))}
        </Modal>
      )}
    </>
  );
}
