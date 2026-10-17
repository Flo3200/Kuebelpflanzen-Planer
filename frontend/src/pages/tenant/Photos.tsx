import { useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { Badge, ConfirmButton, Modal, useToast } from "../../components/ui";
import { t } from "../../i18n";

export const PHOTO_KINDS = ["plant_front", "plant_side", "plant_top", "pot", "path_start", "path_segment", "path_end", "pickup_proof", "damage", "other"];

export function PhotoThumb({ photo, onClick }: { photo: any; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", padding: 0, background: "var(--surface-2)", cursor: "pointer", textAlign: "left" }}
    >
      <img src={photo.url} alt={t(`photo_kinds.${photo.kind}`)} loading="lazy" style={{ width: "100%", height: 140, objectFit: "cover", display: "block" }} />
      <div style={{ padding: "6px 8px" }} className="stack">
        <span className="xs">{t(`photo_kinds.${photo.kind}`)}</span>
        <span className="chip-list">
          {photo.quality?.sharp === false && <Badge tone="red">{t("photos.blurry")}</Badge>}
          {photo.quality?.exposure_ok === false && <Badge tone="amber">{t("photos.exposure")}</Badge>}
          {photo.a4_detected && <Badge tone="green">A4</Badge>}
        </span>
      </div>
    </button>
  );
}

export function PhotoGallery(props: { photos: any[]; orderId: string; plants: any[]; paths: any[]; onChange: () => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState("plant_front");
  const [plantId, setPlantId] = useState<string>("");
  const [open, setOpen] = useState<any | null>(null);
  const [askConsent, setAskConsent] = useState<File[] | null>(null);

  const upload = async (files: File[], consent = false) => {
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      form.append("order_id", props.orderId);
      if (plantId) form.append("plant_id", plantId);
      if (kind.startsWith("path") && props.paths[0]) form.append("path_id", props.paths[0].id);
      if (consent) form.append("consent_confirmed", "true");
      try {
        await api.upload("/api/photos", form);
      } catch (e) {
        if (e instanceof ApiError && e.code === "errors.consent_missing") {
          setAskConsent(files);
          return;
        }
        toast({ text: (e as Error).message, tone: "error" });
        return;
      }
    }
    props.onChange();
    toast({ text: t("photos.uploaded", { n: files.length }) });
  };

  return (
    <div className="stack lg">
      <div className="card tight">
        <div className="row">
          <select className="input" style={{ width: 240 }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("photos.kind")}>
            {PHOTO_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`photo_kinds.${k}`)}
              </option>
            ))}
          </select>
          {!kind.startsWith("path") && props.plants.length > 0 && (
            <select className="input" style={{ width: 220 }} value={plantId} onChange={(e) => setPlantId(e.target.value)} aria-label={t("plants.plant")}>
              <option value="">{t("photos.no_plant")}</option>
              {props.plants.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.number} {p.species_name ?? ""}
                </option>
              ))}
            </select>
          )}
          <input
            ref={input}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (files.length) upload(files);
            }}
          />
          <button className="btn" onClick={() => input.current?.click()}>
            {t("photos.upload")}
          </button>
          <span className="small muted">{t("photos.upload_hint")}</span>
        </div>
      </div>
      {props.photos.length === 0 && <p className="muted">{t("photos.none")}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 12 }}>
        {props.photos.map((p) => (
          <PhotoThumb key={p.id} photo={p} onClick={() => setOpen(p)} />
        ))}
      </div>
      {open && (
        <Modal title={t(`photo_kinds.${open.kind}`)} onClose={() => setOpen(null)} wide>
          <img src={open.url} alt={t(`photo_kinds.${open.kind}`)} style={{ width: "100%", maxHeight: "65vh", objectFit: "contain", borderRadius: 12, background: "var(--surface-2)" }} />
          <div className="row between" style={{ marginTop: 12 }}>
            <span className="small muted">
              {open.width}×{open.height} px
              {open.a4_detected && ` · ${t("photos.a4_scale", { s: open.a4?.cm_per_px })}`}
              {open.ai_results?.analysis?.notes && ` · ${open.ai_results.analysis.notes}`}
            </span>
            <ConfirmButton
              onConfirm={async () => {
                await api.del(`/api/photos/${open.id}`);
                setOpen(null);
                props.onChange();
              }}
            >
              {t("common.delete")}
            </ConfirmButton>
          </div>
        </Modal>
      )}
      {askConsent && (
        <Modal
          title={t("photos.consent_title")}
          onClose={() => setAskConsent(null)}
          footer={
            <>
              <button className="btn ghost" onClick={() => setAskConsent(null)}>
                {t("common.cancel")}
              </button>
              <button
                className="btn"
                onClick={() => {
                  const files = askConsent;
                  setAskConsent(null);
                  upload(files, true);
                }}
              >
                {t("photos.consent_confirm")}
              </button>
            </>
          }
        >
          <p>{t("photos.consent_text")}</p>
        </Modal>
      )}
    </div>
  );
}
