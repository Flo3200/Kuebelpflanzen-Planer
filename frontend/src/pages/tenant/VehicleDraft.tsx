// Vehicle by chat or by cargo-space photo (package C): the AI builds a draft with a confidence for
// every value and asks for gaps; the owner answers, corrects and confirms. Nothing changes before that.
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useEntityMeta } from "../../components/EntityForm";
import { Badge, Confidence, ErrorBox, Modal, Spinner, useToast } from "../../components/ui";
import { fmtDate, t } from "../../i18n";

type VF = { value: any; confidence: number };
type Draft = {
  id: string;
  status: string;
  source: string;
  vehicle_id: string | null;
  data: { vehicle: Record<string, VF>; costs: Record<string, VF>; shelves: Record<string, any>[] };
  messages: { role: string; text: string; at: string }[];
  questions: string[];
  review_fields: string[];
  photos: string[];
  model: string | null;
  created_at: string;
};

const GROUPS: { key: string; fields: string[] }[] = [
  { key: "general", fields: ["name", "kind", "plate", "required_licence", "seats"] },
  { key: "cargo", fields: ["cargo_length_cm", "cargo_width_cm", "cargo_height_cm", "payload_kg", "loading_edge_cm"] },
  { key: "door", fields: ["door_width_cm", "door_height_cm", "door_position"] },
  { key: "arches", fields: ["wheel_arch_x_cm", "wheel_arch_length_cm", "wheel_arch_width_cm", "wheel_arch_height_cm"] },
  { key: "axles", fields: ["front_axle_x_cm", "rear_axle_x_cm", "max_front_axle_extra_kg", "max_rear_axle_extra_kg"] },
  { key: "trailer", fields: ["can_tow", "max_trailer_kg", "max_tongue_load_kg"] },
];
const COSTS = ["cost_per_km", "cost_per_hour", "fuel_l_per_100km"];
const SHELF = ["name", "x_cm", "y_cm", "length_cm", "depth_cm", "height_cm", "clearance_cm", "max_load_kg"];
const TEXT_FIELDS = new Set(["name", "kind", "plate", "required_licence", "door_position"]);

/** Start dialog: chat (optionally for an existing vehicle) or cargo-space photos. */
export function VehicleDraftDialog(props: { mode: "chat" | "photo"; vehicleId?: string; draftId?: string; onClose: () => void; onConfirmed?: (vehicleId: string) => void }) {
  const [draftId, setDraftId] = useState<string | null>(props.draftId ?? null);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const qc = useQueryClient();
  const draft = useQuery({ queryKey: ["vehicle-draft", draftId], queryFn: () => api.get<Draft>(`/api/vehicle-drafts/${draftId}`), enabled: !!draftId });

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      let d: Draft;
      if (!draftId && props.mode === "photo") {
        const form = new FormData();
        files.forEach((f) => form.append("files", f));
        if (text) form.append("note", text);
        if (props.vehicleId) form.append("vehicle_id", props.vehicleId);
        d = await api.upload<Draft>("/api/vehicle-drafts/photo", form);
      } else {
        d = await api.post<Draft>("/api/vehicle-drafts/chat", { message: text, draft_id: draftId, vehicle_id: draftId ? undefined : props.vehicleId });
      }
      setText("");
      setFiles([]);
      setDraftId(d.id);
      qc.setQueryData(["vehicle-draft", d.id], d);
      qc.invalidateQueries({ queryKey: ["vehicle-drafts"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const title = props.vehicleId ? t("vehicledraft.title_change") : props.mode === "photo" ? t("vehicledraft.title_photo") : t("vehicledraft.title_chat");
  const d = draft.data;
  return (
    <Modal title={title} onClose={props.onClose} wide>
      <div className="stack lg">
        {!draftId && <p className="muted small">{props.mode === "photo" ? t("vehicledraft.photo_help") : props.vehicleId ? t("vehicledraft.change_help") : t("vehicledraft.chat_help")}</p>}
        {draftId && draft.isLoading && <Spinner />}
        {d && <Conversation draft={d} />}
        {(!d || d.status === "open") && (
          <div className="stack">
            {!draftId && props.mode === "photo" && (
              <input type="file" accept="image/*" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} aria-label={t("vehicledraft.photos")} />
            )}
            <textarea
              className="input"
              rows={3}
              value={text}
              placeholder={!draftId && props.mode === "photo" ? t("vehicledraft.note_placeholder") : draftId ? t("vehicledraft.answer_placeholder") : t("vehicledraft.chat_placeholder")}
              onChange={(e) => setText(e.target.value)}
              aria-label={t("vehicledraft.message")}
            />
            <ErrorBox error={error} />
            <div className="row end">
              <button className="btn" disabled={busy || (!draftId && props.mode === "photo" ? !files.length : !text.trim())} onClick={send}>
                {busy ? t("vehicledraft.thinking") : !draftId && props.mode === "photo" ? t("vehicledraft.analyse") : t("vehicledraft.send")}
              </button>
            </div>
          </div>
        )}
        {d && <DraftEditor draft={d} onClose={props.onClose} onConfirmed={props.onConfirmed} />}
      </div>
    </Modal>
  );
}

function Conversation({ draft }: { draft: Draft }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {draft.photos.length > 0 && (
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {draft.photos.map((url) => (
            <img key={url} src={url} alt={t("vehicledraft.photos")} style={{ height: 90, borderRadius: 8, border: "1px solid var(--border)" }} />
          ))}
        </div>
      )}
      {draft.messages.map((m, i) => (
        <div key={i} className={`card tight`} style={{ background: m.role === "user" ? "var(--surface-2)" : "var(--surface)", marginLeft: m.role === "user" ? 48 : 0, marginRight: m.role === "user" ? 0 : 48 }}>
          <div className="xs muted">{m.role === "user" ? t("vehicledraft.you") : t("vehicledraft.ai")} · {fmtDate(m.at, true)}</div>
          <div className="small" style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
        </div>
      ))}
      {draft.questions.length > 0 && draft.status === "open" && (
        <div className="alert warn">
          <strong>{t("vehicledraft.questions")}</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {draft.questions.map((q) => (
              <li key={q} className="small">
                {q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DraftEditor({ draft, onClose, onConfirmed }: { draft: Draft; onClose: () => void; onConfirmed?: (vehicleId: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const meta = useEntityMeta("vehicle");
  const byName = useMemo(() => new Map((meta.data?.fields ?? []).map((f) => [f.name, f])), [meta.data]);
  const [edits, setEdits] = useState<{ vehicle: Record<string, any>; costs: Record<string, any> }>({ vehicle: {}, costs: {} });
  const [shelves, setShelves] = useState<Record<string, any>[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const review = new Set(draft.review_fields);
  const open = draft.status === "open";
  const dirty = Object.keys(edits.vehicle).length + Object.keys(edits.costs).length > 0 || shelves !== null;

  const save = async () => {
    const data: any = {
      vehicle: Object.fromEntries(Object.entries(edits.vehicle).map(([k, v]) => [k, { value: v }])),
      costs: Object.fromEntries(Object.entries(edits.costs).map(([k, v]) => [k, { value: v }])),
    };
    if (shelves) data.shelves = shelves;
    const d = await api.patch<Draft>(`/api/vehicle-drafts/${draft.id}`, { data });
    qc.setQueryData(["vehicle-draft", draft.id], d);
    setEdits({ vehicle: {}, costs: {} });
    setShelves(null);
  };
  const confirm = async () => {
    setError(null);
    try {
      if (dirty) await save();
      const r = await api.post<any>(`/api/vehicle-drafts/${draft.id}/confirm`);
      qc.invalidateQueries({ queryKey: ["/api/vehicles"] });
      qc.invalidateQueries({ queryKey: ["vehicle-drafts"] });
      qc.invalidateQueries({ queryKey: ["fk", "vehicle"] });
      toast({ text: t("vehicledraft.confirmed", { name: r.name }) });
      onConfirmed?.(r.vehicle_id);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  const discard = async () => {
    await api.post(`/api/vehicle-drafts/${draft.id}/discard`);
    qc.invalidateQueries({ queryKey: ["vehicle-drafts"] });
    onClose();
  };

  const cell = (section: "vehicle" | "costs", key: string) => {
    const vf: VF = draft.data[section]?.[key] ?? { value: null, confidence: 0 };
    const f = section === "vehicle" ? byName.get(key) : undefined;
    const label = f?.label ?? t(`vehicledraft.fields.${key}`);
    const unit = f?.unit ?? (section === "costs" ? t(`vehicledraft.units.${key}`) : null);
    const edited = key in edits[section];
    const value = edited ? edits[section][key] : vf.value;
    const flagged = review.has(`${section}.${key}`) && !edited;
    const id = `vd-${section}-${key}`;
    const set = (v: any) => setEdits((s) => ({ ...s, [section]: { ...s[section], [key]: v } }));
    return (
      <div className="field" key={key}>
        <label htmlFor={id} className="row between" style={{ gap: 6 }}>
          <span>{label}</span>
          <Confidence value={edited ? 1 : vf.value === null ? null : vf.confidence} />
        </label>
        {f?.type === "bool" || key === "can_tow" ? (
          <select id={id} className="input" disabled={!open} value={value === null || value === undefined ? "" : String(value)} onChange={(e) => set(e.target.value === "" ? null : e.target.value === "true")}>
            <option value="">–</option>
            <option value="true">{t("common.yes")}</option>
            <option value="false">{t("common.no")}</option>
          </select>
        ) : f?.enum ? (
          <select id={id} className="input" disabled={!open} value={value ?? ""} onChange={(e) => set(e.target.value || null)} style={flagged ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined}>
            <option value="">–</option>
            {f.enum.map((o) => (
              <option key={o} value={o}>
                {f.enum_labels[o] ?? o}
              </option>
            ))}
          </select>
        ) : (
          <div className="input-unit">
            <input
              id={id}
              className={`input ${TEXT_FIELDS.has(key) ? "" : "num"}`}
              disabled={!open}
              type={TEXT_FIELDS.has(key) ? "text" : "number"}
              step="any"
              value={value ?? ""}
              style={flagged ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined}
              onChange={(e) => set(e.target.value === "" ? null : TEXT_FIELDS.has(key) ? e.target.value : Number(e.target.value))}
            />
            {unit && <span className="unit">{unit}</span>}
          </div>
        )}
      </div>
    );
  };

  const shelfRows = shelves ?? draft.data.shelves.map((s) => Object.fromEntries([...(s.module_id ? [["module_id", s.module_id]] : []), ...SHELF.map((k) => [k, s[k]?.value ?? null])]));
  return (
    <div className="stack lg">
      <div className="row between">
        <span className="small muted">
          {t(`vehicledraft.status.${draft.status}`)} · {draft.model ?? ""} {review.size > 0 && open && <Badge tone="amber">{t("vehicledraft.to_check", { n: review.size })}</Badge>}
        </span>
      </div>
      {GROUPS.map((g) => (
        <div className="form-section" key={g.key}>
          <h4>{t(`vehicledraft.groups.${g.key}`)}</h4>
          <div className="form-grid">{g.fields.map((k) => cell("vehicle", k))}</div>
        </div>
      ))}
      <div className="form-section">
        <h4>{t("vehicledraft.groups.costs")}</h4>
        <div className="form-grid">{COSTS.map((k) => cell("costs", k))}</div>
      </div>
      <div className="form-section">
        <h4>{t("vehicledraft.groups.shelves")}</h4>
        {shelfRows.length === 0 && <p className="muted small">{t("vehicledraft.no_shelves")}</p>}
        {shelfRows.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  {SHELF.map((k) => (
                    <th key={k}>{t(`vehicledraft.fields.${k}`)}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {shelfRows.map((s, i) => (
                  <tr key={i}>
                    {SHELF.map((k) => (
                      <td key={k}>
                        <input
                          className="input num"
                          disabled={!open}
                          style={{ minWidth: k === "name" ? 120 : 64 }}
                          type={k === "name" ? "text" : "number"}
                          value={s[k] ?? ""}
                          aria-label={t(`vehicledraft.fields.${k}`)}
                          onChange={(e) => setShelves(shelfRows.map((x, j) => (j === i ? { ...x, [k]: k === "name" ? e.target.value : e.target.value === "" ? null : Number(e.target.value) } : x)))}
                        />
                      </td>
                    ))}
                    <td>
                      {open && (
                        <button className="btn small ghost" onClick={() => setShelves(shelfRows.filter((_, j) => j !== i))}>
                          {t("common.remove")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {open && (
          <div style={{ marginTop: 8 }}>
            <button className="btn small secondary" onClick={() => setShelves([...shelfRows, { name: t("resources.shelf"), x_cm: 0, y_cm: 0, length_cm: 120, depth_cm: 40, height_cm: 90, clearance_cm: 60, max_load_kg: 60 }])}>
              {t("resources.add_shelf")}
            </button>
          </div>
        )}
      </div>
      <ErrorBox error={error} />
      {open && (
        <div className="row end">
          <button className="btn ghost" onClick={discard}>
            {t("vehicledraft.discard")}
          </button>
          {dirty && (
            <button className="btn secondary" onClick={save}>
              {t("vehicledraft.save_corrections")}
            </button>
          )}
          <button className="btn" onClick={confirm}>
            {draft.vehicle_id ? t("vehicledraft.confirm_change") : t("vehicledraft.confirm_new")}
          </button>
        </div>
      )}
    </div>
  );
}

/** Open drafts on the vehicles page. */
export function OpenVehicleDrafts({ onOpen }: { onOpen: (d: Draft) => void }) {
  const q = useQuery({ queryKey: ["vehicle-drafts"], queryFn: () => api.get<Draft[]>("/api/vehicle-drafts") });
  if (!(q.data ?? []).length) return null;
  return (
    <div className="alert" style={{ marginBottom: 16 }}>
      <strong>{t("vehicledraft.open_drafts")}</strong>
      <div className="stack" style={{ gap: 4, marginTop: 6 }}>
        {(q.data ?? []).map((d) => (
          <div key={d.id} className="row between small">
            <span>
              {d.data.vehicle?.name?.value ?? t("vehicledraft.unnamed")} · {t(`vehicledraft.source.${d.source}`)} · {fmtDate(d.created_at, true)}
            </span>
            <button className="btn small secondary" onClick={() => onOpen(d)}>
              {t("vehicledraft.continue")}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
