// Agents: enrolment links, tokens, confirmations, call log; for the admin also the platform mode.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Card, ConfirmButton, Empty, Field, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtDate, t } from "../../i18n";

interface Meta {
  kind: "tenant" | "admin";
  scopes: string[];
  mode: "test" | "production";
  readme_url: string;
}

export function AgentsPage({ admin = false }: { admin?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"tokens" | "confirmations" | "calls">("tokens");
  const meta = useQuery({ queryKey: ["agents-meta"], queryFn: () => api.get<Meta>("/api/agents/meta") });
  const tokens = useQuery({ queryKey: ["agent-tokens"], queryFn: () => api.get<any[]>("/api/agents/tokens") });
  const confirmations = useQuery({ queryKey: ["agent-confirmations"], queryFn: () => api.get<any[]>("/api/agents/confirmations"), refetchInterval: 10_000 });
  const calls = useQuery({ queryKey: ["agent-calls"], queryFn: () => api.get<any[]>("/api/agents/calls"), enabled: tab === "calls" });
  const [form, setForm] = useState<{ name: string; scopes: string[]; token_days: string }>({ name: "", scopes: [], token_days: "" });
  const [link, setLink] = useState<any>(null);
  const create = async () => {
    try {
      const r = await api.post("/api/agents/links", { name: form.name, scopes: form.scopes, token_days: form.token_days ? Number(form.token_days) : null });
      setLink(r);
      setForm({ name: "", scopes: [], token_days: "" });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const revoke = async (id: string) => {
    await api.post(`/api/agents/tokens/${id}/revoke`);
    qc.invalidateQueries({ queryKey: ["agent-tokens"] });
    toast({ text: t("agents.revoked") });
  };
  const decide = async (id: string, approve: boolean) => {
    try {
      await api.post(`/api/agents/confirmations/${id}/decide`, { approve });
      qc.invalidateQueries({ queryKey: ["agent-confirmations"] });
      toast({ text: t(approve ? "agents.approved" : "agents.rejected") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const setMode = async (mode: "test" | "production") => {
    await api.put("/api/settings", { scope: "platform", key: "platform.mode", value: mode });
    qc.invalidateQueries({ queryKey: ["agents-meta"] });
    toast({ text: t("agents.mode_changed") });
  };
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast({ text: t("agents.copied") }));
  const m = meta.data;
  const pending = (confirmations.data ?? []).length;
  return (
    <>
      <PageHeader
        title={t("agents.title")}
        description={t(admin ? "agents.description_admin" : "agents.description")}
        actions={
          m && (
            <a className="btn ghost" href={m.readme_url} target="_blank" rel="noreferrer">
              {t("agents.readme")}
            </a>
          )
        }
      />
      {meta.isLoading && <Spinner />}
      {m && admin && (
        <Card title={t("agents.mode")}>
          <div className="row between">
            <div>
              <Badge tone={m.mode === "production" ? "green" : "amber"}>{t(`agents.modes.${m.mode}`)}</Badge>
              <p className="small muted" style={{ marginTop: 6 }}>
                {t(`agents.mode_help.${m.mode}`)}
              </p>
            </div>
            {m.mode === "test" ? (
              <ConfirmButton question={t("agents.to_production_q")} onConfirm={() => setMode("production")}>
                {t("agents.to_production")}
              </ConfirmButton>
            ) : (
              <ConfirmButton question={t("agents.to_test_q")} onConfirm={() => setMode("test")}>
                {t("agents.to_test")}
              </ConfirmButton>
            )}
          </div>
        </Card>
      )}
      {m && (
        <Card title={t("agents.new_link")}>
          <div className="grid cols-3">
            <Field label={t("agents.name")} htmlFor="agent-name">
              <input id="agent-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t("agents.name_ph")} />
            </Field>
            <Field label={t("agents.token_days")} help={t("agents.token_days_help")} htmlFor="agent-days">
              <input id="agent-days" className="input" inputMode="numeric" value={form.token_days} onChange={(e) => setForm({ ...form, token_days: e.target.value.replace(/\D/g, "") })} />
            </Field>
          </div>
          <div className="stack" style={{ gap: 6, marginTop: 8 }}>
            <span className="small muted">{t("agents.scopes")}</span>
            {m.scopes.map((s) => (
              <label key={s} className="checkbox">
                <input type="checkbox" checked={form.scopes.includes(s)} onChange={(e) => setForm({ ...form, scopes: e.target.checked ? [...form.scopes, s] : form.scopes.filter((x) => x !== s) })} />
                <strong>{t(`agents.scope.${s}`)}</strong> <span className="small muted">– {t(`agents.scope_help.${s}`)}</span>
              </label>
            ))}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={form.name.trim().length < 2 || !form.scopes.length} onClick={create}>
              {t("agents.create_link")}
            </button>
          </div>
          {link && (
            <div className="alert ok" style={{ marginTop: 12 }}>
              <p className="small">{t("agents.link_once", { at: fmtDate(link.expires_at, true) })}</p>
              <div className="row">
                <code style={{ wordBreak: "break-all" }}>{link.url}</code>
                <button className="btn small ghost" onClick={() => copy(link.url)}>
                  {t("agents.copy")}
                </button>
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                <code style={{ wordBreak: "break-all" }}>{link.curl}</code>
                <button className="btn small ghost" onClick={() => copy(link.curl)}>
                  {t("agents.copy")}
                </button>
              </div>
            </div>
          )}
        </Card>
      )}
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "tokens", label: t("agents.tab_tokens") },
          { key: "confirmations", label: pending ? `${t("agents.tab_confirmations")} (${pending})` : t("agents.tab_confirmations") },
          { key: "calls", label: t("agents.tab_calls") },
        ]}
      />
      {tab === "tokens" &&
        ((tokens.data ?? []).length === 0 ? (
          <Empty title={t("agents.no_tokens")} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("agents.name")}</th>
                  <th>{t("agents.scopes")}</th>
                  <th>{t("agents.state")}</th>
                  <th>{t("agents.last_used")}</th>
                  <th className="num">{t("agents.calls")}</th>
                  <th>{t("agents.expires")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(tokens.data ?? []).map((x) => (
                  <tr key={x.id}>
                    <td>
                      {x.name} <span className="xs muted">{x.prefix}…</span>
                    </td>
                    <td>{(x.scopes as string[]).map((s) => t(`agents.scope.${s}`)).join(", ")}</td>
                    <td>
                      <Badge tone={x.state === "active" ? "green" : "red"}>{t(`agents.states.${x.state}`)}</Badge>
                    </td>
                    <td>{x.last_used_at ? fmtDate(x.last_used_at, true) : "–"}</td>
                    <td className="num">{x.calls}</td>
                    <td>{fmtDate(x.expires_at)}</td>
                    <td>
                      {x.state === "active" && (
                        <ConfirmButton className="btn small ghost" question={t("agents.revoke_q")} onConfirm={() => revoke(x.id)}>
                          {t("agents.revoke")}
                        </ConfirmButton>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      {tab === "confirmations" &&
        (pending === 0 ? (
          <Empty title={t("agents.no_confirmations")} text={t("agents.confirmations_help")} />
        ) : (
          <div className="stack">
            {(confirmations.data ?? []).map((c) => (
              <Card key={c.id} title={`${c.token ?? t("agents.agent")}: ${t(`agents.actions.${c.action.split(":")[0]}`, { what: c.action.split(":")[1] ?? "" })}`}>
                <pre className="small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                  {JSON.stringify(c.payload, null, 2)}
                </pre>
                <p className="xs muted">{t("agents.requested", { at: fmtDate(c.requested_at, true), until: fmtDate(c.expires_at, true) })}</p>
                <div className="row">
                  <button className="btn" onClick={() => decide(c.id, true)}>
                    {t("agents.approve")}
                  </button>
                  <button className="btn ghost" onClick={() => decide(c.id, false)}>
                    {t("agents.reject")}
                  </button>
                </div>
              </Card>
            ))}
          </div>
        ))}
      {tab === "calls" && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("agents.time")}</th>
                <th>{t("agents.agent")}</th>
                <th>{t("agents.call")}</th>
                <th className="num">{t("agents.status")}</th>
                <th className="num">ms</th>
              </tr>
            </thead>
            <tbody>
              {(calls.data ?? []).map((c) => (
                <tr key={c.id}>
                  <td>{fmtDate(c.at, true)}</td>
                  <td>{c.token}</td>
                  <td>
                    <code>
                      {c.method} {c.path}
                    </code>
                  </td>
                  <td className="num" style={{ color: c.status >= 400 ? "var(--danger)" : undefined }}>
                    {c.status}
                  </td>
                  <td className="num">{c.duration_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
