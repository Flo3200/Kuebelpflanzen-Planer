// Customer link (/teilen/<token>, module "share"): the customer uploads photos and shares the location
// without an account. Photos go straight into the nursery's draft; the AI evaluates them again.
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Botanical } from "../components/Botanical";
import { Spinner } from "../components/ui";
import { t } from "../i18n";
import "../portal/portal.css";

type View = { tenant: string; needed: string[]; uploads: number; consent_given: boolean; consent_text: string; location: { lat: number; lon: number } | null };

export default function SharePage() {
  const { token } = useParams();
  const base = `/api/share/${token}`;
  const q = useQuery({ queryKey: ["share", token], queryFn: () => api.get<View>(base), retry: false });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    document.title = t("share.title");
  }, []);
  if (q.isLoading) return <div className="portal portal-center"><Spinner /></div>;
  if (q.error || !q.data)
    return (
      <div className="portal portal-center">
        <div className="portal-card">
          <h1>{t("share.title")}</h1>
          <p>{q.error instanceof ApiError ? q.error.message : t("share.invalid")}</p>
        </div>
      </div>
    );
  const v = q.data;
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      await q.refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const upload = (files: File[]) =>
    run(async () => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      await api.upload(`${base}/photos`, form);
    }, t("share.uploaded", { n: files.length }));
  const locate = () =>
    run(
      () =>
        new Promise<void>((resolve, reject) => {
          if (!navigator.geolocation) return reject(new Error(t("share.no_geolocation")));
          navigator.geolocation.getCurrentPosition(
            (pos) =>
              api
                .put(`${base}/location`, { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy_m: pos.coords.accuracy, note: note || null })
                .then(() => resolve(), reject),
            () => reject(new Error(t("share.location_denied"))),
            { enableHighAccuracy: true, timeout: 15000 },
          );
        }),
      t("share.location_saved"),
    );
  return (
    <div className="portal">
      <header className="portal-header">
        <div className="portal-brand">{v.tenant}</div>
      </header>
      <main className="portal-main portal-stack">
        <section className="portal-card portal-hero">
          <Botanical variant="olive" />
          <h1>{t("share.title")}</h1>
          <p>{t("share.intro", { tenant: v.tenant })}</p>
        </section>
        {v.needed.length > 0 && (
          <section className="portal-card">
            <h2>{t("share.needed")}</h2>
            <ul>
              {v.needed.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <p className="small muted">{t("share.how")}</p>
          </section>
        )}
        {!v.consent_given ? (
          <section className="portal-card portal-consent">
            <h2>{t("share.consent_title")}</h2>
            <p>{v.consent_text}</p>
            <button className="btn" disabled={busy} onClick={() => run(() => api.post(`${base}/consent`, { accept: true }), t("share.thanks"))}>
              {t("share.accept")}
            </button>
          </section>
        ) : (
          <>
            <section className="portal-card">
              <h2>{t("share.photos")}</h2>
              <p className="small">{v.uploads > 0 ? t("share.uploads_so_far", { n: v.uploads }) : t("share.photos_hint")}</p>
              <input
                ref={input}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  if (files.length) void upload(files);
                }}
              />
              <button className="btn" disabled={busy} onClick={() => input.current?.click()}>
                {busy ? t("common.loading") : t("share.choose_photos")}
              </button>
            </section>
            <section className="portal-card">
              <h2>{t("share.location")}</h2>
              <p className="small">{v.location ? t("share.location_done") : t("share.location_hint")}</p>
              <div className="field">
                <label htmlFor="share-note">{t("share.note")}</label>
                <input id="share-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("share.note_placeholder")} />
              </div>
              <button className="btn secondary" disabled={busy} onClick={locate}>
                {t("share.share_location")}
              </button>
            </section>
          </>
        )}
        {msg && <div className="alert ok" role="status">{msg}</div>}
        {error && <div className="alert error" role="alert">{error}</div>}
      </main>
      <footer className="portal-footer small muted">{t("share.footer")}</footer>
    </div>
  );
}
