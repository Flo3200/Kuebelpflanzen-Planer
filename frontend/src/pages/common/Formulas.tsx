import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Badge, Card, ConfirmButton, ErrorBox, PageHeader, Segmented, Spinner, useToast } from "../../components/ui";
import { fmtDate, fmtMinutes, fmtNumber, t } from "../../i18n";

type Expr = { name: string; level: "plant" | "stop"; expr: string };
type Param = { value: number; learnable: boolean; min?: number; max?: number; unit?: string; scale?: number };

export function FormulasPage() {
  const { me } = useAuth();
  const isTenant = !!me?.tenant;
  const qc = useQueryClient();
  const toast = useToast();
  const [key, setKey] = useState<"time" | "price">("time");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ expressions: Expr[]; parameters: Record<string, Param>; note: string } | null>(null);
  const [test, setTest] = useState<any>(null);
  const [orderId, setOrderId] = useState<string>("");
  const q = useQuery({ queryKey: ["formulas", key], queryFn: () => api.get<any>("/api/formulas", { key }) });
  const orders = useQuery({ queryKey: ["orders-mini"], queryFn: () => api.get<any[]>("/api/orders", { limit: 200 }), enabled: isTenant });
  const tier = useQuery({ queryKey: ["settings", "tenant", null, null], queryFn: () => api.get<any>("/api/settings"), enabled: isTenant });
  const activeTier = tier.data?.values?.find((v: any) => v.key === "time.formula_tier")?.value ?? 1;

  // for tenants: show the effective formula per tier (own override replaces the global one)
  const visible = useMemo(() => {
    const formulas: any[] = q.data?.formulas ?? [];
    if (!isTenant) return formulas;
    return formulas.filter((f) => !(f.is_global && f.overridden_by_tenant));
  }, [q.data, isTenant]);
  const selected = visible.find((f) => f.id === selectedId) ?? visible[0];
  const active = selected?.versions.find((v: any) => v.id === selected.active_version_id);
  type Draft = { expressions: Expr[]; parameters: Record<string, Param>; note: string };
  const base: Draft | null = draft ?? (active ? { expressions: active.expressions as Expr[], parameters: active.parameters as Record<string, Param>, note: "" } : null);

  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;

  const setExpr = (i: number, patch: Partial<Expr>) =>
    base && setDraft({ ...base, expressions: base.expressions.map((e, j) => (j === i ? { ...e, ...patch } : e)) });
  const setParam = (name: string, patch: Partial<Param>) =>
    base && setDraft({ ...base, parameters: { ...base.parameters, [name]: { ...base.parameters[name], ...patch } } });

  const runTest = async () => {
    if (!base) return;
    setTest(await api.post("/api/formulas/test", { key, expressions: base.expressions, parameters: base.parameters, order_id: orderId || undefined }));
  };
  const save = async () => {
    if (!base || !selected) return;
    try {
      const r = await api.post(`/api/formulas/${selected.id}/versions`, { expressions: base.expressions, parameters: base.parameters, note: base.note || null });
      setDraft(null);
      setTest(null);
      setSelectedId(r.formula.id);
      qc.invalidateQueries({ queryKey: ["formulas"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      toast({ text: t("formulas.saved") });
    } catch (e) {
      toast({ text: e instanceof ApiError ? e.message : String(e), tone: "error" });
    }
  };

  return (
    <>
      <PageHeader
        title={t("formulas.title")}
        description={isTenant ? t("formulas.tenant_description") : t("formulas.admin_description")}
        actions={
          <Segmented
            value={key}
            onChange={(k) => (setKey(k), setSelectedId(null), setDraft(null), setTest(null))}
            items={[
              { key: "time", label: t("formulas.key_time") },
              { key: "price", label: t("formulas.key_price") },
            ]}
          />
        }
      />
      <div className="grid" style={{ gridTemplateColumns: "260px minmax(0, 1fr)", alignItems: "start" }}>
        <div className="stack">
          {visible.map((f) => (
            <button
              key={f.id}
              className="card tight"
              style={{ textAlign: "left", cursor: "pointer", borderColor: f.id === selected?.id ? "var(--primary)" : undefined }}
              onClick={() => (setSelectedId(f.id), setDraft(null), setTest(null))}
            >
              <div className="row between">
                <strong>{f.name}</strong>
                {key === "time" && f.tier === activeTier && isTenant && <Badge tone="green">{t("formulas.active_tier")}</Badge>}
              </div>
              <div className="xs muted">
                {t("formulas.tier", { n: f.tier })} · {f.is_global ? t("formulas.global") : t("formulas.own")} ·{" "}
                {t("formulas.version", { n: f.versions.find((v: any) => v.id === f.active_version_id)?.version ?? "–" })}
              </div>
              {f.latest_fit && <div className="xs" style={{ marginTop: 4 }}>{t("formulas.fit_status", { status: t(`fits.status.${f.latest_fit.status}`) })}</div>}
            </button>
          ))}
          {key === "time" && isTenant && <p className="small muted">{t("formulas.tier_hint")}</p>}
        </div>
        {selected && base && (
          <div className="stack lg">
            <Card
              title={`${selected.name} · ${t("formulas.version", { n: active?.version ?? "–" })}`}
              actions={
                !selected.is_global && isTenant ? (
                  <ConfirmButton
                    question={t("formulas.reset_question")}
                    onConfirm={async () => {
                      await api.del(`/api/formulas/${selected.id}`);
                      setSelectedId(null);
                      qc.invalidateQueries({ queryKey: ["formulas"] });
                    }}
                  >
                    {t("formulas.reset_override")}
                  </ConfirmButton>
                ) : undefined
              }
            >
              {selected.is_global && isTenant && <div className="alert" style={{ marginBottom: 12 }}>{t("formulas.override_hint")}</div>}
              <p className="small muted">{selected.description}</p>
              <div className="stack">
                {base.expressions.map((e, i) => (
                  <div key={i} className="stack" style={{ gap: 6 }}>
                    <div className="row">
                      <input className="input mono" style={{ width: 140 }} value={e.name} onChange={(ev) => setExpr(i, { name: ev.target.value })} aria-label={t("formulas.expr_name")} />
                      <select className="input" style={{ width: 160 }} value={e.level} onChange={(ev) => setExpr(i, { level: ev.target.value as Expr["level"] })} aria-label={t("formulas.level")}>
                        <option value="plant">{t("formulas.level_plant")}</option>
                        <option value="stop">{t("formulas.level_stop")}</option>
                      </select>
                      <span className="grow" />
                      <button className="btn small ghost" onClick={() => setDraft({ ...base, expressions: base.expressions.filter((_, j) => j !== i) })}>
                        {t("common.remove")}
                      </button>
                    </div>
                    <textarea className="input mono" rows={2} value={e.expr} onChange={(ev) => setExpr(i, { expr: ev.target.value })} aria-label={e.name} />
                  </div>
                ))}
                <div>
                  <button className="btn small secondary" onClick={() => setDraft({ ...base, expressions: [...base.expressions, { name: "neu", level: "plant", expr: "0" }] })}>
                    {t("formulas.add_expr")}
                  </button>
                </div>
              </div>
            </Card>
            <Card title={t("formulas.parameters")}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("formulas.param_name")}</th>
                      <th className="num">{t("formulas.param_value")}</th>
                      <th>{t("formulas.param_learnable")}</th>
                      <th className="num">{t("formulas.param_min")}</th>
                      <th className="num">{t("formulas.param_max")}</th>
                      <th className="num">{t("formulas.param_scale")}</th>
                      <th>{t("formulas.param_unit")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(base.parameters).map(([name, p]) => (
                      <tr key={name}>
                        <td className="mono">{name}</td>
                        {(["value"] as const).map((f) => (
                          <td key={f} className="num">
                            <input className="input num" style={{ width: 90 }} type="number" step="any" value={p.value} onChange={(e) => setParam(name, { value: Number(e.target.value) })} aria-label={`${name} ${t("formulas.param_value")}`} />
                          </td>
                        ))}
                        <td>
                          <input type="checkbox" checked={!!p.learnable} onChange={(e) => setParam(name, { learnable: e.target.checked })} aria-label={t("formulas.param_learnable")} />
                        </td>
                        {(["min", "max", "scale"] as const).map((f) => (
                          <td key={f} className="num">
                            <input className="input num" style={{ width: 80 }} type="number" step="any" value={p[f] ?? ""} onChange={(e) => setParam(name, { [f]: e.target.value === "" ? undefined : Number(e.target.value) })} aria-label={`${name} ${f}`} />
                          </td>
                        ))}
                        <td>
                          <input className="input" style={{ width: 80 }} value={p.unit ?? ""} onChange={(e) => setParam(name, { unit: e.target.value })} aria-label={`${name} ${t("formulas.param_unit")}`} />
                        </td>
                        <td>
                          <button
                            className="btn small ghost"
                            onClick={() => {
                              const next = { ...base.parameters };
                              delete next[name];
                              setDraft({ ...base, parameters: next });
                            }}
                          >
                            {t("common.remove")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <button
                  className="btn small secondary"
                  onClick={() => {
                    const name = window.prompt(t("formulas.param_name"));
                    if (name) setDraft({ ...base, parameters: { ...base.parameters, [name]: { value: 0, learnable: false } } });
                  }}
                >
                  {t("formulas.add_param")}
                </button>
              </div>
            </Card>
            <Card title={t("formulas.check")}>
              <div className="row">
                {isTenant && (
                  <select className="input" style={{ width: 280 }} value={orderId} onChange={(e) => setOrderId(e.target.value)} aria-label={t("formulas.test_order")}>
                    <option value="">{t("formulas.test_order_any")}</option>
                    {(orders.data ?? []).map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.number} · {o.customer_name} ({o.n_plants})
                      </option>
                    ))}
                  </select>
                )}
                <button className="btn secondary" onClick={runTest}>
                  {t("formulas.test")}
                </button>
                <input className="input" style={{ width: 260 }} placeholder={t("formulas.note")} value={base.note} onChange={(e) => setDraft({ ...base, note: e.target.value })} aria-label={t("formulas.note")} />
                <button className="btn" disabled={!draft} onClick={save}>
                  {t("formulas.save_version")}
                </button>
              </div>
              {test && <TestResult test={test} />}
            </Card>
            <Card title={t("formulas.versions")}>
              <div className="stack" style={{ gap: 8 }}>
                {selected.versions.map((v: any) => (
                  <div key={v.id} className="row between">
                    <span className="small">
                      v{v.version} · {t(`formulas.source.${v.source}`)} · {fmtDate(v.created_at, true)} {v.note && <span className="muted">· {v.note}</span>}
                    </span>
                    {v.id === selected.active_version_id ? (
                      <Badge tone="green">{t("formulas.active")}</Badge>
                    ) : (
                      selected.tenant_id === (me?.tenant?.id ?? null) && (
                        <button
                          className="btn small ghost"
                          onClick={async () => {
                            await api.post(`/api/formulas/${selected.id}/activate/${v.id}`);
                            qc.invalidateQueries({ queryKey: ["formulas"] });
                          }}
                        >
                          {t("formulas.activate")}
                        </button>
                      )
                    )}
                  </div>
                ))}
              </div>
            </Card>
            <VariablesReference variables={q.data.variables[key]} functions={q.data.functions} />
          </div>
        )}
      </div>
    </>
  );
}

function TestResult({ test }: { test: any }) {
  if (!test.ok)
    return (
      <div className="alert error" style={{ marginTop: 12 }}>
        <strong>{t("formulas.problems")}</strong>
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {test.problems.map((p: any, i: number) => (
            <li key={i}>
              <span className="mono">{p.expression}</span>: {t(`formulas.problem_codes.${p.code}`, { detail: p.detail })} {p.detail}
              {p.pos != null && ` (${t("formulas.position", { pos: p.pos })})`}
            </li>
          ))}
        </ul>
      </div>
    );
  const r = test.result;
  if (!r) return <div className="alert ok" style={{ marginTop: 12 }}>{t("formulas.valid")}</div>;
  return (
    <div className="alert ok" style={{ marginTop: 12 }}>
      <div>
        <strong>{t("formulas.valid")}</strong> {test.order_number && t("formulas.example_order", { n: test.order_number })}
      </div>
      {r.duration_min != null && (
        <div className="small">
          {t("formulas.result_time", { team: r.team_size, duration: fmtMinutes(r.duration_min), labour: fmtMinutes(r.labour_min) })}
        </div>
      )}
      {r.price && <div className="small">{t("formulas.result_price", { gross: fmtNumber(r.price.gross, 2) })}</div>}
      {r.error && <div className="small">{r.error}</div>}
    </div>
  );
}

function VariablesReference({ variables, functions }: { variables: any[]; functions: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Card title={t("formulas.variables")} actions={<button className="btn small ghost" onClick={() => setOpen(!open)}>{open ? t("common.close") : t("common.open")}</button>}>
      {open && (
        <div className="stack">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("formulas.var_name")}</th>
                  <th>{t("formulas.level")}</th>
                  <th>{t("formulas.param_unit")}</th>
                  <th>{t("formulas.var_meaning")}</th>
                </tr>
              </thead>
              <tbody>
                {variables.map((v) => (
                  <tr key={v.name}>
                    <td className="mono">{v.name}</td>
                    <td>{v.level === "plant" ? t("formulas.level_plant") : t("formulas.level_stop")}</td>
                    <td>{v.unit}</td>
                    <td className="small">
                      <strong>{v.label}</strong> {v.help}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            {t("formulas.functions")}: <span className="mono">{functions.join(", ")}</span>
          </p>
          <p className="small muted">{t("formulas.syntax_help")}</p>
        </div>
      )}
    </Card>
  );
}
