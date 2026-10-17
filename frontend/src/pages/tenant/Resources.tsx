import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ResourcePage } from "../../components/ResourcePage";
import { Badge, Card, ConfirmButton, ErrorBox, Kpi, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtDate, fmtNumber, t } from "../../i18n";

export function StaffPage() {
  return (
    <ResourcePage
      entity="staff"
      url="/api/staff"
      title={t("nav.staff")}
      description={t("resources.staff_description")}
      columns={["name", "licences", "qualifications", "active"]}
      settingsScope="staff"
      settingsGroups={["staff", "costs", "planning"]}
      extraTabs={[{ key: "availability", label: t("resources.availability"), render: (row) => <AvailabilityRules type="staff" id={row.id} /> }]}
    />
  );
}

export function TeamsPage() {
  const staff = useQuery({ queryKey: ["fk", "staff"], queryFn: () => api.get<any[]>("/api/staff") });
  const names = new Map((staff.data ?? []).map((s) => [s.id, s.name]));
  return (
    <ResourcePage
      entity="team"
      url="/api/teams"
      title={t("resources.teams")}
      description={t("resources.teams_description")}
      columns={["name", "member_ids", "vehicle_id", "active"]}
      render={{ member_ids: (r) => (r.member_ids ?? []).map((id: string) => names.get(id) ?? "?").join(", ") }}
    />
  );
}

export function VehiclesPage() {
  return (
    <ResourcePage
      entity="vehicle"
      url="/api/vehicles"
      title={t("nav.vehicles")}
      description={t("resources.vehicles_description")}
      columns={["name", "plate", "kind", "required_licence", "cargo_length_cm", "cargo_width_cm", "cargo_height_cm", "payload_kg"]}
      settingsScope="vehicle"
      settingsGroups={["drive", "costs", "planning"]}
      extraTabs={[
        { key: "shelves", label: t("resources.shelves"), render: (row) => <ShelfEditor vehicle={row} /> },
        { key: "availability", label: t("resources.availability"), render: (row) => <AvailabilityRules type="vehicle" id={row.id} /> },
      ]}
    />
  );
}

export function EquipmentPage() {
  return (
    <ResourcePage
      entity="equipment"
      url="/api/equipment"
      title={t("nav.equipment")}
      description={t("resources.equipment_description")}
      columns={["name", "kind", "count", "capacity_kg", "solo_limit_kg", "carry_time_factor", "usable_on_stairs", "vehicle_id"]}
      settingsScope="equipment"
      settingsGroups={["costs"]}
    />
  );
}

// ----------------------------------------------------------------------------- shelves

function ShelfEditor({ vehicle }: { vehicle: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["shelves", vehicle.id], queryFn: () => api.get<any[]>("/api/shelves", { filter: [`vehicle_id=${vehicle.id}`] }) });
  const [rows, setRows] = useState<any[] | null>(null);
  const list = rows ?? q.data ?? [];
  const fields: [string, string][] = [
    ["name", ""], ["x_cm", "cm"], ["y_cm", "cm"], ["length_cm", "cm"], ["depth_cm", "cm"], ["height_cm", "cm"], ["clearance_cm", "cm"], ["max_load_kg", "kg"],
  ];
  const set = (i: number, k: string, v: any) => setRows(list.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = async () => {
    await api.put(`/api/vehicles/${vehicle.id}/shelves`, { shelves: list });
    setRows(null);
    qc.invalidateQueries({ queryKey: ["shelves", vehicle.id] });
    toast({ text: t("common.saved") });
  };
  if (q.isLoading) return <Spinner />;
  return (
    <div className="stack">
      <p className="muted small">{t("resources.shelves_help", { l: vehicle.cargo_length_cm, w: vehicle.cargo_width_cm, h: vehicle.cargo_height_cm })}</p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              {fields.map(([f, unit]) => (
                <th key={f}>
                  {t(`resources.shelf_fields.${f}`)}
                  {unit && <span className="faint"> ({unit})</span>}
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => (
              <tr key={i}>
                {fields.map(([f]) => (
                  <td key={f}>
                    <input
                      className="input num"
                      style={{ minWidth: f === "name" ? 140 : 70 }}
                      type={f === "name" ? "text" : "number"}
                      value={r[f] ?? ""}
                      onChange={(e) => set(i, f, f === "name" ? e.target.value : Number(e.target.value))}
                      aria-label={t(`resources.shelf_fields.${f}`)}
                    />
                  </td>
                ))}
                <td>
                  <button className="btn small ghost" onClick={() => setRows(list.filter((_, j) => j !== i))}>
                    {t("common.remove")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button
          className="btn secondary"
          onClick={() => setRows([...list, { name: t("resources.shelf"), x_cm: 0, y_cm: 0, length_cm: 120, depth_cm: 40, height_cm: 90, clearance_cm: 60, max_load_kg: 60 }])}
        >
          {t("resources.add_shelf")}
        </button>
        {rows && (
          <button className="btn" onClick={save}>
            {t("common.save")}
          </button>
        )}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- availability

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

export function AvailabilityRules({ type, id }: { type: "staff" | "vehicle"; id: string }) {
  const qc = useQueryClient();
  const key = ["availability", id];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<any[]>("/api/availability", { filter: [`resource_id=${id}`] }) });
  const [form, setForm] = useState({ kind: "vacation", date_from: "", date_to: "", start_time: "", end_time: "", weekdays: [] as number[], note: "" });
  const [error, setError] = useState<unknown>(null);
  const add = async () => {
    setError(null);
    try {
      await api.post("/api/availability", {
        resource_type: type, resource_id: id, kind: form.kind,
        date_from: form.date_from || null, date_to: form.date_to || form.date_from || null,
        start_time: form.start_time || null, end_time: form.end_time || null, weekdays: form.weekdays, note: form.note || null,
      });
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["calendar"] });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="stack lg">
      <p className="muted small">{t("resources.availability_help")}</p>
      {(q.data ?? []).length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {(q.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>
                    <Badge tone={r.kind === "available" ? "green" : "amber"}>{t(`availability.kinds.${r.kind}`)}</Badge>
                  </td>
                  <td className="small">
                    {r.date_from ? `${fmtDate(r.date_from)} – ${fmtDate(r.date_to)}` : t("availability.always")}
                    {r.weekdays?.length ? ` · ${r.weekdays.map((d: number) => WEEKDAYS[d]).join(", ")}` : ""}
                    {r.start_time ? ` · ${r.start_time.slice(0, 5)}–${(r.end_time ?? "").slice(0, 5)}` : ""}
                  </td>
                  <td className="small muted">{r.note}</td>
                  <td className="num">
                    <ConfirmButton
                      onConfirm={async () => {
                        await api.del(`/api/availability/${r.id}`);
                        qc.invalidateQueries({ queryKey: key });
                      }}
                    >
                      {t("common.delete")}
                    </ConfirmButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Card title={t("availability.add")}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="av-kind">{t("availability.kind")}</label>
            <select id="av-kind" className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {["vacation", "sick", "unavailable", "maintenance", "available"].map((k) => (
                <option key={k} value={k}>
                  {t(`availability.kinds.${k}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="av-from">{t("common.from")}</label>
            <input id="av-from" type="date" className="input" value={form.date_from} onChange={(e) => setForm({ ...form, date_from: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="av-to">{t("common.to")}</label>
            <input id="av-to" type="date" className="input" value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="av-st">{t("availability.start")}</label>
            <input id="av-st" type="time" className="input" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="av-en">{t("availability.end")}</label>
            <input id="av-en" type="time" className="input" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
          </div>
          <div className="field">
            <span className="label">{t("availability.weekdays")}</span>
            <div className="row" style={{ gap: 6 }}>
              {WEEKDAYS.map((d, i) => (
                <label key={d} className="checkbox small">
                  <input
                    type="checkbox"
                    checked={form.weekdays.includes(i)}
                    onChange={(e) => setForm({ ...form, weekdays: e.target.checked ? [...form.weekdays, i] : form.weekdays.filter((x) => x !== i) })}
                  />
                  {d}
                </label>
              ))}
            </div>
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label htmlFor="av-note">{t("availability.note")}</label>
            <input id="av-note" className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
        </div>
        <ErrorBox error={error} />
        <div className="row end" style={{ marginTop: 12 }}>
          <button className="btn" onClick={add}>
            {t("common.add")}
          </button>
        </div>
      </Card>
    </div>
  );
}

function mondayOf(d: Date): Date {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - day);
  return x;
}

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function AvailabilityPage() {
  const [start, setStart] = useState(() => mondayOf(new Date()));
  const [edit, setEdit] = useState<{ type: "staff" | "vehicle"; id: string; name: string } | null>(null);
  const days = 21;
  const q = useQuery({ queryKey: ["calendar", iso(start)], queryFn: () => api.get<any>("/api/availability-calendar", { start: iso(start), days }) });
  const dates = Array.from({ length: days }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });
  const shift = (n: number) => {
    const d = new Date(start);
    d.setDate(d.getDate() + n);
    setStart(d);
  };
  const cell = (info: any) => {
    if (!info) return null;
    const bg = info.available ? (info.reason ? "var(--warning-soft)" : "var(--success-soft)") : info.reason === "weekend" || info.reason === "no_pattern" ? "var(--surface-2)" : "var(--danger-soft)";
    const title = info.available ? `${info.start}–${info.end}${info.reason ? " (" + t(`availability.kinds.${info.reason}`) + ")" : ""}` : t(`availability.reasons.${info.reason}`);
    return (
      <td title={title} style={{ background: bg, padding: 0, minWidth: 30, height: 34, textAlign: "center", fontSize: 11 }}>
        {info.available ? (info.reason ? "½" : "") : info.reason === "weekend" || info.reason === "no_pattern" ? "" : "✕"}
      </td>
    );
  };
  const section = (label: string, type: "staff" | "vehicle", rows: any[]) => (
    <>
      <tr>
        <th colSpan={days + 1} style={{ background: "var(--surface-3)" }}>
          {label}
        </th>
      </tr>
      {rows.map((r) => (
        <tr key={r.id}>
          <td style={{ whiteSpace: "nowrap" }}>
            <button className="btn link" onClick={() => setEdit({ type, id: r.id, name: r.name })}>
              {r.name}
            </button>
          </td>
          {dates.map((d) => cell(r.days[iso(d)]))}
        </tr>
      ))}
    </>
  );
  return (
    <>
      <PageHeader
        title={t("nav.availability")}
        description={t("availability.description")}
        actions={
          <>
            <button className="btn ghost" onClick={() => shift(-7)}>
              ←
            </button>
            <button className="btn ghost" onClick={() => setStart(mondayOf(new Date()))}>
              {t("availability.today")}
            </button>
            <button className="btn ghost" onClick={() => shift(7)}>
              →
            </button>
          </>
        }
      />
      {q.isLoading && <Spinner />}
      {q.data && (
        <div className="table-wrap">
          <table className="table" style={{ fontSize: 13 }}>
            <thead>
              <tr>
                <th />
                {dates.map((d) => (
                  <th key={iso(d)} style={{ padding: "6px 2px", textAlign: "center", color: d.getDay() % 6 === 0 ? "var(--text-faint)" : undefined }}>
                    {WEEKDAYS[(d.getDay() + 6) % 7]}
                    <br />
                    {d.getDate()}.{d.getMonth() + 1}.
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section(t("nav.staff"), "staff", q.data.staff)}
              {section(t("nav.vehicles"), "vehicle", q.data.vehicles)}
            </tbody>
          </table>
        </div>
      )}
      <div className="row small muted" style={{ marginTop: 12, gap: 16 }}>
        <span><span className="badge green">&nbsp;</span> {t("availability.legend_available")}</span>
        <span><span className="badge amber">½</span> {t("availability.legend_partial")}</span>
        <span><span className="badge red">✕</span> {t("availability.legend_absent")}</span>
      </div>
      {edit && (
        <Modal title={`${t("resources.availability")}: ${edit.name}`} onClose={() => setEdit(null)} wide>
          <AvailabilityRules type={edit.type} id={edit.id} />
        </Modal>
      )}
    </>
  );
}

// ----------------------------------------------------------------------------- storage

export function StoragePage() {
  const occ = useQuery({ queryKey: ["occupancy"], queryFn: () => api.get<any>("/api/storage/occupancy") });
  const o = occ.data;
  return (
    <>
      <ResourcePage
        entity="storage_area"
        url="/api/storage-areas"
        title={t("nav.storage")}
        description={t("storage.description")}
        columns={["name", "kind", "area_m2", "height_cm", "min_temp_c", "for_frost_sensitive"]}
      />
      {o && (
        <div className="stack lg" style={{ marginTop: 24 }}>
          {o.warn && <div className="alert warn">{o.over ? t("storage.over") : t("storage.warn")}</div>}
          <div className="grid cols-4">
            <Kpi label={t("storage.capacity")} value={`${fmtNumber(o.capacity_m2)} m²`} />
            <Kpi label={t("storage.stored")} value={`${fmtNumber(o.stored_m2, 1)} m²`} />
            <Kpi label={t("storage.expected")} value={`${fmtNumber(o.expected_m2, 1)} m²`} />
            <Kpi label={t("storage.utilisation")} value={o.pct != null ? `${fmtNumber(o.pct)} %` : "–"} sub={t("storage.frost", { m2: fmtNumber(o.frost_sensitive_m2, 1), warm: fmtNumber(o.warm_capacity_m2) })} />
          </div>
        </div>
      )}
    </>
  );
}
