// Tables (round 2, package P): spreadsheet-like overviews of plants, orders, customers and tour stops.
// Tick the columns you want (addresses, plant images, plant names …), sort by clicking a header, filter,
// group, edit cells with a double click (saved through the normal endpoints) and export to Excel/CSV.
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/auth";
import { Thumb, type PlantImg } from "../../components/PlantImage";
import { Badge, Empty, ErrorBox, PageHeader, Segmented, Spinner, useToast } from "../../components/ui";
import { fmtDate, fmtNumber, t } from "../../i18n";

type Col = { key: string; type: "text" | "number" | "bool" | "date" | "image" | "images" | "status"; label: string; edit: string | null; default: boolean };
type Source = "plants" | "orders" | "customers" | "stops";
type Img = PlantImg;

const EDIT_URL: Record<Source, ((row: any) => string) | null> = {
  plants: (r) => `/api/plants/${r.id}`,
  orders: (r) => `/api/orders/${r.id}`,
  customers: (r) => `/api/customers/${r.id}`,
  stops: null,
};

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode: the view is kept for this visit only */
  }
}

function text(col: Col, v: any): string {
  if (v === null || v === undefined) return "";
  if (col.type === "date") return fmtDate(v);
  if (col.type === "bool") return v ? t("common.yes") : t("common.no");
  if (col.type === "number") return fmtNumber(v, Number.isInteger(v) ? 0 : 1);
  if (col.type === "status") return t(`orders.status.${v}`) === `orders.status.${v}` ? String(v) : t(`orders.status.${v}`);
  return String(v);
}

function Cell({ col, row }: { col: Col; row: any }) {
  const v = row[col.key];
  if (col.type === "image") return <Thumb img={v} />;
  if (col.type === "images")
    return (
      <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
        {(v ?? []).slice(0, 4).map((img: Img, i: number) => (
          <Thumb key={i} img={img} size={34} />
        ))}
      </span>
    );
  if (col.type === "status") return v ? <Badge>{text(col, v)}</Badge> : null;
  const estimated = (row.estimated ?? []).includes(col.edit ?? "");
  return <span style={estimated ? { color: "var(--text-muted)", fontStyle: "italic" } : undefined}>{text(col, v)}{estimated ? " ≈" : ""}</span>;
}

function EditCell({ col, row, onSave, onCancel }: { col: Col; row: any; onSave: (v: any) => void; onCancel: () => void }) {
  const [v, setV] = useState<any>(row[col.key] ?? "");
  const commit = () => {
    let out: any = v;
    if (col.type === "number") out = v === "" ? null : Number(String(v).replace(",", "."));
    if (col.type === "text" && v === "") out = null;
    onSave(out);
  };
  if (col.type === "bool")
    return (
      <select autoFocus className="input" value={v === "" || v === null ? "" : String(v)} onChange={(e) => onSave(e.target.value === "" ? null : e.target.value === "true")} onBlur={onCancel}>
        <option value="">–</option>
        <option value="true">{t("common.yes")}</option>
        <option value="false">{t("common.no")}</option>
      </select>
    );
  return (
    <input
      autoFocus
      className={`input ${col.type === "number" ? "num" : ""}`}
      type={col.type === "date" ? "date" : "text"}
      inputMode={col.type === "number" ? "decimal" : undefined}
      value={v ?? ""}
      onChange={(e) => setV(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") onCancel();
      }}
      onBlur={commit}
    />
  );
}

export function TablesPage() {
  const { has } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [source, setSource] = useState<Source>(() => load("kp.tables.source", "plants"));
  const q = useQuery({ queryKey: ["tables", source], queryFn: () => api.get<{ columns: Col[]; rows: any[] }>(`/api/tables/${source}`) });
  const cols = useMemo(() => q.data?.columns ?? [], [q.data]);
  const [visible, setVisible] = useState<string[] | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [group, setGroup] = useState<string>("");
  const [showCols, setShowCols] = useState(false);
  const [editing, setEditing] = useState<{ id: string; key: string } | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    save("kp.tables.source", source);
    setVisible(null);
    setSort(null);
    setGroup(load(`kp.tables.${source}.group`, ""));
  }, [source]);
  useEffect(() => {
    if (cols.length && visible === null) setVisible(load(`kp.tables.${source}.cols`, cols.filter((c) => c.default).map((c) => c.key)));
  }, [cols, visible, source]);
  const shown = useMemo(() => cols.filter((c) => (visible ?? []).includes(c.key)), [cols, visible]);
  const toggle = (key: string) => {
    const next = (visible ?? []).includes(key) ? (visible ?? []).filter((k) => k !== key) : cols.map((c) => c.key).filter((k) => k === key || (visible ?? []).includes(k));
    setVisible(next);
    save(`kp.tables.${source}.cols`, next);
  };
  const rows = useMemo(() => {
    let out = q.data?.rows ?? [];
    const f = filter.trim().toLowerCase();
    if (f) out = out.filter((r) => shown.some((c) => !["image", "images"].includes(c.type) && text(c, r[c.key]).toLowerCase().includes(f)));
    if (sort) {
      const col = cols.find((c) => c.key === sort.key);
      out = [...out].sort((a, b) => {
        const x = a[sort.key];
        const y = b[sort.key];
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        const cmp = col?.type === "number" ? x - y : String(text(col!, x)).localeCompare(String(text(col!, y)), "de", { numeric: true });
        return cmp * sort.dir;
      });
    }
    return out;
  }, [q.data, filter, sort, shown, cols]);
  const groups = useMemo(() => {
    if (!group) return [{ key: "", rows }];
    const col = cols.find((c) => c.key === group);
    const map = new Map<string, any[]>();
    for (const r of rows) {
      const k = col ? text(col, r[group]) || "–" : "–";
      map.set(k, [...(map.get(k) ?? []), r]);
    }
    return [...map.entries()].map(([key, rs]) => ({ key, rows: rs }));
  }, [rows, group, cols]);
  const sums = (rs: any[]) =>
    shown.map((c) => (c.type === "number" && !["number", "position"].includes(c.key) ? rs.reduce((s, r) => s + (Number(r[c.key]) || 0), 0) : null));

  const saveCell = async (row: any, col: Col, value: any) => {
    setEditing(null);
    if ((row[col.key] ?? null) === value) return;
    const url = EDIT_URL[source]?.(row);
    if (!url || !col.edit) return;
    setError(null);
    try {
      await api.patch(url, { [col.edit]: value });
      toast({ text: t("common.saved") });
      qc.invalidateQueries({ queryKey: ["tables"] });
    } catch (e) {
      setError(e);
    }
  };
  const exportUrl = (fmt: string) => `/api/tables/${source}/export?fmt=${fmt}&cols=${encodeURIComponent((visible ?? []).join(","))}`;
  const link = (row: any) => (source === "customers" ? `/betrieb/kunden/${row.id}` : row.order_id ? `/betrieb/auftraege/${row.order_id}` : null);
  const sources: { key: Source; label: string }[] = [
    { key: "plants", label: t("tables.sources.plants") },
    { key: "orders", label: t("tables.sources.orders") },
    ...(has("customers.read") ? [{ key: "customers" as Source, label: t("tables.sources.customers") }] : []),
    { key: "stops", label: t("tables.sources.stops") },
  ];

  return (
    <>
      <PageHeader
        title={t("nav.tables")}
        description={t("tables.description")}
        actions={
          <>
            <a className="btn ghost" href={exportUrl("xlsx")}>
              {t("tables.export_xlsx")}
            </a>
            <a className="btn ghost" href={exportUrl("csv")}>
              CSV
            </a>
          </>
        }
      />
      <div className="row between" style={{ flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
        <Segmented value={source} onChange={setSource} items={sources} label={t("tables.source")} />
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ width: 220 }} placeholder={t("common.search")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("common.search")} />
          <select
            className="input"
            style={{ width: 200 }}
            value={group}
            onChange={(e) => {
              setGroup(e.target.value);
              save(`kp.tables.${source}.group`, e.target.value);
            }}
            aria-label={t("tables.group_by")}
          >
            <option value="">{t("tables.no_group")}</option>
            {cols
              .filter((c) => ["text", "date", "status", "bool"].includes(c.type))
              .map((c) => (
                <option key={c.key} value={c.key}>
                  {t("tables.group_by")}: {c.label}
                </option>
              ))}
          </select>
          <button className={`btn ${showCols ? "" : "secondary"}`} onClick={() => setShowCols(!showCols)} aria-expanded={showCols}>
            {t("tables.columns", { n: shown.length })}
          </button>
        </div>
      </div>
      {showCols && (
        <div className="card tight" style={{ marginBottom: 12 }}>
          <div className="chip-list" role="group" aria-label={t("tables.choose_columns")}>
            {cols.map((c) => (
              <label key={c.key} className={`col-chip ${(visible ?? []).includes(c.key) ? "on" : ""}`}>
                <input type="checkbox" checked={(visible ?? []).includes(c.key)} onChange={() => toggle(c.key)} />
                {c.label}
              </label>
            ))}
          </div>
        </div>
      )}
      <ErrorBox error={error} />
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && rows.length === 0 && <Empty title={t("tables.empty")} />}
      {q.data && rows.length > 0 && (
        <div className="table-wrap sheet">
          <table className="table">
            <thead>
              <tr>
                {shown.map((c) => (
                  <th
                    key={c.key}
                    className={c.type === "number" ? "num" : undefined}
                    aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
                  >
                    {["image", "images"].includes(c.type) ? (
                      c.label
                    ) : (
                      <button className="th-sort" onClick={() => setSort(sort?.key === c.key ? { key: c.key, dir: sort.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 })}>
                        {c.label} {sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : ""}
                      </button>
                    )}
                  </th>
                ))}
                <th aria-label={t("common.open")} />
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <Fragment key={g.key}>
                  {group && (
                    <tr className="group-row">
                      <td colSpan={shown.length + 1}>
                        <strong>{g.key}</strong> <span className="muted small">({g.rows.length})</span>
                      </td>
                    </tr>
                  )}
                  {g.rows.map((r) => (
                    <tr key={r.id}>
                      {shown.map((c) => {
                        const editable = Boolean(c.edit && EDIT_URL[source]);
                        const isEditing = editing !== null && editing.id === r.id && editing.key === c.key;
                        return (
                          <td
                            key={c.key}
                            className={`${c.type === "number" ? "num" : ""} ${editable ? "editable" : ""}`}
                            onDoubleClick={() => editable && setEditing({ id: r.id, key: c.key })}
                            title={editable && !isEditing ? t("tables.edit_hint") : undefined}
                          >
                            {isEditing ? <EditCell col={c} row={r} onSave={(v) => void saveCell(r, c, v)} onCancel={() => setEditing(null)} /> : <Cell col={c} row={r} />}
                          </td>
                        );
                      })}
                      <td>{link(r) && <Link to={link(r)!}>{t("common.open")}</Link>}</td>
                    </tr>
                  ))}
                  {group && sums(g.rows).some((x) => x !== null) && (
                    <tr className="sum-row">
                      {sums(g.rows).map((s, i) => (
                        <td key={i} className="num small muted">
                          {s !== null ? fmtNumber(s, 1) : ""}
                        </td>
                      ))}
                      <td />
                    </tr>
                  )}
                </Fragment>
              ))}
              {sums(rows).some((x) => x !== null) && (
                <tr className="sum-row total">
                  {sums(rows).map((s, i) => (
                    <td key={i} className="num small">
                      {i === 0 ? `${t("tables.total")} (${rows.length})` : s !== null ? fmtNumber(s, 1) : ""}
                    </td>
                  ))}
                  <td />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
