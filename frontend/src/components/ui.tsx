import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type InputHTMLAttributes,
} from "react";
import { t } from "../i18n";
import { Botanical } from "./Botanical";

export function PageHeader(props: { title: string; eyebrow?: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        {props.eyebrow && <div className="eyebrow">{props.eyebrow}</div>}
        <h1>{props.title}</h1>
        {props.description && <p>{props.description}</p>}
      </div>
      {props.actions && <div className="row">{props.actions}</div>}
    </header>
  );
}

export function Card(props: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <div className="card-head">
          {props.title && <h3>{props.title}</h3>}
          {props.actions && <div className="row">{props.actions}</div>}
        </div>
      )}
      {props.children}
    </section>
  );
}

export function Kpi(props: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card tight kpi">
      <span className="kpi-label">{props.label}</span>
      <span className="kpi-value">{props.value}</span>
      {props.sub && <span className="kpi-sub">{props.sub}</span>}
    </div>
  );
}

export function Badge(props: { tone?: "green" | "terra" | "red" | "amber" | "blue"; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${props.tone ?? ""}`} title={props.title}>
      {props.children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" role="status">
      <span className="spinner" aria-hidden="true" />
      <span className="muted small">{label ?? t("common.loading")}</span>
    </span>
  );
}

export function Empty(props: { title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <Botanical variant="fern" style={{ right: -30, top: -20, width: 260 }} />
      <Botanical variant="leaf" style={{ left: -20, bottom: -30, width: 200 }} />
      <h3>{props.title}</h3>
      {props.text && <p>{props.text}</p>}
      {props.action}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="alert error" role="alert">
      {message}
    </div>
  );
}

export function Field(props: {
  label: ReactNode;
  help?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={props.htmlFor}>{props.label}</label>
      {props.children}
      {props.error ? <span className="error-text">{props.error}</span> : props.help ? <span className="help">{props.help}</span> : null}
    </div>
  );
}

export function UnitInput(props: InputHTMLAttributes<HTMLInputElement> & { unit?: string | null }) {
  const { unit, className, ...rest } = props;
  if (!unit) return <input className={`input ${className ?? ""}`} {...rest} />;
  return (
    <div className="input-unit">
      <input className={`input ${className ?? ""}`} {...rest} />
      <span className="unit">{unit}</span>
    </div>
  );
}

export function Modal(props: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && props.onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className={`modal ${props.wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={props.title} ref={ref}>
        <div className="modal-head">
          <h3>{props.title}</h3>
          <button className="btn icon ghost" onClick={props.onClose} aria-label={t("common.close")}>
            ✕
          </button>
        </div>
        {props.children}
        {props.footer && <div className="modal-foot">{props.footer}</div>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>(props: { value: T; onChange: (v: T) => void; items: { key: T; label: ReactNode }[] }) {
  return (
    <div className="tabs" role="tablist">
      {props.items.map((it) => (
        <button
          key={it.key}
          role="tab"
          aria-selected={props.value === it.key}
          className={props.value === it.key ? "active" : ""}
          onClick={() => props.onChange(it.key)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>(props: { value: T; onChange: (v: T) => void; items: { key: T; label: ReactNode }[]; label?: string }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={props.label}>
      {props.items.map((it) => (
        <button
          key={it.key}
          role="radio"
          aria-checked={props.value === it.key}
          className={props.value === it.key ? "active" : ""}
          onClick={() => props.onChange(it.key)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Confidence({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const color = value >= 0.75 ? "var(--success)" : value >= 0.5 ? "var(--warning)" : "var(--danger)";
  return (
    <span className="row" style={{ gap: 6 }} title={t("common.confidence")}>
      <span className="confidence">
        <span style={{ width: `${Math.round(value * 100)}%`, background: color }} />
      </span>
      <span className="xs muted num">{Math.round(value * 100)} %</span>
    </span>
  );
}

// ---------------------------------------------------------------- toasts

type Toast = { id: number; text: string; tone?: "error"; action?: { label: string; run: () => void } };
const ToastContext = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((ts) => [...ts, { ...toast, id }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), toast.action ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((x) => (
          <div key={x.id} className={`toast ${x.tone ?? ""}`}>
            <span>{x.text}</span>
            {x.action && (
              <button className="btn link" onClick={x.action.run}>
                {x.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

export function ConfirmButton(props: {
  onConfirm: () => void;
  children: ReactNode;
  question?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (asking)
    return (
      <span className="row" style={{ gap: 6 }}>
        <span className="small">{props.question ?? t("common.really")}</span>
        <button
          className="btn small danger"
          onClick={() => {
            setAsking(false);
            props.onConfirm();
          }}
        >
          {t("common.yes")}
        </button>
        <button className="btn small ghost" onClick={() => setAsking(false)}>
          {t("common.no")}
        </button>
      </span>
    );
  return (
    <button className={props.className ?? "btn small ghost"} onClick={() => setAsking(true)} disabled={props.disabled}>
      {props.children}
    </button>
  );
}
