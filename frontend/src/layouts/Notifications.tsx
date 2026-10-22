// Bell in the top bar: notifications of the office (missing photos with a ready message for the
// customer, uploads through the customer link, tours ended early, spontaneous teams).
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/ui";
import { fmtDate, t } from "../i18n";

type Item = { id: string; kind: string; title: string; body: string | null; message: string | null; link: string | null; read: boolean; created_at: string; updated_at: string };

export function NotificationBell() {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<{ items: Item[]; unread: number }>("/api/notifications"),
    refetchInterval: 30_000,
  });
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["notifications"] });
  const act = async (n: Item, what: "read" | "done") => {
    await api.post(`/api/notifications/${n.id}/${what}`);
    refresh();
  };
  const unread = q.data?.unread ?? 0;
  const items = q.data?.items ?? [];
  return (
    <div className="bell" ref={box}>
      <button className="btn icon ghost" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={t("notifications.title_n", { n: unread })} title={t("notifications.title")}>
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" />
          <path d="M10 20a2 2 0 0 0 4 0" />
        </svg>
        {unread > 0 && <span className="bell-count">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label={t("notifications.title")}>
          <div className="row between" style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)" }}>
            <strong>{t("notifications.title")}</strong>
            {unread > 0 && (
              <button className="btn link small" onClick={() => api.post("/api/notifications/read-all").then(refresh)}>
                {t("notifications.read_all")}
              </button>
            )}
          </div>
          {items.length === 0 && <p className="small muted" style={{ padding: 14, margin: 0 }}>{t("notifications.empty")}</p>}
          <ul className="bell-list">
            {items.map((n) => (
              <li key={n.id} className={n.read ? "" : "unread"}>
                <div className="small" style={{ fontWeight: n.read ? 400 : 600 }}>{n.title}</div>
                {n.body && <div className="xs muted">{n.body}</div>}
                {n.message && <pre className="bell-message xs">{n.message}</pre>}
                <div className="row xs" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                  <span className="faint">{fmtDate(n.updated_at, true)}</span>
                  {n.message && (
                    <button
                      className="btn small secondary"
                      onClick={() =>
                        navigator.clipboard.writeText(n.message ?? "").then(() => {
                          toast({ text: t("common.copied") });
                          void act(n, "read");
                        })
                      }
                    >
                      {t("notifications.copy_message")}
                    </button>
                  )}
                  {n.link && (
                    <Link className="btn small ghost" to={n.link} onClick={() => (setOpen(false), void act(n, "read"))}>
                      {t("common.open")}
                    </Link>
                  )}
                  <button className="btn small ghost" onClick={() => act(n, "done")}>
                    {t("notifications.done")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
