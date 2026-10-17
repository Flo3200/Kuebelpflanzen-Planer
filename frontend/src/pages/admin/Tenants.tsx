import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { EntityForm, EntityTable } from "../../components/EntityForm";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Badge, Card, Empty, ErrorBox, Kpi, Modal, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtNumber, t } from "../../i18n";

export function AdminTenantsPage() {
  const q = useQuery({ queryKey: ["admin-tenants"], queryFn: () => api.get<any[]>("/api/admin/tenants") });
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  return (
    <>
      <PageHeader
        title={t("admin.tenants_title")}
        description={t("admin.tenants_description")}
        actions={
          <button className="btn" onClick={() => setCreating(true)}>
            {t("admin.new_tenant")}
          </button>
        }
      />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {q.data && q.data.length === 0 && <Empty title={t("admin.tenants_title")} text={t("admin.tenants_description")} />}
      {q.data && q.data.length > 0 && (
        <EntityTable
          entity="tenant"
          rows={q.data}
          columns={["name", "slug", "city", "status", "is_demo"]}
          onRowClick={(row) => navigate(`/admin/betriebe/${row.id}`)}
          render={{
            status: (r) => <Badge tone={r.status === "active" ? "green" : "red"}>{t(`admin.status_${r.status}`)}</Badge>,
            is_demo: (r) => (r.is_demo ? <Badge tone="blue">{t("admin.demo")}</Badge> : null),
          }}
        />
      )}
      {creating && <CreateTenantModal onClose={() => setCreating(false)} />}
    </>
  );
}

function CreateTenantModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ name: "", city: "", owner_name: "", owner_email: "", owner_password: "" });
  const [error, setError] = useState<unknown>(null);
  const create = useMutation({
    mutationFn: () =>
      api.post("/api/admin/tenants", {
        tenant: { name: form.name, city: form.city || null },
        owner: form.owner_email ? { name: form.owner_name || form.owner_email, email: form.owner_email, password: form.owner_password } : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-tenants"] });
      toast({ text: t("admin.tenant_created") });
      onClose();
    },
    onError: setError,
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal
      title={t("admin.new_tenant")}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn" disabled={!form.name || create.isPending} onClick={() => create.mutate()}>
            {t("common.create")}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <div className="field">
          <label htmlFor="tn">{t("admin.tenant_name")} *</label>
          <input id="tn" className="input" value={form.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label htmlFor="tc">{t("fields_common.city")}</label>
          <input id="tc" className="input" value={form.city} onChange={set("city")} />
        </div>
        <div className="field">
          <label htmlFor="on">{t("admin.owner_name")}</label>
          <input id="on" className="input" value={form.owner_name} onChange={set("owner_name")} />
        </div>
        <div className="field">
          <label htmlFor="oe">{t("admin.owner_email")}</label>
          <input id="oe" className="input" type="email" value={form.owner_email} onChange={set("owner_email")} />
        </div>
        <div className="field">
          <label htmlFor="op">{t("admin.owner_password")}</label>
          <input id="op" className="input" type="password" minLength={10} value={form.owner_password} onChange={set("owner_password")} />
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <ErrorBox error={error} />
      </div>
    </Modal>
  );
}

export function AdminTenantDetailPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState<"profile" | "settings">("profile");
  const tenants = useQuery({ queryKey: ["admin-tenants"], queryFn: () => api.get<any[]>("/api/admin/tenants") });
  const stats = useQuery({ queryKey: ["admin-tenant-stats", id], queryFn: () => api.get<Record<string, number>>(`/api/admin/tenants/${id}/stats`) });
  const tenant = tenants.data?.find((x) => x.id === id);
  if (tenants.isLoading) return <Spinner />;
  if (!tenant) return <ErrorBox error={new Error(t("errors.not_found_page"))} />;

  const openAs = async () => {
    await api.post("/api/auth/act-as", { tenant_id: id });
    await qc.invalidateQueries();
    navigate("/betrieb");
  };
  const toggleStatus = async () => {
    await api.patch(`/api/admin/tenants/${id}`, { status: tenant.status === "active" ? "suspended" : "active" });
    qc.invalidateQueries({ queryKey: ["admin-tenants"] });
  };

  return (
    <>
      <PageHeader
        eyebrow={t("admin.tenants_title")}
        title={tenant.name}
        description={[tenant.city, tenant.slug].filter(Boolean).join(" · ")}
        actions={
          <>
            <button className="btn ghost" onClick={toggleStatus}>
              {tenant.status === "active" ? t("admin.suspend") : t("admin.activate")}
            </button>
            <button className="btn" onClick={openAs}>
              {t("admin.open_as_tenant")}
            </button>
          </>
        }
      />
      <div className="grid cols-4" style={{ marginBottom: 24 }}>
        {Object.entries(stats.data ?? {}).map(([k, v]) => (
          <Kpi key={k} label={t(`stats.${k}`)} value={fmtNumber(v)} />
        ))}
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "profile", label: t("admin.tenant_profile") },
          { key: "settings", label: t("admin.tenant_settings") },
        ]}
      />
      {tab === "profile" && (
        <Card>
          <EntityForm
            key={tenant.id + tenant.updated_at}
            entity="tenant"
            initial={tenant}
            onSubmit={async (values) => {
              await api.patch(`/api/admin/tenants/${id}`, values);
              qc.invalidateQueries({ queryKey: ["admin-tenants"] });
              toast({ text: t("common.saved") });
            }}
          />
        </Card>
      )}
      {tab === "settings" && <SettingsEditor scope="tenant" tenantId={id} canEditAdminOnly />}
    </>
  );
}
