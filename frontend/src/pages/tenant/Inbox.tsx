import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Card, Confidence, Empty, ErrorBox, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtDate, t } from "../../i18n";
import { JobStatus, useJob } from "../common/Jobs";
import { PhotoThumb } from "./Photos";
import { useAuth } from "../../auth/auth";

const STATUS_TONE: Record<string, "green" | "amber" | "red" | "blue" | undefined> = {
  processing: "blue",
  review: "amber",
  confirmed: "green",
  rejected: undefined,
  failed: "red",
};

export function InboxPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("review,processing,failed");
  const list = useQuery({
    queryKey: ["drafts", filter],
    queryFn: () => api.get<any[]>("/api/drafts", { status: filter || undefined }),
    refetchInterval: (q) => ((q.state.data ?? []).some((d: any) => d.status === "processing") ? 2000 : false),
  });
  return (
    <>
      <PageHeader title={t("nav.inbox")} description={t("inbox.description")} />
      <Composer
        onCreated={(d) => {
          qc.invalidateQueries({ queryKey: ["drafts"] });
          navigate(`/betrieb/posteingang/${d.id}`);
        }}
      />
      <div className="row between" style={{ margin: "28px 0 12px" }}>
        <h3 style={{ margin: 0 }}>{t("inbox.drafts")}</h3>
        <select className="input" style={{ width: 220 }} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("common.status")}>
          <option value="review,processing,failed">{t("inbox.open")}</option>
          <option value="confirmed">{t("inbox.status.confirmed")}</option>
          <option value="rejected">{t("inbox.status.rejected")}</option>
          <option value="">{t("common.all")}</option>
        </select>
      </div>
      {list.isLoading && <Spinner />}
      {list.data && list.data.length === 0 && <Empty title={t("inbox.empty")} text={t("inbox.empty_text")} />}
      <div className="stack">
        {(list.data ?? []).map((d) => (
          <Link key={d.id} to={`/betrieb/posteingang/${d.id}`} className="card tight row between" style={{ textDecoration: "none", color: "inherit" }}>
            <div>
              <div>{d.summary}</div>
              <div className="xs muted">
                {fmtDate(d.created_at, true)} · {t(`inbox.source.${d.source_kind}`)} {d.model ? `· ${d.model}` : ""}
              </div>
            </div>
            <div className="row">
              {d.review_fields?.length > 0 && d.status === "review" && <span className="small muted">{t("inbox.to_check", { n: d.review_fields.length })}</span>}
              <Badge tone={STATUS_TONE[d.status]}>{t(`inbox.status.${d.status}`)}</Badge>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

function Composer({ onCreated }: { onCreated: (d: any) => void }) {
  const [text, setText] = useState("");
  const [source, setSource] = useState("email");
  const [files, setFiles] = useState<{ file: File; url: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => () => files.forEach((f) => URL.revokeObjectURL(f.url)), [files]);
  const addFiles = (list: File[]) => {
    const images = list.filter((f) => f.type.startsWith("image/"));
    if (images.length) setFiles((prev) => [...prev, ...images.map((file) => ({ file, url: URL.createObjectURL(file) }))]);
  };
  // text and photos are pasted together (e.g. a whole chat or e-mail); the AI sorts the photos itself
  const onPaste = (e: React.ClipboardEvent) => {
    const pasted = Array.from(e.clipboardData.files ?? []);
    if (pasted.length) {
      addFiles(pasted);
      if (!e.clipboardData.getData("text")) e.preventDefault();
    }
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("text", text);
      form.append("source_kind", source);
      files.forEach((f) => form.append("files", f.file));
      const d = await api.upload("/api/drafts", form);
      setText("");
      setFiles([]);
      onCreated(d);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title={t("inbox.new_message")}>
      <div
        className={`stack paste-zone ${drag ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          addFiles(Array.from(e.dataTransfer.files ?? []));
        }}
      >
        <div className="row">
          <select className="input" style={{ width: 200 }} value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("inbox.source_label")}>
            {["email", "text", "voice"].map((s) => (
              <option key={s} value={s}>
                {t(`inbox.source.${s}`)}
              </option>
            ))}
          </select>
          <span className="small muted">{t("inbox.paste_hint")}</span>
        </div>
        <textarea className="input" rows={7} value={text} onChange={(e) => setText(e.target.value)} onPaste={onPaste} placeholder={t("inbox.placeholder")} aria-label={t("inbox.new_message")} />
        {files.length > 0 && (
          <div className="paste-thumbs" aria-label={t("orders.photos")}>
            {files.map((f, i) => (
              <figure key={f.url}>
                <img src={f.url} alt={f.file.name} />
                <button className="btn small ghost" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={`${t("common.remove")}: ${f.file.name}`}>
                  ×
                </button>
              </figure>
            ))}
          </div>
        )}
        {files.length > 0 && <div className="xs muted">{t("inbox.auto_sort_hint", { n: files.length })}</div>}
        <ErrorBox error={error} />
        <div className="row between">
          <div>
            <input
              ref={input}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <button className="btn ghost" onClick={() => input.current?.click()}>
              {t("inbox.add_photos")}
            </button>
          </div>
          <button className="btn" disabled={busy || (!text.trim() && files.length === 0)} onClick={submit}>
            {busy ? t("common.loading") : t("inbox.analyse")}
          </button>
        </div>
      </div>
    </Card>
  );
}

// ----------------------------------------------------------------------------- review

type VF = { value: any; confidence: number };

const SECTIONS: { key: string; fields: [string, "text" | "number" | "bool" | "date"][] }[] = [
  { key: "customer", fields: [["name", "text"], ["company", "text"], ["email", "text"], ["phone", "text"]] },
  { key: "address", fields: [["street", "text"], ["postal_code", "text"], ["city", "text"], ["floor", "text"], ["parking_notes", "text"], ["access_notes", "text"]] },
  { key: "order", fields: [["earliest_date", "date"], ["latest_date", "date"], ["notes", "text"]] },
  { key: "path", fields: [["length_m", "number"], ["steps", "number"], ["height_m", "number"], ["min_width_cm", "number"], ["elevator", "bool"], ["surface", "text"], ["description", "text"]] },
];
const PLANT_FIELDS: [string, "text" | "number" | "bool"][] = [
  ["species", "text"], ["count", "number"], ["label", "text"], ["total_height_cm", "number"], ["pot_diameter_cm", "number"],
  ["pot_height_cm", "number"], ["crown_width_cm", "number"], ["weight_kg", "number"], ["frost_sensitive", "bool"], ["can_tilt", "bool"], ["notes", "text"],
];

function ValueField(props: { id: string; label: string; vf: VF | undefined; kind: string; review: boolean; threshold: number; onChange: (v: VF) => void }) {
  const vf = props.vf ?? { value: null, confidence: 0 };
  const low = vf.value !== null && vf.confidence < props.threshold;
  const style = props.review || low ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined;
  const set = (value: any) => props.onChange({ value, confidence: 1 });
  return (
    <div className="field">
      <label htmlFor={props.id} className="row between" style={{ gap: 6 }}>
        <span>{props.label}</span>
        <Confidence value={vf.value === null ? null : vf.confidence} />
      </label>
      {props.kind === "bool" ? (
        <select id={props.id} className="input" style={style} value={vf.value === null ? "" : String(vf.value)} onChange={(e) => set(e.target.value === "" ? null : e.target.value === "true")}>
          <option value="">–</option>
          <option value="true">{t("common.yes")}</option>
          <option value="false">{t("common.no")}</option>
        </select>
      ) : (
        <input
          id={props.id}
          className={`input ${props.kind === "number" ? "num" : ""}`}
          style={style}
          type={props.kind === "number" ? "number" : props.kind === "date" ? "date" : "text"}
          value={vf.value ?? ""}
          onChange={(e) => set(e.target.value === "" ? null : props.kind === "number" ? Number(e.target.value) : e.target.value)}
        />
      )}
    </div>
  );
}

export function DraftReviewPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["draft", id],
    queryFn: () => api.get<any>(`/api/drafts/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 1500 : false),
  });
  const job = useJob(q.data?.status === "processing" ? q.data.job_id : null);
  const threshold = useQuery({ queryKey: ["settings", "tenant", null, null], queryFn: () => api.get<any>("/api/settings") });
  const minConf = threshold.data?.values?.find((v: any) => v.key === "photos.min_confidence")?.value ?? 0.6;
  const [ex, setEx] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);
  const [storeContact, setStoreContact] = useState<boolean | null>(null);
  const { mod } = useAuth();
  useEffect(() => {
    if (q.data?.extracted && Object.keys(q.data.extracted).length) setEx(structuredClone(q.data.extracted));
  }, [q.data?.status, q.data?.extracted]);
  useEffect(() => {
    if (q.data && storeContact === null) setStoreContact(Boolean(q.data.store_contact_default));
  }, [q.data, storeContact]);

  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  const review = new Set<string>(d.review_fields ?? []);
  const editable = d.status === "review" || d.status === "failed";

  const setVF = (section: string, field: string, vf: VF) => setEx({ ...ex, [section]: { ...ex[section], [field]: vf } });
  const setPlant = (i: number, field: string, vf: VF) =>
    setEx({ ...ex, plants: ex.plants.map((p: any, j: number) => (j === i ? { ...p, [field]: vf } : p)) });
  const emptyPlant = () => Object.fromEntries([...PLANT_FIELDS.map(([f]) => [f, { value: null, confidence: 1 }]), ["location", { value: null, confidence: 0 }]]);

  const confirm = async () => {
    setError(null);
    try {
      const r = await api.post(`/api/drafts/${id}/confirm`, { extracted: ex, store_contact: Boolean(storeContact) });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      toast({ text: t("inbox.confirmed", { number: r.order_number }) });
      navigate(`/betrieb/auftraege/${r.order_id}`);
    } catch (e) {
      setError(e);
    }
  };
  const reject = async () => {
    await api.post(`/api/drafts/${id}/reject`);
    qc.invalidateQueries({ queryKey: ["drafts"] });
    navigate("/betrieb/posteingang");
  };
  const reprocess = async () => {
    await api.post(`/api/drafts/${id}/reprocess`);
    qc.invalidateQueries({ queryKey: ["draft", id] });
  };

  return (
    <>
      <PageHeader
        eyebrow={t("nav.inbox")}
        title={d.summary || t("inbox.draft")}
        description={`${fmtDate(d.created_at, true)} · ${t(`inbox.status.${d.status}`)}${d.model ? " · " + d.model : ""}`}
        actions={
          editable ? (
            <>
              <button className="btn ghost" onClick={reprocess}>
                {t("inbox.reprocess")}
              </button>
              <button className="btn ghost" onClick={reject}>
                {t("inbox.reject")}
              </button>
              <button className="btn" onClick={confirm} disabled={!ex}>
                {t("inbox.confirm")}
              </button>
            </>
          ) : d.order_id ? (
            <Link className="btn" to={`/betrieb/auftraege/${d.order_id}`}>
              {t("inbox.open_order")}
            </Link>
          ) : null
        }
      />
      {d.status === "processing" && (
        <Card>
          <Spinner label={t("inbox.processing")} />
          {job.data && <div style={{ marginTop: 12 }}><JobStatus job={job.data} /></div>}
        </Card>
      )}
      {d.status === "failed" && <div className="alert error">{t("inbox.failed")}: {t(d.error ?? "errors.generic")}</div>}
      <ErrorBox error={error} />
      {ex && (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)", alignItems: "start", marginTop: 16 }}>
          <div className="stack lg">
            {review.size > 0 && editable && <div className="alert warn">{t("inbox.review_hint", { n: review.size })}</div>}
            {SECTIONS.map((sec) => (
              <Card
                key={sec.key}
                title={t(`inbox.sections.${sec.key}`)}
                actions={
                  sec.key === "customer" && (
                    <label className="row small" style={{ gap: 6 }}>
                      <input type="checkbox" checked={Boolean(storeContact)} onChange={(e) => setStoreContact(e.target.checked)} disabled={!editable} />
                      {t("inbox.store_contact")}
                    </label>
                  )
                }
              >
                {sec.key === "customer" && !storeContact && <p className="xs muted" style={{ marginTop: 0 }}>{t("inbox.contact_not_stored")}</p>}
                <div className="form-grid">
                  {sec.fields.map(([f, kind]) => (
                    <ValueField
                      key={f}
                      id={`${sec.key}-${f}`}
                      label={t(`inbox.fields.${f}`)}
                      vf={ex[sec.key]?.[f]}
                      kind={kind}
                      threshold={minConf}
                      review={review.has(`${sec.key}.${f}`)}
                      onChange={(vf) => setVF(sec.key, f, vf)}
                    />
                  ))}
                </div>
              </Card>
            ))}
            <Card
              title={t("inbox.sections.plants")}
              actions={
                editable && (
                  <button className="btn small secondary" onClick={() => setEx({ ...ex, plants: [...(ex.plants ?? []), emptyPlant()] })}>
                    {t("common.add")}
                  </button>
                )
              }
            >
              {(ex.plants ?? []).length === 0 && <p className="muted">{t("inbox.no_plants")}</p>}
              <div className="stack lg">
                {(ex.plants ?? []).map((p: any, i: number) => (
                  <div key={i} className="stack" style={{ borderTop: i ? "1px solid var(--border)" : undefined, paddingTop: i ? 16 : 0 }}>
                    <div className="row between">
                      <strong>
                        {t("plants.plant")} {i + 1}
                      </strong>
                      {editable && (
                        <button className="btn small ghost" onClick={() => setEx({ ...ex, plants: ex.plants.filter((_: any, j: number) => j !== i) })}>
                          {t("common.remove")}
                        </button>
                      )}
                    </div>
                    <div className="form-grid">
                      {PLANT_FIELDS.map(([f, kind]) => (
                        <ValueField
                          key={f}
                          id={`plant-${i}-${f}`}
                          label={t(`inbox.fields.${f}`)}
                          vf={p[f]}
                          kind={kind}
                          threshold={minConf}
                          review={review.has(`plants[${i}].${f}`)}
                          onChange={(vf) => setPlant(i, f, vf)}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
          <div className="stack lg">
            <Card title={t("inbox.original")}>
              <pre className="small" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>
                {d.source_text}
              </pre>
            </Card>
            <CustomerRequest draft={d} share={mod("share")} onChange={() => qc.invalidateQueries({ queryKey: ["draft", id] })} />
            {(d.photos ?? []).length > 0 && (
              <Card title={t("orders.photos")}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
                  {d.photos.map((p: any) => (
                    <div key={p.id} className="stack" style={{ gap: 4 }}>
                      <PhotoThumb photo={p} />
                      {p.ai_results?.sorted && (
                        <span className="xs muted" title={p.ai_results.sorted.description ?? undefined}>
                          {p.ai_results.sorted.plant ? t("inbox.photo_plant", { n: p.ai_results.sorted.plant }) : t("inbox.photo_path")} · {t("inbox.sorted_by_ai")}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                {d.photo_check?.feedback?.length > 0 && (
                  <ul className="small" style={{ paddingLeft: 18, marginBottom: 0 }}>
                    {d.photo_check.feedback.map((f: string) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                )}
              </Card>
            )}
            {(ex.missing ?? []).length > 0 && (
              <Card title={t("inbox.missing")}>
                <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                  {ex.missing.map((m: string) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </Card>
            )}

          </div>
        </div>
      )}
    </>
  );
}

/** Message to the customer for the missing photos/details (written by the AI), with the customer link. */
function CustomerRequest({ draft, share, onChange }: { draft: any; share: boolean; onChange: () => void }) {
  const toast = useToast();
  const [link, setLink] = useState<string | null>(null);
  const n = draft.notification;
  const message: string | null = draft.follow_up ?? n?.message ?? null;
  if (!message && !share) return null;
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast({ text: t("common.copied") }));
  const makeLink = async () => {
    const r = await api.post<any>(`/api/drafts/${draft.id}/share-link`);
    setLink(r.url);
  };
  const done = async () => {
    await api.post(`/api/notifications/${n.id}/done`);
    toast({ text: t("inbox.request_done") });
    onChange();
  };
  const shareUrl = link ?? n?.data?.share_url ?? null;
  return (
    <Card
      title={t("inbox.follow_up")}
      actions={
        message && (
          <button className="btn small secondary" onClick={() => copy(message)}>
            {t("common.copy")}
          </button>
        )
      }
    >
      {message && (
        <pre className="small" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>
          {message}
        </pre>
      )}
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
        {share && !shareUrl && (
          <button className="btn small ghost" onClick={makeLink}>
            {t("inbox.make_share_link")}
          </button>
        )}
        {shareUrl && (
          <button className="btn small ghost" onClick={() => copy(shareUrl)} title={shareUrl}>
            {t("inbox.copy_share_link")}
          </button>
        )}
        {n && !n.done && (
          <button className="btn small ghost" onClick={done}>
            {t("inbox.mark_sent")}
          </button>
        )}
        {n?.done && <Badge tone="green">{t("inbox.sent")}</Badge>}
      </div>
    </Card>
  );
}
