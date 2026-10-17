import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { homeFor, useAuth } from "../auth/auth";
import { Card, ErrorBox, PageHeader, useToast } from "../components/ui";
import { t } from "../i18n";

export function AccountPage() {
  const { me, refresh } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");

  const enable = async () => {
    setError(null);
    try {
      await api.post("/api/auth/2fa/enable", { code });
      setSetup(null);
      setCode("");
      await refresh();
      toast({ text: t("account.twofa_enabled") });
      if (me?.mfa_setup_required) navigate(homeFor({ ...me, mfa_setup_required: false }));
    } catch (e) {
      setError(e);
    }
  };

  const disable = async () => {
    setError(null);
    try {
      await api.post("/api/auth/2fa/disable", { code });
      setCode("");
      await refresh();
    } catch (e) {
      setError(e);
    }
  };

  const changePw = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/api/auth/password", { old_password: oldPw, new_password: newPw });
      setOldPw("");
      setNewPw("");
      toast({ text: t("account.password_changed") });
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div style={{ maxWidth: 760 }}>
      <PageHeader title={t("account.title")} description={me?.user?.email ?? undefined} />
      {me?.mfa_setup_required && <div className="alert warn" style={{ marginBottom: 16 }}>{t("account.twofa_required")}</div>}
      <ErrorBox error={error} />
      <div className="stack lg" style={{ marginTop: 16 }}>
        <Card title={t("account.twofa_title")}>
          {me?.user?.totp_enabled ? (
            <div className="stack">
              <div className="alert ok">{t("account.twofa_enabled")}</div>
              <div className="row">
                <input className="input num" style={{ width: 160 }} placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} aria-label={t("login.code")} />
                <button className="btn ghost" onClick={disable}>
                  {t("account.twofa_disable")}
                </button>
              </div>
            </div>
          ) : setup ? (
            <div className="stack">
              <p className="muted">{t("account.twofa_intro")}</p>
              <dl className="dl">
                <dt>{t("account.twofa_secret")}</dt>
                <dd className="mono">{setup.secret}</dd>
                <dt>{t("account.twofa_uri")}</dt>
                <dd className="mono xs" style={{ wordBreak: "break-all" }}>
                  {setup.uri}
                </dd>
              </dl>
              <div className="row">
                <input className="input num" style={{ width: 160 }} placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} aria-label={t("login.code")} autoFocus />
                <button className="btn" onClick={enable}>
                  {t("account.twofa_enable")}
                </button>
              </div>
            </div>
          ) : (
            <div className="stack">
              <p className="muted">{t("account.twofa_intro")}</p>
              <div>
                <button className="btn" onClick={async () => setSetup(await api.post("/api/auth/2fa/setup"))}>
                  {t("account.twofa_start")}
                </button>
              </div>
            </div>
          )}
        </Card>
        {!me?.mfa_setup_required && me?.user?.email && (
          <Card title={t("account.password_title")}>
            <form className="stack" onSubmit={changePw}>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="old-pw">{t("account.old_password")}</label>
                  <input id="old-pw" className="input" type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
                </div>
                <div className="field">
                  <label htmlFor="new-pw">{t("account.new_password")}</label>
                  <input id="new-pw" className="input" type="password" minLength={10} value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
                </div>
              </div>
              <div>
                <button className="btn" type="submit">
                  {t("common.save")}
                </button>
              </div>
            </form>
          </Card>
        )}
      </div>
    </div>
  );
}
