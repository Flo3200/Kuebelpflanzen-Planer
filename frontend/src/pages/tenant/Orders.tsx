import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { EntityForm, EntityTable, formatCell, useEntityMeta } from "../../components/EntityForm";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Badge, Card, Confidence, ConfirmButton, Empty, ErrorBox, Modal, PageHeader, Spinner, Tabs, useToast } from "../../components/ui";
import { fmtMinutes, fmtMoney, fmtNumber, t } from "../../i18n";
import { JobStatus, useJob } from "../common/Jobs";
import { EstimateDetails } from "./Estimate";
import { PhotoGallery } from "./Photos";

const STATUS_TONE: Record<string, "green" | "amber" | "red" | "blue" | "terra" | undefined> = {
  draft: "amber",
  confirmed: "blue",
  planned: "terra",
  picked_up: "green",
  stored: "green",
  returned: "green",
  cancelled: "red",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status]}>{t(`orders.status.${status}`)}</Badge>;
}

// ----------------------------------------------------------------------------- customers

export function CustomersPage() {
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["customers", q], queryFn: () => api.get<any[]>("/api/customers", { q: q || undefined }) });
  return (
    <>
      <PageHeader
        title={t("nav.customers")}
        description={t("customers.description")}
        actions={
          <>
            <input className="input" style={{ width: 240 }} placeholder={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
            <button className="btn" onClick={() => setCreating(true)}>
              {t("customers.new")}
            </button>
          </>
        }
      />
      {list.isLoading && <Spinner />}
      {list.data && list.data.length === 0 && <Empty title={t("customers.empty")} text={t("customers.empty_text")} />}
      {list.data && list.data.length > 0 && (
        <EntityTable
          entity="customer"
          rows={list.data}
          columns={["name", "phone"]}
          onRowClick={(r) => navigate(`/betrieb/kunden/${r.id}`)}
        />
      )}
      {creating && <NewCustomerModal onClose={() => setCreating(false)} onCreated={(id) => navigate(`/betrieb/kunden/${id}`)} />}
    </>
  );
}

function NewCustomerModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [step, setStep] = useState<"customer" | "address">("customer");
  const [customer, setCustomer] = useState<any>(null);
  return (
    <Modal title={t("customers.new")} onClose={onClose} wide>
      {step === "customer" && (
        <EntityForm
          entity="customer"
          fields={["name", "phone", "company", "email", "preferred_contact", "notes"]}
          submitLabel={t("common.next")}
          onCancel={onClose}
          onSubmit={async (v) => {
            setCustomer(await api.post("/api/customers", v));
            setStep("address");
          }}
        />
      )}
      {step === "address" && customer && (
        <EntityForm
          entity="address"
          fields={["street", "postal_code", "city", "label", "lat", "lon", "parking_notes", "bell_notes", "access_notes"]}
          submitLabel={t("common.create")}
          onCancel={() => onCreated(customer.id)}
          onSubmit={async (v) => {
            await api.post("/api/addresses", { ...v, customer_id: customer.id });
            onCreated(customer.id);
          }}
        />
      )}
    </Modal>
  );
}

export function CustomerDetailPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["customer", id], queryFn: () => api.get<any>(`/api/customers/${id}/full`) });
  const { mod } = useAuth();
  const [addAddress, setAddAddress] = useState(false);
  const [editAddress, setEditAddress] = useState<any>(null);
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { customer, addresses, orders } = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ["customer", id] });
  const newOrder = async (addressId: string) => {
    const o = await api.post("/api/orders", { customer_id: id, address_id: addressId });
    navigate(`/betrieb/auftraege/${o.order.id}`);
  };
  const portalLink = async () => {
    try {
      const r = await api.post<any>(`/api/customers/${id}/portal-link`);
      await navigator.clipboard?.writeText(r.url).catch(() => undefined);
      window.prompt(t("portal.staff_link_copy", { days: r.valid_days }), r.url);
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const erase = async () => {
    try {
      await api.post(`/api/customers/${id}/erase`, { confirm: true });
      toast({ text: t("privacy.erased") });
      refresh();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <>
      <PageHeader
        eyebrow={t("nav.customers")}
        title={customer.name}
        description={[customer.email, customer.phone].filter(Boolean).join(" · ")}
        actions={
          <>
            {mod("portal") && (
              <button className="btn secondary" onClick={portalLink}>
                {t("portal.staff_link")}
              </button>
            )}
            <a className="btn ghost" href={`/api/customers/${id}/export`}>
              {t("privacy.export")}
            </a>
            <ConfirmButton className="btn ghost" question={t("privacy.erase_q")} onConfirm={erase}>
              {t("privacy.erase")}
            </ConfirmButton>
          </>
        }
      />
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Card title={t("customers.data")}>
          <EntityForm
            key={customer.updated_at}
            entity="customer"
            initial={customer}
            onSubmit={async (v) => {
              await api.patch(`/api/customers/${id}`, v);
              refresh();
              toast({ text: t("common.saved") });
            }}
          />
        </Card>
        <div className="stack lg">
          <Card
            title={t("customers.addresses")}
            actions={
              <button className="btn small secondary" onClick={() => setAddAddress(true)}>
                {t("common.add")}
              </button>
            }
          >
            <div className="stack">
              {addresses.map((a: any) => (
                <div key={a.id} className="row between top">
                  <div>
                    <div>{a.street}</div>
                    <div className="small muted">
                      {a.postal_code} {a.city} {a.lat == null && <Badge tone="amber">{t("customers.no_coordinates")}</Badge>}
                    </div>
                  </div>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="btn small ghost" onClick={() => setEditAddress(a)}>
                      {t("common.edit")}
                    </button>
                    <button className="btn small" onClick={() => newOrder(a.id)}>
                      {t("orders.new")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card title={t("nav.orders")}>
            {orders.length === 0 && <p className="muted">{t("orders.none")}</p>}
            <div className="stack" style={{ gap: 8 }}>
              {orders.map((o: any) => (
                <Link key={o.id} to={`/betrieb/auftraege/${o.id}`} className="row between" style={{ textDecoration: "none", color: "inherit" }}>
                  <span>
                    {o.number} · {t(`orders.direction.${o.direction}`)} · {o.n_plants} {t("orders.plants_short")}
                  </span>
                  <StatusBadge status={o.status} />
                </Link>
              ))}
            </div>
          </Card>
        </div>
      </div>
      {(addAddress || editAddress) && (
        <Modal title={t("customers.address")} onClose={() => (setAddAddress(false), setEditAddress(null))} wide>
          <EntityForm
            entity="address"
            initial={editAddress ?? {}}
            fields={["street", "postal_code", "city", "label", "lat", "lon", "parking_notes", "bell_notes", "access_notes"]}
            onCancel={() => (setAddAddress(false), setEditAddress(null))}
            onSubmit={async (v) => {
              if (editAddress) await api.patch(`/api/addresses/${editAddress.id}`, v);
              else await api.post("/api/addresses", { ...v, customer_id: id });
              setAddAddress(false);
              setEditAddress(null);
              refresh();
            }}
          />
        </Modal>
      )}
    </>
  );
}

// ----------------------------------------------------------------------------- orders

function ReturnsModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const year = new Date().getMonth() >= 6 ? new Date().getFullYear() + 1 : new Date().getFullYear();
  const [form, setForm] = useState({ earliest_date: `${year}-04-01`, latest_date: `${year}-05-31` });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>("/api/orders/returns", form);
      toast({ text: t("returns.created", { n: r.created, existing: r.existing }) });
      qc.invalidateQueries({ queryKey: ["orders"] });
      onDone();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t("returns.create")}
      onClose={onClose}
      footer={
        <button className="btn" onClick={submit} disabled={busy}>
          {t("returns.create_now")}
        </button>
      }
    >
      <p className="small muted">{t("returns.create_help")}</p>
      <div className="grid cols-2">
        <div className="field">
          <label htmlFor="ret-from">{t("returns.from")}</label>
          <input id="ret-from" type="date" className="input" value={form.earliest_date} onChange={(e) => setForm({ ...form, earliest_date: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ret-to">{t("returns.to")}</label>
          <input id="ret-to" type="date" className="input" value={form.latest_date} onChange={(e) => setForm({ ...form, latest_date: e.target.value })} />
        </div>
      </div>
      <p className="xs muted">{t("returns.frost_hint")}</p>
    </Modal>
  );
}

export function OrdersPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string>("");
  const [direction, setDirection] = useState<string>("pickup");
  const [returnsOpen, setReturnsOpen] = useState(false);
  const navigate = useNavigate();
  const { mod } = useAuth();
  const billing = mod("customer_billing");
  const list = useQuery({
    queryKey: ["orders", q, status, direction],
    queryFn: () => api.get<any[]>("/api/orders", { q: q || undefined, status: status ? [status] : undefined, direction: direction || undefined }),
  });
  const totals = useMemo(() => {
    const rows = list.data ?? [];
    return {
      plants: rows.reduce((s, r) => s + (r.n_plants ?? 0), 0),
      revenue: rows.reduce((s, r) => s + (r.price_quoted ?? 0), 0),
      labour: rows.reduce((s, r) => s + (r.labour_min ?? 0), 0),
    };
  }, [list.data]);
  return (
    <>
      <PageHeader
        title={t("nav.orders")}
        description={t("orders.description")}
        actions={
          <>
            <select className="input" style={{ width: 160 }} value={direction} onChange={(e) => setDirection(e.target.value)} aria-label={t("orders.direction_label")}>
              <option value="">{t("common.all")}</option>
              <option value="pickup">{t("orders.direction.pickup")}</option>
              <option value="return">{t("orders.direction.return")}</option>
            </select>
            <select className="input" style={{ width: 170 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("common.status")}>
              <option value="">{t("common.all")}</option>
              {["draft", "confirmed", "planned", "picked_up", ...(mod("storage") ? ["stored"] : []), "returned", "cancelled"].map((s) => (
                <option key={s} value={s}>
                  {t(`orders.status.${s}`)}
                </option>
              ))}
            </select>
            <input className="input" style={{ width: 220 }} placeholder={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
            <button className="btn secondary" onClick={() => setReturnsOpen(true)}>
              {t("returns.create")}
            </button>
          </>
        }
      />
      {returnsOpen && <ReturnsModal onClose={() => setReturnsOpen(false)} onDone={() => (setReturnsOpen(false), setDirection("return"))} />}
      {list.isLoading && <Spinner />}
      {list.data && list.data.length === 0 && <Empty title={t("orders.none")} text={t("orders.empty_text")} />}
      {list.data && list.data.length > 0 && (
        <>
          <p className="small muted">
            {billing
              ? t("orders.totals", { n: list.data.length, plants: totals.plants, labour: fmtMinutes(totals.labour), revenue: fmtMoney(totals.revenue) })
              : t("orders.totals_logistics", { n: list.data.length, plants: totals.plants, labour: fmtMinutes(totals.labour) })}
          </p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("orders.number")}</th>
                  <th>{t("orders.customer")}</th>
                  <th>{t("orders.place")}</th>
                  <th className="num">{t("orders.plants")}</th>
                  <th className="num">{t("orders.duration")}</th>
                  <th className="num">{t("orders.team")}</th>
                  {billing && <th className="num">{t("orders.price")}</th>}
                  <th>{t("common.status")}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((o) => (
                  <tr key={o.id} className="clickable" onClick={() => navigate(`/betrieb/auftraege/${o.id}`)}>
                    <td className="num">{o.number}</td>
                    <td>{o.customer_name}</td>
                    <td className="small">
                      {o.postal_code} {o.city}
                    </td>
                    <td className="num">{o.n_plants}</td>
                    <td className="num">{fmtMinutes(o.duration_min)}</td>
                    <td className="num">{o.team_size ?? "–"}</td>
                    {billing && <td className="num">{fmtMoney(o.price_quoted)}</td>}
                    <td>
                      <StatusBadge status={o.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

export function OrderDetailPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useState<"plants" | "path" | "photos" | "order" | "estimate">("plants");
  const q = useQuery({ queryKey: ["order", id], queryFn: () => api.get<any>(`/api/orders/${id}`) });
  const { mod } = useAuth();
  const occupancy = useQuery({
    queryKey: ["occupancy", id],
    queryFn: () => api.get<any>("/api/storage/occupancy", { order_id: id }),
    enabled: q.data?.order?.status === "draft" && mod("storage"),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["order", id] });
    qc.invalidateQueries({ queryKey: ["orders"] });
  };
  const setStatus = useMutation({
    mutationFn: (status: string) => api.patch(`/api/orders/${id}`, { status }),
    onSuccess: refresh,
  });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { order, customer, address, plants, paths, photos } = q.data;
  const est = order.estimate ?? {};
  return (
    <>
      <PageHeader
        eyebrow={`${t(`orders.direction.${order.direction}`)} · ${t("orders.season")} ${order.season}`}
        title={`${order.number} · ${customer?.name ?? ""}`}
        description={
          <>
            {address?.street}, {address?.postal_code} {address?.city} · <StatusBadge status={order.status} />
          </>
        }
        actions={
          <>
            {order.status === "draft" && (
              <button className="btn" onClick={() => setStatus.mutate("confirmed")}>
                {t("orders.confirm")}
              </button>
            )}
            {order.direction === "pickup" && order.status !== "cancelled" && (
              <button
                className="btn ghost"
                onClick={async () => {
                  const r = await api.post(`/api/orders/${id}/return`);
                  navigate(`/betrieb/auftraege/${r.order.id}`);
                }}
              >
                {t("orders.create_return")}
              </button>
            )}
            {order.status !== "cancelled" && (
              <ConfirmButton question={t("orders.cancel_question")} onConfirm={() => setStatus.mutate("cancelled")}>
                {t("orders.cancel")}
              </ConfirmButton>
            )}
          </>
        }
      />
      {order.status === "draft" && occupancy.data?.warn && (
        <div className="alert warn" style={{ marginBottom: 16 }}>
          {t("storage.order_warn", { pct: fmtNumber(occupancy.data.pct) })}
        </div>
      )}
      <div className="grid cols-4" style={{ marginBottom: 20 }}>
        <div className="card tight kpi">
          <span className="kpi-label">{t("orders.plants")}</span>
          <span className="kpi-value">{plants.length}</span>
          <span className="kpi-sub">{fmtNumber(plants.reduce((s: number, p: any) => s + (p.weight_kg ?? 0), 0))} kg</span>
        </div>
        <div className="card tight kpi">
          <span className="kpi-label">{t("orders.duration")}</span>
          <span className="kpi-value">{fmtMinutes(est.duration_min)}</span>
          <span className="kpi-sub">{est.team_size ? t("orders.team_of", { n: est.team_size }) : t("estimate.pending")}</span>
        </div>
        <div className="card tight kpi">
          <span className="kpi-label">{t("orders.labour")}</span>
          <span className="kpi-value">{fmtMinutes(est.labour_min)}</span>
          <span className="kpi-sub">{est.planning_duration_min ? t("estimate.planned_with", { m: fmtMinutes(est.planning_duration_min) }) : ""}</span>
        </div>
        {mod("customer_billing") ? (
          <div className="card tight kpi">
            <span className="kpi-label">{t("orders.price")}</span>
            <span className="kpi-value">{fmtMoney(order.price_quoted)}</span>
            <span className="kpi-sub">{est.price?.coverage_pct != null ? t("estimate.coverage", { pct: fmtNumber(est.price.coverage_pct) }) : ""}</span>
          </div>
        ) : (
          <div className="card tight kpi">
            <span className="kpi-label">{t("orders.logistics_cost")}</span>
            <span className="kpi-value">{fmtMoney(est.plan_costs?.self_cost ?? est.costs?.self_cost)}</span>
            <span className="kpi-sub">{est.plan_costs ? t("orders.cost_from_plan") : t("orders.cost_estimated")}</span>
          </div>
        )}
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { key: "plants", label: `${t("orders.plants")} (${plants.length})` },
          { key: "path", label: t("orders.path") },
          { key: "photos", label: `${t("orders.photos")} (${photos.length})` },
          { key: "estimate", label: t("orders.estimate") },
          { key: "order", label: t("orders.details") },
        ]}
      />
      {tab === "plants" && <PlantsTab orderId={order.id} plants={plants} paths={paths} onChange={refresh} />}
      {tab === "path" && <PathsTab orderId={order.id} paths={paths} onChange={refresh} />}
      {tab === "photos" && <PhotosTab order={order} photos={photos} plants={plants} paths={paths} onChange={refresh} />}
      {tab === "estimate" && <EstimateTab orderId={order.id} estimate={est} onChange={refresh} />}
      {tab === "order" && (
        <Card>
          <EntityForm
            key={order.updated_at}
            entity="order"
            initial={order}
            fields={["status", "earliest_date", "latest_date", "fixed_date", "time_windows", "priority", "price_final", "notes"]}
            onSubmit={async (v) => {
              await api.patch(`/api/orders/${id}`, v);
              refresh();
              toast({ text: t("common.saved") });
            }}
          />
        </Card>
      )}
    </>
  );
}

function EstimateTab({ orderId, estimate, onChange }: { orderId: string; estimate: any; onChange: () => void }) {
  if (!estimate || !estimate.duration_min) {
    return <Empty title={t("estimate.pending")} text={t("estimate.pending_text")} />;
  }
  return <EstimateDetails orderId={orderId} estimate={estimate} onChange={onChange} />;
}

function PlantsTab({ orderId, plants, paths, onChange }: { orderId: string; plants: any[]; paths: any[]; onChange: () => void }) {
  const [editing, setEditing] = useState<any | null>(null);
  const [adding, setAdding] = useState(false);
  const meta = useEntityMeta("plant");
  const byName = new Map((meta.data?.fields ?? []).map((f) => [f.name, f]));
  const cell = (p: any, field: string) => {
    const estimated = (p.estimated_fields ?? []).includes(field);
    const conf = p.field_confidence?.[field];
    return (
      <td className="num" title={estimated ? t("common.estimated") : conf != null ? `${t("common.confidence")}: ${Math.round(conf * 100)} %` : undefined}>
        <span style={estimated ? { color: "var(--text-muted)", fontStyle: "italic" } : undefined}>{formatCell(byName.get(field), p[field])}</span>
        {estimated && <span className="xs faint"> ≈</span>}
      </td>
    );
  };
  return (
    <div className="stack">
      <div className="row between">
        <span className="small muted">{t("plants.estimated_hint")}</span>
        <button className="btn" onClick={() => setAdding(true)}>
          {t("plants.add")}
        </button>
      </div>
      {plants.length === 0 && <Empty title={t("plants.none")} />}
      {plants.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("plants.number")}</th>
                <th>{t("plants.species")}</th>
                <th className="num">{t("plants.height")}</th>
                <th className="num">{t("plants.pot")}</th>
                <th className="num">{t("plants.crown")}</th>
                <th className="num">{t("plants.weight")}</th>
                <th className="num">{t("plants.team")}</th>
                <th>{t("plants.flags")}</th>
              </tr>
            </thead>
            <tbody>
              {plants.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => setEditing(p)}>
                  <td className="num">#{p.number}</td>
                  <td>
                    {p.species_name ?? t("common.unknown")}
                    {p.label && <div className="xs muted">{p.label}</div>}
                  </td>
                  {cell(p, "total_height_cm")}
                  {cell(p, "pot_diameter_cm")}
                  {cell(p, "crown_width_cm")}
                  <td className="num">
                    <span style={(p.estimated_fields ?? []).includes("weight_kg") ? { color: "var(--text-muted)", fontStyle: "italic" } : undefined}>
                      {fmtNumber(p.weight_kg)} kg
                    </span>
                    {p.weight_uncertainty_kg ? <span className="xs faint"> ± {fmtNumber(p.weight_uncertainty_kg)}</span> : null}
                    {p.weight_measured_kg != null && <div className="xs" style={{ color: "var(--success)" }}>{t("plants.weighed", { kg: fmtNumber(p.weight_measured_kg, 1) })}</div>}
                  </td>
                  <td className="num">{p.team_size ?? p.team_size_override ?? "–"}</td>
                  <td>
                    <div className="chip-list">
                      {p.can_tilt && <Badge>{t("plants.tiltable")}</Badge>}
                      {p.sensitive && <Badge tone="amber">{t("plants.sensitive")}</Badge>}
                      {p.frost_sensitive && <Badge tone="blue">{t("plants.frost")}</Badge>}
                      {p.must_secure && <Badge tone="terra">{t("plants.secure")}</Badge>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(editing || adding) && (
        <Modal title={editing ? `${t("plants.plant")} #${editing.number}` : t("plants.add")} onClose={() => (setEditing(null), setAdding(false))} wide>
          <PlantEditor
            plant={editing}
            orderId={orderId}
            paths={paths}
            onDone={() => {
              setEditing(null);
              setAdding(false);
              onChange();
            }}
          />
        </Modal>
      )}
    </div>
  );
}

function PlantEditor({ plant, orderId, paths, onDone }: { plant: any | null; orderId: string; paths: any[]; onDone: () => void }) {
  const [tab, setTab] = useState<"data" | "settings">("data");
  return (
    <>
      {plant && (
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { key: "data", label: t("resource.tab_data") },
            { key: "settings", label: t("resource.tab_settings") },
          ]}
        />
      )}
      {tab === "data" && (
        <EntityForm
          entity="plant"
          initial={plant ?? {}}
          exclude={["weight_uncertainty_kg", "access_path_id"]}
          onCancel={onDone}
          extra={
            plant ? (
              <div className="row">
                {paths.length > 1 && (
                  <select
                    className="input"
                    style={{ width: 240 }}
                    defaultValue={plant.access_path_id ?? ""}
                    aria-label={t("orders.path")}
                    onChange={async (e) => {
                      await api.patch(`/api/plants/${plant.id}`, { access_path_id: e.target.value });
                    }}
                  >
                    {paths.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                )}
                <ConfirmButton
                  onConfirm={async () => {
                    await api.del(`/api/plants/${plant.id}`);
                    onDone();
                  }}
                >
                  {t("common.delete")}
                </ConfirmButton>
              </div>
            ) : undefined
          }
          onSubmit={async (values) => {
            if (plant) await api.patch(`/api/plants/${plant.id}`, values);
            else await api.post(`/api/orders/${orderId}/plants`, values);
            onDone();
          }}
        />
      )}
      {tab === "settings" && plant && <SettingsEditorLazy plantId={plant.id} />}
    </>
  );
}

function SettingsEditorLazy({ plantId }: { plantId: string }) {
  return <SettingsEditor scope="plant" objectId={plantId} compact />;
}

// ----------------------------------------------------------------------------- paths

const SEGMENT_FIELDS: [string, string, string][] = [
  ["kind", "enum", ""],
  ["length_m", "number", "m"],
  ["steps", "number", ""],
  ["height_diff_m", "number", "m"],
  ["min_width_cm", "number", "cm"],
  ["doors", "number", ""],
  ["surface", "enum", ""],
  ["slope_pct", "number", "%"],
  ["elevator", "bool", ""],
];

function PathsTab({ orderId, paths, onChange }: { orderId: string; paths: any[]; onChange: () => void }) {
  const toast = useToast();
  const meta = useEntityMeta("segment");
  const fields = new Map((meta.data?.fields ?? []).map((f) => [f.name, f]));
  const [drafts, setDrafts] = useState<Record<string, any[]>>({});
  const addPath = async () => {
    await api.post(`/api/orders/${orderId}/paths`, { name: t("orders.path") });
    onChange();
  };
  if (paths.length === 0)
    return (
      <Empty
        title={t("paths.none")}
        text={t("paths.none_text")}
        action={
          <button className="btn" onClick={addPath}>
            {t("paths.add")}
          </button>
        }
      />
    );
  return (
    <div className="stack lg">
      {paths.map((p) => {
        const segs = drafts[p.id] ?? p.segments;
        const set = (i: number, k: string, v: any) => setDrafts({ ...drafts, [p.id]: segs.map((s: any, j: number) => (j === i ? { ...s, [k]: v } : s)) });
        return (
          <Card
            key={p.id}
            title={p.name}
            actions={
              <span className="small muted">
                {t("paths.summary", {
                  length: fmtNumber(p.summary.length_m, 1),
                  steps: p.summary.steps,
                  height: fmtNumber(p.summary.height_m, 1),
                  width: p.summary.min_width_cm ? `${fmtNumber(p.summary.min_width_cm)} cm` : "–",
                })}
              </span>
            }
          >
            <div className="row" style={{ marginBottom: 12 }}>
              <label className="small" htmlFor={`len-${p.id}`}>
                {t("paths.confirmed_length")}
              </label>
              <input
                id={`len-${p.id}`}
                className="input num"
                style={{ width: 110 }}
                type="number"
                defaultValue={p.length_confirmed_m ?? ""}
                onBlur={async (e) => {
                  await api.patch(`/api/paths/${p.id}`, { length_confirmed_m: e.target.value === "" ? null : Number(e.target.value) });
                  onChange();
                }}
              />
              <span className="small muted">m · {t("paths.confirmed_length_help")}</span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {SEGMENT_FIELDS.map(([f, , unit]) => (
                      <th key={f}>
                        {fields.get(f)?.label ?? f}
                        {unit && <span className="faint"> ({unit})</span>}
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {segs.map((s: any, i: number) => (
                    <tr key={i}>
                      {SEGMENT_FIELDS.map(([f, kind]) => (
                        <td key={f}>
                          {kind === "enum" ? (
                            <select className="input" value={s[f] ?? ""} onChange={(e) => set(i, f, e.target.value)} aria-label={fields.get(f)?.label}>
                              {(fields.get(f)?.enum ?? []).map((v) => (
                                <option key={v} value={v}>
                                  {fields.get(f)?.enum_labels[v] ?? v}
                                </option>
                              ))}
                            </select>
                          ) : kind === "bool" ? (
                            <input type="checkbox" checked={!!s[f]} onChange={(e) => set(i, f, e.target.checked)} aria-label={fields.get(f)?.label} />
                          ) : (
                            <input
                              className="input num"
                              style={{ width: 80 }}
                              type="number"
                              value={s[f] ?? ""}
                              onChange={(e) => set(i, f, e.target.value === "" ? null : Number(e.target.value))}
                              aria-label={fields.get(f)?.label}
                            />
                          )}
                        </td>
                      ))}
                      <td>
                        <button className="btn small ghost" onClick={() => setDrafts({ ...drafts, [p.id]: segs.filter((_: any, j: number) => j !== i) })}>
                          {t("common.remove")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="btn secondary small"
                onClick={() => setDrafts({ ...drafts, [p.id]: [...segs, { kind: "flat", length_m: 5, steps: 0, height_diff_m: 0, surface: "paved", doors: 0, slope_pct: 0 }] })}
              >
                {t("paths.add_segment")}
              </button>
              {drafts[p.id] && (
                <button
                  className="btn small"
                  onClick={async () => {
                    await api.put(`/api/paths/${p.id}/segments`, { segments: drafts[p.id] });
                    const next = { ...drafts };
                    delete next[p.id];
                    setDrafts(next);
                    onChange();
                    toast({ text: t("common.saved") });
                  }}
                >
                  {t("common.save")}
                </button>
              )}
              <span className="grow" />
              <ConfirmButton
                onConfirm={async () => {
                  await api.del(`/api/paths/${p.id}`);
                  onChange();
                }}
              >
                {t("paths.delete")}
              </ConfirmButton>
            </div>
          </Card>
        );
      })}
      <div>
        <button className="btn secondary" onClick={addPath}>
          {t("paths.add")}
        </button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- photos

function PhotosTab({ order, photos, plants, paths, onChange }: { order: any; photos: any[]; plants: any[]; paths: any[]; onChange: () => void }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const check = order.estimate?.photo_check;
  const run = async (kind: "photo-check" | "photo-analysis") => {
    try {
      const r = await api.post(`/api/orders/${order.id}/${kind}`);
      setJobId(r.job_id);
    } catch (e) {
      if (e instanceof ApiError) alert(e.message);
    }
  };
  const finished = job.data && (job.data.status === "done" || job.data.status === "failed");
  useEffect(() => {
    if (finished) onChange();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);
  return (
    <div className="stack lg">
      <div className="row">
        <button className="btn secondary" onClick={() => run("photo-check")} disabled={!photos.length}>
          {t("photos.check")}
        </button>
        <button className="btn secondary" onClick={() => run("photo-analysis")} disabled={!photos.length}>
          {t("photos.analyse")}
        </button>
        {job.data && <JobStatus job={job.data} />}
      </div>
      {check && (
        <div className={`alert ${check.overall_ok ? "ok" : "warn"}`}>
          <strong>{check.overall_ok ? t("photos.complete") : t("photos.incomplete")}</strong>
          {(check.feedback ?? []).length > 0 && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {check.feedback.map((f: string) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <PhotoGallery photos={photos} orderId={order.id} plants={plants} paths={paths} onChange={onChange} />
    </div>
  );
}

export { Confidence };
