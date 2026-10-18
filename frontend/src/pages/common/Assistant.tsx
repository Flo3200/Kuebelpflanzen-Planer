// Settings AI: chat that explains the app and changes settings; every change has an undo button.
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Card, PageHeader, useToast } from "../../components/ui";
import { t } from "../../i18n";

interface Change {
  key: string;
  label: string;
  old: unknown;
  new: unknown;
  scope: string;
  audit_id?: string;
  batch_id?: string;
  reset?: boolean;
  undone?: boolean;
}

interface Msg {
  role: "user" | "assistant";
  content: string;
  changes?: Change[];
}

const show = (v: unknown) => (typeof v === "object" ? JSON.stringify(v) : String(v));

export function AssistantPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // block body: newer browsers return a promise from scrollIntoView, which must not become the cleanup
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next: Msg[] = [...messages, { role: "user", content: text.trim() }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const r = await api.post<{ text: string; changes: Change[] }>("/api/assistant/chat", {
        messages: next.map(({ role, content }) => ({ role, content })),
      });
      setMessages([...next, { role: "assistant", content: r.text, changes: r.changes }]);
      if (r.changes.length) qc.invalidateQueries({ queryKey: ["settings"] });
    } catch (e) {
      setMessages([...next, { role: "assistant", content: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  };
  const undo = async (mi: number, ci: number) => {
    const c = messages[mi].changes![ci];
    try {
      await api.post(c.batch_id ? `/api/audit/batch/${c.batch_id}/undo` : `/api/audit/${c.audit_id}/undo`);
      setMessages(messages.map((m, i) => (i === mi ? { ...m, changes: m.changes!.map((x, j) => (j === ci ? { ...x, undone: true } : x)) } : m)));
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast({ text: t("assistant.undone") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const examples = [t("assistant.ex1"), t("assistant.ex2"), t("assistant.ex3")];
  return (
    <>
      <PageHeader title={t("assistant.title")} description={t("assistant.description")} />
      <Card>
        <div className="chat" aria-live="polite">
          {messages.length === 0 && (
            <div className="stack" style={{ gap: 8 }}>
              <p className="muted">{t("assistant.intro")}</p>
              <div className="row">
                {examples.map((e) => (
                  <button key={e} className="btn ghost small" onClick={() => send(e)}>
                    {e}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, mi) => (
            <div key={mi} className={`chat-msg ${m.role}`}>
              <div className="chat-bubble">{m.content}</div>
              {(m.changes ?? []).map((c, ci) => (
                <div key={ci} className="chat-change">
                  <span>
                    <strong>{c.label}</strong>: {show(c.old)} → {show(c.new)} <span className="xs muted">({t(`assistant.scopes.${c.scope}`)})</span>
                  </span>
                  {c.undone ? (
                    <span className="small muted">{t("assistant.undone")}</span>
                  ) : (
                    <button className="btn small ghost" onClick={() => undo(mi, ci)}>
                      {t("assistant.undo")}
                    </button>
                  )}
                </div>
              ))}
            </div>
          ))}
          {busy && <div className="chat-msg assistant"><div className="chat-bubble muted">{t("assistant.thinking")}</div></div>}
          <div ref={end} />
        </div>
        <form
          className="row"
          style={{ marginTop: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <input className="input" style={{ flex: 1 }} value={input} onChange={(e) => setInput(e.target.value)} placeholder={t("assistant.placeholder")} aria-label={t("assistant.placeholder")} />
          <button className="btn" disabled={busy || !input.trim()}>
            {t("assistant.send")}
          </button>
        </form>
        <p className="xs muted" style={{ marginTop: 8 }}>
          {t("assistant.note")}
        </p>
      </Card>
    </>
  );
}
