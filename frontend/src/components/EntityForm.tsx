// Forms and tables generated from /api/meta/entities/<name> (server-side column metadata).
import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../auth/auth";
import { fmtDate, fmtNumber, t, tMaybe } from "../i18n";
import { ErrorBox, Spinner } from "./ui";

export type FieldMeta = {
  name: string;
  type: string;
  nullable: boolean;
  required: boolean;
  writable: boolean;
  unit: string | null;
  group: string | null;
  enum: string[] | null;
  enum_labels: Record<string, string>;
  fk: string | null;
  options: string[] | null;
  min: number | null;
  max: number | null;
  list: boolean;
  /** not used by any calculation: shown folded under "Weitere Angaben" */
  advanced: boolean;
  /** optional module the field belongs to; hidden while the module is off */
  module: string | null;
  label: string;
  help: string;
};

export type EntityMeta = { name: string; settings_scope: string | null; fields: FieldMeta[] };

/** REST collection URL per entity, used for foreign-key selects. */
export const ENTITY_URLS: Record<string, string> = {
  staff: "/api/staff",
  vehicle: "/api/vehicles",
  equipment: "/api/equipment",
  customer: "/api/customers",
  address: "/api/addresses",
  order: "/api/orders",
  plant: "/api/plants",
  species: "/api/species",
  team: "/api/teams",
  storage_area: "/api/storage-areas",
};

export function useEntityMeta(name: string) {
  return useQuery({
    queryKey: ["meta", name],
    queryFn: () => api.get<EntityMeta>(`/api/meta/entities/${name}`),
    staleTime: Infinity,
  });
}

function FkSelect(props: { entity: string; value: string | null; onChange: (v: string | null) => void; id: string; required: boolean }) {
  const url = ENTITY_URLS[props.entity];
  const q = useQuery({ queryKey: ["fk", props.entity], queryFn: () => api.get<any[]>(url), enabled: !!url });
  return (
    <select id={props.id} className="input" value={props.value ?? ""} onChange={(e) => props.onChange(e.target.value || null)}>
      {!props.required && <option value="">–</option>}
      {(q.data ?? []).map((row) => (
        <option key={row.id} value={row.id}>
          {row.display_name ?? row.name ?? row.label ?? row.number ?? row.id}
        </option>
      ))}
    </select>
  );
}

function StaffMulti(props: { id: string; value: string[] | null; onChange: (v: string[]) => void }) {
  const q = useQuery({ queryKey: ["fk", "staff"], queryFn: () => api.get<any[]>("/api/staff") });
  const current = props.value ?? [];
  return (
    <div className="chip-list" id={props.id} role="group">
      {(q.data ?? []).map((s) => (
        <label key={s.id} className="checkbox" style={{ marginRight: 12 }}>
          <input
            type="checkbox"
            checked={current.includes(s.id)}
            onChange={(e) => props.onChange(e.target.checked ? [...current, s.id] : current.filter((x) => x !== s.id))}
          />
          <span>{s.name}</span>
        </label>
      ))}
    </div>
  );
}

const WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

/** Weekdays 0 = Monday … 6 = Sunday; empty list = every day. */
function WeekdaysInput(props: { id: string; value: number[] | null; onChange: (v: number[]) => void }) {
  const current = props.value ?? [];
  return (
    <div className="row" id={props.id} role="group" style={{ gap: 8 }}>
      {WEEKDAY_SHORT.map((d, i) => (
        <label key={d} className="checkbox small">
          <input
            type="checkbox"
            checked={current.includes(i)}
            onChange={(e) => props.onChange(e.target.checked ? [...current, i].sort() : current.filter((x) => x !== i))}
          />
          {d}
        </label>
      ))}
    </div>
  );
}

export function fmtWeekdays(days: number[] | null | undefined): string {
  if (!days || !days.length) return t("teams.weekdays_all");
  return days.map((d) => WEEKDAY_SHORT[d]).join(", ");
}

function WindowsInput(props: { id: string; value: { from: string; to: string; date?: string }[] | null; onChange: (v: any[]) => void }) {
  const list = props.value ?? [];
  return (
    <div className="stack" id={props.id} style={{ gap: 6 }}>
      {list.map((w, i) => (
        <div className="row" key={i}>
          <input type="date" className="input" style={{ width: 160 }} value={w.date ?? ""} aria-label={t("common.date")}
            onChange={(e) => props.onChange(list.map((x, j) => (j === i ? { ...x, date: e.target.value || undefined } : x)))} />
          <input type="time" className="input" style={{ width: 120 }} value={w.from} aria-label={t("common.from")}
            onChange={(e) => props.onChange(list.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)))} />
          <span>–</span>
          <input type="time" className="input" style={{ width: 120 }} value={w.to} aria-label={t("common.to")}
            onChange={(e) => props.onChange(list.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))} />
          <button type="button" className="btn small ghost" onClick={() => props.onChange(list.filter((_, j) => j !== i))}>
            {t("common.remove")}
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn small secondary" onClick={() => props.onChange([...list, { from: "08:00", to: "12:00" }])}>
          {t("form.add_window")}
        </button>
      </div>
    </div>
  );
}

export function FieldInput(props: { f: FieldMeta; value: any; onChange: (v: any) => void; id: string }) {
  const { f, value, onChange, id } = props;
  if (f.type === "bool")
    return (
      <label className="checkbox">
        <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        <span>{value ? t("common.yes") : t("common.no")}</span>
      </label>
    );
  if (f.enum)
    return (
      <select id={id} className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        {!f.required && <option value="">–</option>}
        {f.enum.map((v) => (
          <option key={v} value={v}>
            {f.enum_labels[v] ?? v}
          </option>
        ))}
      </select>
    );
  if (f.fk) return <FkSelect entity={f.fk} value={value} onChange={onChange} id={id} required={f.required} />;
  if (f.type === "tags" && f.options) {
    const current: string[] = Array.isArray(value) ? value : [];
    return (
      <div className="row" id={id} role="group" style={{ gap: 12 }}>
        {f.options.map((o) => (
          <label key={o} className="checkbox">
            <input
              type="checkbox"
              checked={current.includes(o)}
              onChange={(e) => onChange(e.target.checked ? [...current, o] : current.filter((x) => x !== o))}
            />
            <span>{o}</span>
          </label>
        ))}
      </div>
    );
  }
  if (f.type === "staff_multi") return <StaffMulti id={id} value={value} onChange={onChange} />;
  if (f.type === "windows") return <WindowsInput id={id} value={value} onChange={onChange} />;
  if (f.type === "weekdays") return <WeekdaysInput id={id} value={value} onChange={onChange} />;
  if (f.type === "text")
    return <textarea id={id} className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} />;
  if (f.type === "json" || f.type === "tags") {
    const text = Array.isArray(value) ? value.join(", ") : value ? JSON.stringify(value) : "";
    return (
      <input
        id={id}
        className="input"
        value={text}
        placeholder={f.type === "tags" ? t("form.tags_placeholder") : ""}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    );
  }
  const isNum = f.type === "int" || f.type === "float";
  const inputType = isNum ? "number" : f.type === "date" ? "date" : f.type === "time" ? "time" : f.type === "datetime" ? "datetime-local" : "text";
  const input = (
    <input
      id={id}
      className={`input ${isNum ? "num" : ""}`}
      type={inputType}
      step={f.type === "float" ? "any" : undefined}
      min={f.min ?? undefined}
      max={f.max ?? undefined}
      required={f.required}
      value={value ?? ""}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") onChange(null);
        else onChange(isNum ? Number(raw) : raw);
      }}
    />
  );
  if (!f.unit) return input;
  return (
    <div className="input-unit">
      {input}
      <span className="unit">{f.unit}</span>
    </div>
  );
}

export function EntityForm(props: {
  entity: string;
  initial?: Record<string, any>;
  onSubmit: (values: Record<string, any>) => Promise<unknown> | void;
  fields?: string[];
  exclude?: string[];
  submitLabel?: string;
  onCancel?: () => void;
  extra?: ReactNode;
}) {
  const meta = useEntityMeta(props.entity);
  const { mod } = useAuth();
  const [values, setValues] = useState<Record<string, any>>(props.initial ?? {});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const fields = useMemo(() => {
    const all = (meta.data?.fields ?? []).filter((f) => f.writable && (!f.module || mod(f.module)));
    const picked = props.fields ? props.fields.map((n) => all.find((f) => f.name === n)).filter(Boolean) as FieldMeta[] : all;
    return picked.filter((f) => !props.exclude?.includes(f.name));
  }, [meta.data, props.fields, props.exclude, mod]);

  const grouped = (list: FieldMeta[]) => {
    const out: { key: string; fields: FieldMeta[] }[] = [];
    for (const f of list) {
      const g = f.group ?? "_";
      let entry = out.find((x) => x.key === g);
      if (!entry) out.push((entry = { key: g, fields: [] }));
      entry.fields.push(f);
    }
    return out;
  };
  const groups = useMemo(() => grouped(fields.filter((f) => !f.advanced)), [fields]);
  // fields no calculation needs are folded away; required ones always stay visible
  const advanced = useMemo(() => fields.filter((f) => f.advanced && !f.required), [fields]);

  if (meta.isLoading) return <Spinner />;
  if (meta.error) return <ErrorBox error={meta.error} />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, any> = {};
      for (const f of fields) if (f.name in values) payload[f.name] = values[f.name];
      await props.onSubmit(payload);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const renderField = (f: FieldMeta) => {
    const id = `f-${props.entity}-${f.name}`;
    const wide = f.type === "text" || f.type === "json";
    return (
      <div className="field" key={f.name} style={wide ? { gridColumn: "1 / -1" } : undefined}>
        <label htmlFor={id}>
          {f.label}
          {f.required && <span aria-hidden="true"> *</span>}
        </label>
        <FieldInput f={f} id={id} value={values[f.name]} onChange={(v) => setValues((s) => ({ ...s, [f.name]: v }))} />
        {f.help && <span className="help">{f.help}</span>}
      </div>
    );
  };
  const filledAdvanced = advanced.filter((f) => values[f.name] !== null && values[f.name] !== undefined && values[f.name] !== "" && !(Array.isArray(values[f.name]) && !values[f.name].length)).length;

  return (
    <form onSubmit={submit} className="stack lg">
      {groups.map((g) => (
        <div className="form-section" key={g.key}>
          {groups.length > 1 && g.key !== "_" && <h4>{tMaybe(`fields.groups.${g.key}`) ?? g.key}</h4>}
          <div className="form-grid">{g.fields.map(renderField)}</div>
        </div>
      ))}
      {advanced.length > 0 && (
        <details className="form-more">
          <summary>
            {t("form.more")}
            <span className="faint small"> · {t("form.more_hint", { n: advanced.length, filled: filledAdvanced })}</span>
          </summary>
          <div className="form-grid" style={{ marginTop: 12 }}>
            {advanced.map(renderField)}
          </div>
        </details>
      )}
      {props.extra}
      <ErrorBox error={error} />
      <div className="row end">
        {props.onCancel && (
          <button type="button" className="btn ghost" onClick={props.onCancel}>
            {t("common.cancel")}
          </button>
        )}
        <button className="btn" type="submit" disabled={busy}>
          {props.submitLabel ?? t("common.save")}
        </button>
      </div>
    </form>
  );
}

export function formatCell(f: FieldMeta | undefined, value: any): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="faint">–</span>;
  if (!f) return String(value);
  if (f.type === "bool") return value ? t("common.yes") : t("common.no");
  if (f.enum) return f.enum_labels[value] ?? value;
  if (f.type === "float") return `${fmtNumber(value, Number.isInteger(value) ? 0 : 1)}${f.unit ? " " + f.unit : ""}`;
  if (f.type === "int") return `${fmtNumber(value)}${f.unit ? " " + f.unit : ""}`;
  if (f.type === "datetime") return fmtDate(value, true);
  if (f.type === "date") return fmtDate(value);
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function EntityTable(props: {
  entity: string;
  rows: any[];
  columns: string[];
  onRowClick?: (row: any) => void;
  render?: Record<string, (row: any) => ReactNode>;
  labels?: Record<string, string>;
  actions?: (row: any) => ReactNode;
}) {
  const meta = useEntityMeta(props.entity);
  const byName = new Map((meta.data?.fields ?? []).map((f) => [f.name, f]));
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {props.columns.map((c) => {
              const f = byName.get(c);
              const numeric = f && (f.type === "int" || f.type === "float");
              return (
                <th key={c} className={numeric ? "num" : undefined}>
                  {props.labels?.[c] ?? f?.label ?? c}
                </th>
              );
            })}
            {props.actions && <th />}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row) => (
            <tr key={row.id} className={props.onRowClick ? "clickable" : undefined} onClick={() => props.onRowClick?.(row)}>
              {props.columns.map((c) => {
                const f = byName.get(c);
                const numeric = f && (f.type === "int" || f.type === "float");
                return (
                  <td key={c} className={numeric ? "num" : undefined}>
                    {props.render?.[c] ? props.render[c](row) : formatCell(f, row[c])}
                  </td>
                );
              })}
              {props.actions && (
                <td className="num" onClick={(e) => e.stopPropagation()}>
                  {props.actions(row)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
