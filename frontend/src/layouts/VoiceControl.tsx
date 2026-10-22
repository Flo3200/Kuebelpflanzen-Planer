// Voice control (round 2): press the microphone, speak, the AI operates the app (open pages, search,
// new drafts, day teams, tours, planning, settings). Speech to text through the AI model when one is set
// (recording is sent once and not stored), otherwise the browser's speech recognition. The answer is
// read out; typing a command works as well.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { t } from "../i18n";

type Reply = { heard: string; text: string; actions: { type: string; to?: string }[]; changes: any[]; model: string };
type State = "idle" | "listening" | "thinking";

const Recognition: any = typeof window !== "undefined" ? (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition : undefined;

function speak(text: string) {
  try {
    if (!("speechSynthesis" in window) || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "de-DE";
    window.speechSynthesis.speak(u);
  } catch {
    /* reading out is optional */
  }
}

export function VoiceControl() {
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["voice-config"], queryFn: () => api.get<{ enabled: boolean; transcription: "ai" | "browser" }>("/api/voice/config"), staleTime: 300_000, retry: false });
  const [state, setState] = useState<State>("idle");
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [interim, setInterim] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const history = useRef<{ role: string; content: string }[]>([]);
  const recorder = useRef<MediaRecorder | null>(null);
  const recognition = useRef<any>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node) && state === "idle") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, state]);

  if (!cfg.data?.enabled) return null;
  const useAi = cfg.data.transcription === "ai" && typeof MediaRecorder !== "undefined";
  const canListen = useAi || Boolean(Recognition);

  const send = async (text: string) => {
    if (!text.trim()) {
      setState("idle");
      return;
    }
    setState("thinking");
    setError(null);
    try {
      const r = await api.post<Reply>("/api/voice/command", { text, page: location.pathname, history: history.current.slice(-6) });
      setReply(r);
      history.current.push({ role: "user", content: text }, { role: "assistant", content: r.text });
      for (const a of r.actions) if (a.type === "navigate" && a.to) navigate(a.to);
      if (r.changes.length) qc.invalidateQueries();
      speak(r.text);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setState("idle");
      setInterim("");
    }
  };

  const startAi = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop());
      setState("thinking");
      try {
        const form = new FormData();
        form.append("audio", new Blob(chunks, { type: rec.mimeType || "audio/webm" }), "sprache.webm");
        const r = await api.upload<{ text: string }>("/api/voice/transcribe", form);
        setInterim(r.text);
        await send(r.text);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setState("idle");
      }
    };
    recorder.current = rec;
    rec.start();
    setState("listening");
    window.setTimeout(() => rec.state === "recording" && rec.stop(), 30_000);
  };

  const startBrowser = () => {
    const rec = new Recognition();
    rec.lang = "de-DE";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    let final = "";
    rec.onresult = (e: any) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      final = text;
      setInterim(text);
    };
    rec.onerror = (e: any) => {
      setError(e.error === "not-allowed" ? t("voice.mic_denied") : t("voice.not_heard"));
      setState("idle");
    };
    rec.onend = () => {
      recognition.current = null;
      if (final) void send(final);
      else setState("idle");
    };
    recognition.current = rec;
    rec.start();
    setState("listening");
  };

  const toggle = async () => {
    setOpen(true);
    setError(null);
    if (state === "listening") {
      if (recorder.current?.state === "recording") recorder.current.stop();
      recognition.current?.stop();
      return;
    }
    if (state !== "idle") return;
    setReply(null);
    setInterim("");
    try {
      if (useAi) await startAi();
      else if (Recognition) startBrowser();
    } catch {
      setError(t("voice.mic_denied"));
      setState("idle");
    }
  };

  return (
    <div className="voice" ref={box}>
      <button
        className={`btn icon ${state === "listening" ? "voice-on" : "ghost"}`}
        onClick={() => (canListen ? void toggle() : setOpen(!open))}
        aria-pressed={state === "listening"}
        aria-label={state === "listening" ? t("voice.stop") : t("voice.start")}
        title={state === "listening" ? t("voice.stop") : t("voice.start")}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
        </svg>
      </button>
      {open && (
        <div className="voice-panel" role="dialog" aria-label={t("voice.title")}>
          <div className="row between">
            <strong>{t("voice.title")}</strong>
            <button className="btn link small" onClick={() => setOpen(false)}>
              {t("common.close")}
            </button>
          </div>
          <p className="xs muted" style={{ margin: "4px 0 8px" }}>
            {state === "listening" ? t("voice.listening") : state === "thinking" ? t("voice.thinking") : canListen ? t("voice.hint") : t("voice.no_mic")}
          </p>
          {interim && <p className="small" style={{ fontStyle: "italic" }}>„{interim}“</p>}
          {reply && (
            <div className="voice-reply">
              {!interim && <p className="xs muted" style={{ margin: 0 }}>„{reply.heard}“</p>}
              <p className="small" style={{ margin: "4px 0 0" }}>{reply.text}</p>
            </div>
          )}
          {error && <div className="alert error small">{error}</div>}
          <form
            className="row"
            style={{ gap: 6, marginTop: 8 }}
            onSubmit={(e) => {
              e.preventDefault();
              const v = typed;
              setTyped("");
              setInterim(v);
              void send(v);
            }}
          >
            <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t("voice.type_placeholder")} aria-label={t("voice.type_placeholder")} />
            <button className="btn small" disabled={!typed.trim() || state !== "idle"}>
              {t("voice.send")}
            </button>
          </form>
          <details className="xs muted" style={{ marginTop: 8 }}>
            <summary>{t("voice.examples_title")}</summary>
            <ul style={{ paddingLeft: 16, margin: "4px 0 0" }}>
              {["ex1", "ex2", "ex3", "ex4", "ex5"].map((k) => (
                <li key={k}>{t(`voice.${k}`)}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </div>
  );
}
