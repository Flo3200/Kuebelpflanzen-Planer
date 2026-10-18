// Billing: usage and invoices of the platform. Tenant: own usage and invoices. Admin: modules per
// tenant, preview, invoice for a month, monthly run, cancel and mark paid.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Badge, Card, ConfirmButton, Empty, Kpi, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtDate, fmtMoney, fmtNumber, t } from "../../i18n";

function monthOptions(): { y: number; m: number; label: string }[] {
  const out = [];
  const d = new Date();
  for (let i = 0; i < 13; i++) {
    const x = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push({ y: x.getFullYear(), m: x.getMonth() + 1, label: x.toLocaleDateString("de-DE", { month: "long", year: "numeric" }) });
  }
  return out;
}

function Preview({ p }: { p: any }) {
  if (!p) return null;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t("billing.line")}</th>
            <th className="num">{t("billing.quantity")}</th>
            <th className="num">{t("billing.unit_price")}</th>
            <th className="num">{t("billing.amount")}</th>
          </tr>
        </thead>
        <tbody>
          {p.lines.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                {t("billing.nothing")}
              </td>
            </tr>
          )}
          {p.lines.map((l: any, i: number) => (
            <tr key={i}>
              <td>{l.text}</td>
              <td className="num">{l.quantity != null ? `${fmtNumber(l.quantity)} ${l.unit ?? ""}` : ""}</td>
              <td className="num">{l.unit_price != null ? fmtMoney(l.unit_price) : ""}</td>
              <td className="num">{fmtMoney(l.amount)}</td>
            </tr>
          ))}
          <tr>
            <td>{t("billing.net")}</td>
            <td />
            <td />
            <td className="num">{fmtMoney(p.net)}</td>
          </tr>
          <tr>
            <td>{p.small_business ? t("billing.small_business") : t("billing.vat", { pct: fmtNumber(p.vat_pct) })}</td>
            <td />
            <td />
            <td className="num">{fmtMoney(p.vat)}</td>
          </tr>
          <tr>
            <td>
              <strong>{t("billing.gross")}</strong>
            </td>
            <td />
            <td />
            <td className="num">
              <strong>{fmtMoney(p.gross)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function Invoices({ tenantId, admin, kind = "platform" }: { tenantId?: string; admin?: boolean; kind?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["invoices", kind, tenantId ?? null], queryFn: () => api.get<any[]>("/api/billing/invoices", { tenant_id: tenantId, kind }) });
  const act = async (id: string, what: "cancel" | "paid") => {
    try {
      await api.post(`/api/billing/invoices/${id}/${what}`);
      qc.invalidateQueries({ queryKey: ["invoices"] });
      toast({ text: t(what === "cancel" ? "billing.cancelled" : "billing.marked_paid") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  if (q.isLoading) return <Spinner />;
  if (!(q.data ?? []).length) return <Empty title={t("billing.no_invoices")} />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t("billing.number")}</th>
            <th>{t("billing.date")}</th>
            <th>{t("billing.period")}</th>
            {admin && <th>{t("billing.recipient")}</th>}
            <th className="num">{t("billing.gross")}</th>
            <th>{t("billing.status")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(q.data ?? []).map((i) => (
            <tr key={i.id}>
              <td>
                {i.number} {i.cancels_id && <Badge tone="amber">{t("billing.storno")}</Badge>}
              </td>
              <td>{fmtDate(i.issue_date)}</td>
              <td>{i.period_start ? `${fmtDate(i.period_start)} – ${fmtDate(i.period_end)}` : "–"}</td>
              {admin && <td>{i.recipient?.name}</td>}
              <td className="num">{fmtMoney(i.gross)}</td>
              <td>
                <Badge tone={i.status === "paid" ? "green" : i.status === "cancelled" ? "red" : undefined}>{t(`billing.states.${i.status}`)}</Badge>
              </td>
              <td className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                <a className="btn small ghost" href={i.pdf_url} target="_blank" rel="noreferrer">
                  PDF
                </a>
                {admin && i.status === "issued" && !i.cancels_id && (
                  <>
                    <button className="btn small ghost" onClick={() => act(i.id, "paid")}>
                      {t("billing.mark_paid")}
                    </button>
                    <ConfirmButton className="btn small ghost" question={t("billing.cancel_q")} onConfirm={() => act(i.id, "cancel")}>
                      {t("billing.cancel")}
                    </ConfirmButton>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Usage({ tenantId }: { tenantId?: string }) {
  const months = monthOptions();
  const [sel, setSel] = useState(0);
  const { y, m } = months[sel];
  const q = useQuery({ queryKey: ["usage", tenantId ?? null, y, m], queryFn: () => api.get<any>("/api/billing/usage", { tenant_id: tenantId, year: y, month: m }) });
  const d = q.data;
  const aiCost = (d?.ai ?? []).reduce((s: number, x: any) => s + x.cost_eur, 0);
  const tokens = (d?.ai ?? []).reduce((s: number, x: any) => s + x.input_tokens + x.output_tokens, 0);
  return (
    <div className="stack lg">
      <div className="row">
        <select className="input" style={{ maxWidth: 240 }} value={sel} onChange={(e) => setSel(Number(e.target.value))} aria-label={t("billing.month")}>
          {months.map((x, i) => (
            <option key={i} value={i}>
              {x.label}
            </option>
          ))}
        </select>
      </div>
      {q.isLoading && <Spinner />}
      {d && (
        <>
          <div className="grid cols-4">
            <Kpi label={t("billing.kpi_plants")} value={fmtNumber(d.plants_picked_up)} />
            <Kpi label={t("billing.kpi_ai_cost")} value={fmtMoney(aiCost)} sub={t("billing.kpi_tokens", { n: fmtNumber(tokens) })} />
            <Kpi label={t("billing.kpi_preview")} value={fmtMoney(d.preview.gross)} sub={t("billing.kpi_preview_sub")} />
          </div>
          <Card title={t("billing.preview")}>
            <Preview p={d.preview} />
          </Card>
          {d.ai.length > 0 && (
            <Card title={t("billing.ai_usage")}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("billing.function")}</th>
                      <th>{t("billing.model")}</th>
                      <th>{t("billing.key")}</th>
                      <th className="num">{t("billing.calls")}</th>
                      <th className="num">{t("billing.tokens_in")}</th>
                      <th className="num">{t("billing.tokens_out")}</th>
                      <th className="num">{t("billing.cost")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.ai.map((x: any, i: number) => (
                      <tr key={i}>
                        <td>{t(`ai.functions.${x.function}`)}</td>
                        <td>{x.model}</td>
                        <td>{t(`billing.key_modes.${x.key_mode}`)}</td>
                        <td className="num">{x.calls}</td>
                        <td className="num">{fmtNumber(x.input_tokens)}</td>
                        <td className="num">{fmtNumber(x.output_tokens)}</td>
                        <td className="num">{fmtMoney(x.cost_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

export function TenantBillingPage() {
  return (
    <>
      <PageHeader title={t("billing.title")} description={t("billing.description_tenant")} />
      <div className="stack lg">
        <Usage />
        <Card title={t("billing.invoices")}>
          <Invoices />
        </Card>
      </div>
    </>
  );
}

export function AdminBillingPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const tenants = useQuery({ queryKey: ["admin-tenants"], queryFn: () => api.get<any>("/api/admin/tenants") });
  const list: any[] = Array.isArray(tenants.data) ? tenants.data : (tenants.data?.items ?? []);
  const [tenantId, setTenantId] = useState<string>("");
  const months = monthOptions();
  const [sel, setSel] = useState(1);
  const createInvoice = async () => {
    const { y, m } = months[sel];
    try {
      const inv = await api.post<any>("/api/billing/invoices", { tenant_id: tenantId, year: y, month: m });
      toast({ text: t("billing.created", { number: inv.number }) });
      qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const runMonthly = async () => {
    try {
      const r = await api.post<any>("/api/billing/run-monthly", { sync: true });
      toast({ text: t("billing.run_done", { n: r.result?.created?.length ?? 0 }) });
      qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <>
      <PageHeader
        title={t("billing.title")}
        description={t("billing.description_admin")}
        actions={
          <ConfirmButton question={t("billing.run_q")} onConfirm={runMonthly}>
            {t("billing.run_monthly")}
          </ConfirmButton>
        }
      />
      <div className="stack lg">
        <div className="row">
          <select className="input" style={{ maxWidth: 320 }} value={tenantId} onChange={(e) => setTenantId(e.target.value)} aria-label={t("billing.tenant")}>
            <option value="">{t("billing.all_tenants")}</option>
            {list.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </div>
        {tenantId && (
          <>
            <Card title={t("billing.modules")}>
              <p className="small muted">{t("billing.modules_help")}</p>
              <SettingsEditor scope="tenant" tenantId={tenantId} onlyGroups={["billing"]} compact canEditAdminOnly />
            </Card>
            <Usage tenantId={tenantId} />
            <Card title={t("billing.create_invoice")}>
              <div className="row">
                <select className="input" style={{ maxWidth: 240 }} value={sel} onChange={(e) => setSel(Number(e.target.value))} aria-label={t("billing.month")}>
                  {months.map((x, i) => (
                    <option key={i} value={i}>
                      {x.label}
                    </option>
                  ))}
                </select>
                <button className="btn" onClick={createInvoice}>
                  {t("billing.create_invoice")}
                </button>
              </div>
            </Card>
          </>
        )}
        <Card title={t("billing.invoices")}>
          <Invoices tenantId={tenantId || undefined} admin />
        </Card>
      </div>
    </>
  );
}

export function OrderInvoices({ orderId }: { orderId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["invoices", "customer", null], queryFn: () => api.get<any[]>("/api/billing/invoices", { kind: "customer" }) });
  const mine = (q.data ?? []).filter((i) => i.order_id === orderId);
  const create = async () => {
    try {
      const inv = await api.post<any>(`/api/billing/orders/${orderId}/invoice`);
      qc.invalidateQueries({ queryKey: ["invoices"] });
      window.open(inv.pdf_url, "_blank");
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const open = mine.some((i) => i.status !== "cancelled" && !i.cancels_id);
  return (
    <Card
      title={t("billing.customer_invoices")}
      actions={
        !open && (
          <button className="btn small" onClick={create}>
            {t("billing.create_customer_invoice")}
          </button>
        )
      }
    >
      {mine.length === 0 && <p className="muted small">{t("billing.no_customer_invoice")}</p>}
      <div className="stack" style={{ gap: 6 }}>
        {mine.map((i) => (
          <div key={i.id} className="row between">
            <span className="small">
              {i.number} · {fmtDate(i.issue_date)} · {fmtMoney(i.gross)} · {t(`billing.states.${i.status}`)}
            </span>
            <a className="btn small ghost" href={i.pdf_url} target="_blank" rel="noreferrer">
              PDF
            </a>
          </div>
        ))}
      </div>
    </Card>
  );
}
