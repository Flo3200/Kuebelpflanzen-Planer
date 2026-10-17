import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { homeFor, type Me } from "../auth/auth";
import { Botanical } from "../components/Botanical";
import { t } from "../i18n";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { email, password, code: needCode ? code : undefined });
      const me = await api.get<Me>("/api/auth/me");
      qc.setQueryData(["me"], me);
      navigate(homeFor(me));
    } catch (err) {
      if (err instanceof ApiError && err.code === "errors.mfa_required") setNeedCode(true);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page botanical-page">
      <Botanical variant="olive" style={{ right: "-4%", top: "6%", width: "min(560px, 55vw)", opacity: 0.11 }} strokeWidth={1.2} />
      <Botanical variant="fern" style={{ left: "-3%", bottom: "-6%", width: "min(360px, 40vw)", opacity: 0.09 }} />
      <Botanical variant="citrus" style={{ right: "18%", bottom: "-10%", width: "min(300px, 30vw)", opacity: 0.07 }} />
      <div className="login-card">
        <div className="login-brand">
          <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M6 26 C 8 14, 16 6, 27 5 C 27 16, 19 25, 6 26 Z" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M6 26 C 12 19, 18 12, 27 5" fill="none" stroke="currentColor" strokeWidth="1.2" />
          </svg>
          <div>
            <div className="login-name">{t("app.name")}</div>
            <div className="muted small">{t("app.tagline")}</div>
          </div>
        </div>
        <h1>{t("login.title")}</h1>
        <p className="muted">{t("login.subtitle")}</p>
        <form onSubmit={submit} className="stack" style={{ marginTop: 24 }}>
          <div className="field">
            <label htmlFor="email">{t("login.email")}</label>
            <input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">{t("login.password")}</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {needCode && (
            <div className="field">
              <label htmlFor="code">{t("login.code")}</label>
              <input id="code" className="input num" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
            </div>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="btn" type="submit" disabled={busy} style={{ marginTop: 8 }}>
            {t("login.submit")}
          </button>
        </form>
        <p className="small muted" style={{ marginTop: 24 }}>
          {t("login.driver_hint")} <a href="/fahrer">{t("login.driver_link")}</a>
        </p>
      </div>
    </div>
  );
}
