import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Card, ErrorBox, Modal, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtDate, fmtMoney, fmtNumber, t, tMaybe } from "../../i18n";

const EVAL_FUNCTIONS = ["photo_analysis", "vehicle_photo", "vehicle_chat"];
const EVAL_TRUTH: Record<string, string> = {
  photo_analysis: '{"total_height_cm": 180, "pot_diameter_cm": 50}',
  vehicle_photo: '{"cargo_width_cm": 178, "cargo_height_cm": 194}',
  vehicle_chat: '{"cargo_length_cm": 330, "cargo_width_cm": 178, "cargo_height_cm": 194, "payload_kg": 1150}',
};

export function AdminAIPage() {
  const [tab, setTab] = useState<"models" | "prompts" | "usage" | "eval">("models");
  return (
    <>
      <PageHeader title={t("ai.title")} description={t("ai.description")} />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "models", label: t("ai.tab_models") },
          { key: "prompts", label: t("ai.tab_prompts") },
          { key: "usage", label: t("ai.tab_usage") },
          { key: "eval", label: t("ai.tab_eval") },
        ]}
      />
      {tab === "models" && <ProvidersAndModels />}
      {tab === "prompts" && <PromptEditor />}
      {tab === "usage" && <UsageTable admin />}
      {tab === "eval" && <EvalTool />}
    </>
  );
}

function ProvidersAndModels() {
  const qc = useQueryClient();
  const toast = useToast();
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: () => api.get<any[]>("/api/admin/ai/providers") });
  const models = useQuery({ queryKey: ["ai-models-admin"], queryFn: () => api.get<any[]>("/api/admin/ai/models") });
  const [keyFor, setKeyFor] = useState<any | null>(null);
  const [key, setKey] = useState("");
  const [newModel, setNewModel] = useState<any | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ai-providers"] });
    qc.invalidateQueries({ queryKey: ["ai-models-admin"] });
    qc.invalidateQueries({ queryKey: ["ai-models"] });
  };
  const patchModel = async (id: string, values: any) => {
    await api.patch(`/api/admin/ai/models/${id}`, values);
    refresh();
  };
  if (providers.isLoading || models.isLoading) return <Spinner />;
  return (
    <div className="stack lg">
      <p className="muted small">{t("ai.terms_hint")}</p>
      <Card title={t("ai.providers")}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.name")}</th>
                <th>{t("ai.kind")}</th>
                <th>{t("ai.key")}</th>
                <th>{t("common.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(providers.data ?? []).map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.kind}</td>
                  <td>{p.kind === "fake" ? "–" : p.has_key ? <Badge tone="green">{t("ai.key_set")}</Badge> : <Badge tone="amber">{t("ai.key_missing")}</Badge>}</td>
                  <td>
                    <label className="checkbox">
                      <input type="checkbox" checked={p.active} onChange={async (e) => (await api.patch(`/api/admin/ai/providers/${p.id}`, { active: e.target.checked }), refresh())} />
                      {p.active ? t("ai.active") : t("ai.inactive")}
                    </label>
                  </td>
                  <td className="num">
                    {p.kind !== "fake" && (
                      <button className="btn small ghost" onClick={() => (setKeyFor(p), setKey(""))}>
                        {t("ai.set_key")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card
        title={t("ai.models")}
        actions={
          <button className="btn small secondary" onClick={() => setNewModel({ provider_id: providers.data?.[0]?.id, model_name: "", label: "", input_price_per_mtok: 0, output_price_per_mtok: 0, price_currency: "USD" })}>
            {t("ai.add_model")}
          </button>
        }
      >
        <p className="small muted">{t("ai.models_hint")}</p>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("ai.label")}</th>
                <th>{t("ai.model_name")}</th>
                <th className="num">{t("ai.price_in")}</th>
                <th className="num">{t("ai.price_out")}</th>
                <th>{t("ai.effort")}</th>
                <th>{t("ai.fallbacks")}</th>
                <th>{t("ai.default")}</th>
                <th>{t("ai.active")}</th>
              </tr>
            </thead>
            <tbody>
              {(models.data ?? []).map((m) => (
                <tr key={m.id}>
                  <td>
                    {m.label}
                    <div className="xs muted">{m.provider_name}</div>
                  </td>
                  <td className="mono small">{m.model_name}</td>
                  <td className="num">
                    <input className="input num" style={{ width: 80 }} type="number" step="any" defaultValue={m.input_price_per_mtok} onBlur={(e) => patchModel(m.id, { input_price_per_mtok: Number(e.target.value) })} aria-label={t("ai.price_in")} />
                  </td>
                  <td className="num">
                    <input className="input num" style={{ width: 80 }} type="number" step="any" defaultValue={m.output_price_per_mtok} onBlur={(e) => patchModel(m.id, { output_price_per_mtok: Number(e.target.value) })} aria-label={t("ai.price_out")} />
                    <span className="xs faint"> {m.price_currency}</span>
                  </td>
                  <td>
                    <select className="input" style={{ width: 110 }} value={m.effort ?? ""} onChange={(e) => patchModel(m.id, { effort: e.target.value || null })} aria-label={t("ai.effort")}>
                      <option value="">–</option>
                      {["low", "medium", "high", "xhigh", "max"].map((x) => (
                        <option key={x} value={x}>
                          {x}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input type="checkbox" checked={m.use_fallbacks} onChange={(e) => patchModel(m.id, { use_fallbacks: e.target.checked })} aria-label={t("ai.fallbacks")} disabled={m.provider_kind !== "anthropic"} />
                  </td>
                  <td>
                    <input type="radio" name="default-model" checked={m.is_default} onChange={() => patchModel(m.id, { is_default: true })} aria-label={t("ai.default")} />
                  </td>
                  <td>
                    <input type="checkbox" checked={m.active} onChange={(e) => patchModel(m.id, { active: e.target.checked })} aria-label={t("ai.active")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {keyFor && (
        <Modal
          title={`${t("ai.set_key")}: ${keyFor.name}`}
          onClose={() => setKeyFor(null)}
          footer={
            <>
              <button className="btn ghost" onClick={() => setKeyFor(null)}>
                {t("common.cancel")}
              </button>
              <button
                className="btn"
                onClick={async () => {
                  await api.patch(`/api/admin/ai/providers/${keyFor.id}`, { api_key: key });
                  setKeyFor(null);
                  refresh();
                  toast({ text: t("common.saved") });
                }}
              >
                {t("common.save")}
              </button>
            </>
          }
        >
          <p className="small muted">{t("ai.key_hint")}</p>
          <input className="input mono" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} aria-label={t("ai.key")} />
        </Modal>
      )}
      {newModel && (
        <Modal
          title={t("ai.add_model")}
          onClose={() => setNewModel(null)}
          footer={
            <>
              <button className="btn ghost" onClick={() => setNewModel(null)}>
                {t("common.cancel")}
              </button>
              <button
                className="btn"
                disabled={!newModel.model_name}
                onClick={async () => {
                  await api.post("/api/admin/ai/models", newModel);
                  setNewModel(null);
                  refresh();
                }}
              >
                {t("common.create")}
              </button>
            </>
          }
        >
          <div className="form-grid">
            <div className="field">
              <label htmlFor="nm-p">{t("ai.provider")}</label>
              <select id="nm-p" className="input" value={newModel.provider_id} onChange={(e) => setNewModel({ ...newModel, provider_id: e.target.value })}>
                {(providers.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            {(["model_name", "label"] as const).map((f) => (
              <div className="field" key={f}>
                <label htmlFor={`nm-${f}`}>{t(`ai.${f}`)}</label>
                <input id={`nm-${f}`} className="input" value={newModel[f]} onChange={(e) => setNewModel({ ...newModel, [f]: e.target.value })} />
              </div>
            ))}
            {(["input_price_per_mtok", "output_price_per_mtok"] as const).map((f) => (
              <div className="field" key={f}>
                <label htmlFor={`nm-${f}`}>{t(`ai.${f}`)}</label>
                <input id={`nm-${f}`} className="input num" type="number" step="any" value={newModel[f]} onChange={(e) => setNewModel({ ...newModel, [f]: Number(e.target.value) })} />
              </div>
            ))}
            <div className="field">
              <label htmlFor="nm-cur">{t("ai.currency")}</label>
              <select id="nm-cur" className="input" value={newModel.price_currency} onChange={(e) => setNewModel({ ...newModel, price_currency: e.target.value })}>
                <option>USD</option>
                <option>EUR</option>
              </select>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function PromptEditor() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["prompts"], queryFn: () => api.get<any>("/api/ai/prompts") });
  const [fn, setFn] = useState("message_intake");
  const [draft, setDraft] = useState<{ system: string; instructions: string; note: string } | null>(null);
  if (q.isLoading) return <Spinner />;
  const versions = (q.data.prompts as any[]).filter((p) => p.function === fn);
  const active = versions.find((p) => p.active);
  const base = draft ?? { system: active?.system ?? "", instructions: active?.instructions ?? "", note: "" };
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(240px, 1fr)", alignItems: "start" }}>
      <Card
        title={t("ai.prompt_for")}
        actions={
          <select className="input" style={{ width: 240 }} value={fn} onChange={(e) => (setFn(e.target.value), setDraft(null))} aria-label={t("ai.function")}>
            {q.data.functions.map((f: string) => (
              <option key={f} value={f}>
                {t(`ai.functions.${f}`)}
              </option>
            ))}
          </select>
        }
      >
        <div className="stack">
          <div className="field">
            <label htmlFor="pr-sys">{t("ai.system_prompt")}</label>
            <textarea id="pr-sys" className="input" rows={14} value={base.system} onChange={(e) => setDraft({ ...base, system: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pr-ins">{t("ai.instructions")}</label>
            <textarea id="pr-ins" className="input" rows={3} value={base.instructions} onChange={(e) => setDraft({ ...base, instructions: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pr-note">{t("ai.version_note")}</label>
            <input id="pr-note" className="input" value={base.note} onChange={(e) => setDraft({ ...base, note: e.target.value })} />
          </div>
          <div className="row end">
            <button
              className="btn"
              disabled={!draft}
              onClick={async () => {
                await api.post("/api/ai/prompts", { function: fn, ...base });
                setDraft(null);
                qc.invalidateQueries({ queryKey: ["prompts"] });
                toast({ text: t("ai.version_saved") });
              }}
            >
              {t("ai.save_version")}
            </button>
          </div>
        </div>
      </Card>
      <Card title={t("ai.versions")}>
        <div className="stack" style={{ gap: 8 }}>
          {versions.map((p) => (
            <div key={p.id} className="row between">
              <span className="small">
                v{p.version} {p.tenant_id ? <Badge tone="terra">{t("ai.own")}</Badge> : <Badge>{t("ai.global")}</Badge>} {p.note}
                <div className="xs muted">{fmtDate(p.created_at, true)}</div>
              </span>
              {p.active ? (
                <Badge tone="green">{t("ai.active")}</Badge>
              ) : (
                <button className="btn small ghost" onClick={async () => (await api.post(`/api/ai/prompts/${p.id}/activate`), qc.invalidateQueries({ queryKey: ["prompts"] }))}>
                  {t("ai.activate")}
                </button>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function UsageTable({ admin = false }: { admin?: boolean }) {
  const [months, setMonths] = useState(1);
  const q = useQuery({ queryKey: ["ai-usage", months], queryFn: () => api.get<any>("/api/ai/usage", { months }) });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const rows: any[] = q.data.rows;
  const total = rows.reduce((s, r) => s + r.cost_eur, 0);
  return (
    <div className="stack">
      <div className="row between">
        <select className="input" style={{ width: 200 }} value={months} onChange={(e) => setMonths(Number(e.target.value))} aria-label={t("ai.period")}>
          <option value={1}>{t("ai.this_month")}</option>
          <option value={3}>{t("ai.last_months", { n: 3 })}</option>
          <option value={12}>{t("ai.last_months", { n: 12 })}</option>
        </select>
        {q.data.status && (
          <span className={`badge ${q.data.status.blocked ? "red" : q.data.status.warn ? "amber" : "green"}`}>
            {t("ai.spend_status", { spent: fmtMoney(q.data.status.spent_eur), limit: fmtMoney(q.data.status.limit_eur) })}
          </span>
        )}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              {admin && <th>{t("ai.tenant")}</th>}
              <th>{t("ai.function")}</th>
              <th>{t("ai.model_name")}</th>
              <th>{t("ai.key_mode")}</th>
              <th className="num">{t("ai.calls")}</th>
              <th className="num">{t("ai.tokens_in")}</th>
              <th className="num">{t("ai.tokens_out")}</th>
              <th className="num">{t("ai.cost")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {admin && <td>{r.tenant_name}</td>}
                <td>{t(`ai.functions.${r.function}`)}</td>
                <td className="mono small">{r.model}</td>
                <td>{r.key_mode === "byok" ? t("ai.byok") : t("ai.platform_key")}</td>
                <td className="num">
                  {fmtNumber(r.calls)}
                  {r.failed ? <span className="xs" style={{ color: "var(--danger)" }}> ({r.failed} ✕)</span> : null}
                </td>
                <td className="num">{fmtNumber(r.input_tokens)}</td>
                <td className="num">{fmtNumber(r.output_tokens)}</td>
                <td className="num">{fmtMoney(r.cost_eur)}</td>
              </tr>
            ))}
            <tr>
              <td colSpan={admin ? 7 : 6}>
                <strong>{t("ai.total")}</strong>
              </td>
              <td className="num">
                <strong>{fmtMoney(total)}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EvalTool() {
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["eval-sets"], queryFn: () => api.get<any[]>("/api/admin/ai/eval-sets"), refetchInterval: 4000 });
  const models = useQuery({ queryKey: ["ai-models-admin"], queryFn: () => api.get<any[]>("/api/admin/ai/models") });
  const [name, setName] = useState("");
  const [fn, setFn] = useState("photo_analysis");
  const [item, setItem] = useState<{ setId: string; fn: string; label: string; truth: string; text: string; files: File[] } | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["eval-sets"] });
  return (
    <div className="stack lg">
      <p className="muted small">{t("ai.eval_description")}</p>
      <div className="row">
        <input className="input" style={{ width: 280 }} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("ai.eval_set_name")} aria-label={t("ai.eval_set_name")} />
        <select className="input" style={{ width: 240 }} value={fn} onChange={(e) => setFn(e.target.value)} aria-label={t("ai.eval_function")}>
          {EVAL_FUNCTIONS.map((f) => (
            <option key={f} value={f}>
              {t(`ai.functions.${f}`)}
            </option>
          ))}
        </select>
        <button className="btn secondary" disabled={!name} onClick={async () => (await api.post("/api/admin/ai/eval-sets", { name, function: fn }), setName(""), refresh())}>
          {t("ai.new_eval_set")}
        </button>
      </div>
      {(sets.data ?? []).map((s) => (
        <Card
          key={s.id}
          title={
            <>
              {s.name} <Badge>{t(`ai.functions.${s.function ?? "photo_analysis"}`)}</Badge>
            </>
          }
          actions={
            <button className="btn small secondary" onClick={() => setItem({ setId: s.id, fn: s.function ?? "photo_analysis", label: "", truth: EVAL_TRUTH[s.function ?? "photo_analysis"], text: "", files: [] })}>
              {t("ai.add_item")}
            </button>
          }
        >
          <p className="small muted">{t("ai.items", { n: s.items.length })}</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {(models.data ?? []).filter((m) => m.active).map((m) => (
              <label key={m.id} className="checkbox small">
                <input type="checkbox" checked={chosen.includes(m.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, m.id] : chosen.filter((x) => x !== m.id))} />
                {m.label}
              </label>
            ))}
            <button className="btn small" disabled={!chosen.length || !s.items.length} onClick={async () => (await api.post(`/api/admin/ai/eval-sets/${s.id}/run`, { model_ids: chosen }), refresh())}>
              {t("ai.run_eval")}
            </button>
          </div>
          {s.runs.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("ai.model_name")}</th>
                    <th>{t("common.status")}</th>
                    <th>{t("ai.mae")}</th>
                    <th className="num">{t("ai.cost_per_item")}</th>
                  </tr>
                </thead>
                <tbody>
                  {s.runs.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.model}</td>
                      <td>{t(`jobs.status.${r.status === "running" ? "running" : r.status === "done" ? "done" : "queued"}`)}</td>
                      <td className="small">
                        {Object.entries(r.metrics?.mae ?? {}).map(([k, v]) => (
                          <div key={k}>
                            {tMaybe(`inbox.fields.${k}`) ?? tMaybe(`vehicledraft.fields.${k}`) ?? k}: {fmtNumber(v as number, 1)}
                          </div>
                        ))}
                      </td>
                      <td className="num">{r.metrics?.cost_per_item_eur != null ? fmtMoney(r.metrics.cost_per_item_eur) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ))}
      {item && (
        <Modal
          title={t("ai.add_item")}
          onClose={() => setItem(null)}
          footer={
            <button
              className="btn"
              disabled={!item.label || (item.fn === "vehicle_chat" ? !item.text : !item.files.length)}
              onClick={async () => {
                const form = new FormData();
                form.append("label", item.label);
                form.append("truth", item.truth);
                if (item.text) form.append("input_text", item.text);
                item.files.forEach((f, i) => {
                  form.append("files", f);
                  form.append("kinds", ["plant_front", "plant_side", "plant_top", "pot"][Math.min(i, 3)]);
                });
                await api.upload(`/api/admin/ai/eval-sets/${item.setId}/items`, form);
                setItem(null);
                refresh();
              }}
            >
              {t("common.save")}
            </button>
          }
        >
          <div className="stack">
            <div className="field">
              <label htmlFor="ev-l">{t("ai.item_label")}</label>
              <input id="ev-l" className="input" value={item.label} onChange={(e) => setItem({ ...item, label: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="ev-t">{t("ai.truth")}</label>
              <textarea id="ev-t" className="input mono" rows={3} value={item.truth} onChange={(e) => setItem({ ...item, truth: e.target.value })} />
              <span className="help">{t("ai.truth_help")}</span>
            </div>
            {item.fn !== "photo_analysis" && (
              <div className="field">
                <label htmlFor="ev-x">{item.fn === "vehicle_chat" ? t("ai.eval_message") : t("ai.eval_note")}</label>
                <textarea id="ev-x" className="input" rows={3} value={item.text} onChange={(e) => setItem({ ...item, text: e.target.value })} />
              </div>
            )}
            {item.fn !== "vehicle_chat" && (
              <input type="file" accept="image/*" multiple onChange={(e) => setItem({ ...item, files: Array.from(e.target.files ?? []) })} aria-label={t("orders.photos")} />
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}

export function TenantAIPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const providers = useQuery({ queryKey: ["ai-models"], queryFn: () => api.get<any[]>("/api/ai/models") });
  const keys = useQuery({ queryKey: ["ai-keys"], queryFn: () => api.get<any[]>("/api/ai/keys") });
  const [tab, setTab] = useState<"usage" | "keys" | "prompts">("usage");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("");
  const providerList = Array.from(new Map((providers.data ?? []).filter((m) => m.provider_kind !== "fake").map((m) => [m.provider_id, m.provider_name])).entries());
  return (
    <>
      <PageHeader title={t("ai.tenant_title")} description={t("ai.tenant_description")} />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "usage", label: t("ai.tab_usage") },
          { key: "keys", label: t("ai.tab_keys") },
          { key: "prompts", label: t("ai.tab_prompts") },
        ]}
      />
      {tab === "usage" && <UsageTable />}
      {tab === "keys" && (
        <Card title={t("ai.byok_title")}>
          <p className="small muted">{t("ai.byok_text")}</p>
          <div className="stack">
            {(keys.data ?? []).map((k) => (
              <div className="row between" key={k.id}>
                <span>
                  {providerList.find(([id]) => id === k.provider_id)?.[1] ?? k.provider_id} · <span className="mono">{k.key_hint}</span>
                </span>
                <button className="btn small ghost" onClick={async () => (await api.del(`/api/ai/keys/${k.provider_id}`), qc.invalidateQueries({ queryKey: ["ai-keys"] }))}>
                  {t("common.delete")}
                </button>
              </div>
            ))}
            <div className="row">
              <select className="input" style={{ width: 200 }} value={provider} onChange={(e) => setProvider(e.target.value)} aria-label={t("ai.provider")}>
                <option value="">{t("ai.provider")}</option>
                {providerList.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
              <input className="input mono" style={{ width: 320 }} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={t("ai.key")} aria-label={t("ai.key")} />
              <button
                className="btn"
                disabled={!provider || !key}
                onClick={async () => {
                  await api.put("/api/ai/keys", { provider_id: provider, api_key: key });
                  setKey("");
                  qc.invalidateQueries({ queryKey: ["ai-keys"] });
                  toast({ text: t("common.saved") });
                }}
              >
                {t("common.save")}
              </button>
            </div>
          </div>
        </Card>
      )}
      {tab === "prompts" && <PromptEditor />}
    </>
  );
}
