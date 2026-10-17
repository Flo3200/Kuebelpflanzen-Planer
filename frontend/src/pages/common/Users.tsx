import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Badge, ConfirmButton, ErrorBox, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtDate, t } from "../../i18n";

type User = {
  id: string;
  name: string;
  email: string | null;
  role: string;
  is_active: boolean;
  extra_permissions: string[];
  revoked_permissions: string[];
  totp_enabled: boolean;
  has_pin: boolean;
  last_login_at: string | null;
};

export function UsersPage({ admin = false }: { admin?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/api/users") });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const roles = admin ? ["admin"] : me?.role === "owner" || me?.role === "admin" ? ["owner", "dispatcher", "driver"] : ["dispatcher", "driver"];

  const del = async (u: User) => {
    await api.del(`/api/users/${u.id}`);
    qc.invalidateQueries({ queryKey: ["users"] });
  };
  const toggle = async (u: User) => {
    await api.patch(`/api/users/${u.id}`, { is_active: !u.is_active });
    qc.invalidateQueries({ queryKey: ["users"] });
  };
  const pin = async (u: User) => {
    const value = window.prompt(t("users.pin"));
    if (!value) return;
    try {
      const r = await api.post(`/api/users/${u.id}/pin`, { pin: value });
      toast({ text: t("users.pin_set", { code: r.tenant_code }) });
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const makeLink = async (u: User) => {
    const r = await api.post(`/api/users/${u.id}/driver-link`);
    setLink(r.url);
  };

  return (
    <>
      <PageHeader
        title={admin ? t("admin.admins_title") : t("users.title")}
        description={admin ? undefined : t("users.description")}
        actions={
          <button className="btn" onClick={() => setCreating(true)}>
            {admin ? t("admin.new_admin") : t("users.new")}
          </button>
        }
      />
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} />
      {q.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.name")}</th>
                <th>{t("users.email")}</th>
                <th>{t("users.role")}</th>
                <th>{t("common.status")}</th>
                <th>{t("users.last_login")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.name} {u.totp_enabled && <Badge tone="green">2FA</Badge>}
                  </td>
                  <td>{u.email ?? <span className="faint">–</span>}</td>
                  <td>
                    {t(`users.roles.${u.role}`)}
                    {(u.extra_permissions.length > 0 || u.revoked_permissions.length > 0) && (
                      <span className="xs muted"> (+{u.extra_permissions.length}/−{u.revoked_permissions.length})</span>
                    )}
                  </td>
                  <td>
                    <Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? t("users.active") : t("users.inactive")}</Badge>
                  </td>
                  <td className="small num">{fmtDate(u.last_login_at, true)}</td>
                  <td className="num">
                    <div className="row end" style={{ gap: 4 }}>
                      {u.role === "driver" && (
                        <>
                          <button className="btn small ghost" onClick={() => pin(u)}>
                            {t("users.set_pin")}
                          </button>
                          <button className="btn small ghost" onClick={() => makeLink(u)}>
                            {t("users.driver_link")}
                          </button>
                        </>
                      )}
                      {u.role === "dispatcher" && (
                        <button className="btn small ghost" onClick={() => setEditing(u)}>
                          {t("users.permissions")}
                        </button>
                      )}
                      {u.id !== me?.user?.id && (
                        <>
                          <button className="btn small ghost" onClick={() => toggle(u)}>
                            {u.is_active ? t("admin.suspend") : t("admin.activate")}
                          </button>
                          <ConfirmButton onConfirm={() => del(u)}>{t("common.delete")}</ConfirmButton>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <CreateUserModal roles={roles} onClose={() => setCreating(false)} />}
      {editing && <PermissionsModal user={editing} onClose={() => setEditing(null)} />}
      {link && (
        <Modal title={t("users.driver_link")} onClose={() => setLink(null)}>
          <p className="muted">{t("users.driver_link_text")}</p>
          <div className="row">
            <input className="input mono" readOnly value={link} onFocus={(e) => e.target.select()} />
            <button className="btn" onClick={() => navigator.clipboard.writeText(link).then(() => toast({ text: t("common.copied") }))}>
              {t("common.copy")}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function CreateUserModal({ roles, onClose }: { roles: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", role: roles.includes("dispatcher") ? "dispatcher" : roles[0], password: "" });
  const m = useMutation({
    mutationFn: () =>
      api.post("/api/users", {
        name: form.name,
        email: form.email || null,
        role: form.role,
        password: form.role === "driver" ? null : form.password || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });
  return (
    <Modal
      title={t("users.new")}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn" disabled={!form.name || m.isPending} onClick={() => m.mutate()}>
            {t("common.create")}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <div className="field">
          <label htmlFor="un">{t("common.name")} *</label>
          <input id="un" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        {roles.length > 1 && (
          <div className="field">
            <label htmlFor="ur">{t("users.role")}</label>
            <select id="ur" className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {roles.map((r) => (
                <option key={r} value={r}>
                  {t(`users.roles.${r}`)}
                </option>
              ))}
            </select>
          </div>
        )}
        {form.role !== "driver" && (
          <>
            <div className="field">
              <label htmlFor="ue">{t("users.email")}</label>
              <input id="ue" className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="up">{t("users.password")}</label>
              <input id="up" className="input" type="password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
          </>
        )}
      </div>
      <div style={{ marginTop: 16 }}>
        <ErrorBox error={m.error} />
      </div>
    </Modal>
  );
}

function PermissionsModal({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["perm-meta"], queryFn: () => api.get<any>("/api/meta/permissions") });
  const [revoked, setRevoked] = useState<string[]>(user.revoked_permissions);
  const rolePerms: string[] = meta.data?.roles?.[user.role] ?? [];
  const save = async () => {
    await api.patch(`/api/users/${user.id}`, { revoked_permissions: revoked });
    qc.invalidateQueries({ queryKey: ["users"] });
    onClose();
  };
  return (
    <Modal
      title={`${t("users.permissions")}: ${user.name}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn" onClick={save}>
            {t("common.save")}
          </button>
        </>
      }
    >
      {meta.isLoading && <Spinner />}
      <div className="grid cols-2" style={{ gap: 8 }}>
        {(meta.data?.permissions ?? [])
          .filter((p: any) => rolePerms.includes(p.key))
          .map((p: any) => (
            <label key={p.key} className="checkbox">
              <input
                type="checkbox"
                checked={!revoked.includes(p.key)}
                onChange={(e) => setRevoked(e.target.checked ? revoked.filter((x) => x !== p.key) : [...revoked, p.key])}
              />
              <span>{p.label}</span>
            </label>
          ))}
      </div>
    </Modal>
  );
}
