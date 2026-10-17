// Forms and tables generated from /api/meta/entities/<name> (server-side column metadata).
import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
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
  min: number | null;
  max: number | null;
  list: boolean;
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
  const [values, setValues] = useState<Record<string, any>>(props.initial ?? {});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const fields = useMemo(() => {
    const all = (meta.data?.fields ?? []).filter((f) => f.writable);
    const picked = props.fields ? props.fields.map((n) => all.find((f) => f.name === n)).filter(Boolean) as FieldMeta[] : all;
    return picked.filter((f) => !props.exclude?.includes(f.name));
  }, [meta.data, props.fields, props.exclude]);

  const groups = useMemo(() => {
    const out: { key: string; fields: FieldMeta[] }[] = [];
    for (const f of fields) {
      const g = f.group ?? "_";
      let entry = out.find((x) => x.key === g);
      if (!entry) out.push((entry = { key: g, fields: [] }));
      entry.fields.push(f);
    }
    return out;
  }, [fields]);

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

  return (
    <form onSubmit={submit} className="stack lg">
      {groups.map((g) => (
        <div className="form-section" key={g.key}>
          {groups.length > 1 && g.key !== "_" && <h4>{tMaybe(`fields.groups.${g.key}`) ?? g.key}</h4>}
          <div className="form-grid">
            {g.fields.map((f) => {
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
            })}
          </div>
        </div>
      ))}
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
