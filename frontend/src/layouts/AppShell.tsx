import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../auth/auth";
import { t } from "../i18n";
import type { NavItem, NavSection } from "./nav";
import { NotificationBell } from "./Notifications";
import { VoiceControl } from "./VoiceControl";
import { ThemeToggle } from "./ThemeToggle";

function LeafMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M6 26 C 8 14, 16 6, 27 5 C 27 16, 19 25, 6 26 Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M6 26 C 12 19, 18 12, 27 5" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function AppShell({ nav }: { nav: NavSection[] }) {
  const { me, has, mod, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  const visible = (items: NavItem[]) => items.filter((it) => (!it.perm || has(it.perm)) && (!it.module || mod(it.module)));
  const rare = nav.flatMap((section) => visible(section.items).filter((it) => it.rare));
  const [moreOpen, setMoreOpen] = useState(() => {
    try {
      return localStorage.getItem("kp.nav.more") === "1";
    } catch {
      return false;
    }
  });
  const toggleMore = (v: boolean) => {
    setMoreOpen(v);
    try {
      localStorage.setItem("kp.nav.more", v ? "1" : "0");
    } catch {
      /* private mode: only for this visit */
    }
  };
  // an item of "Weitere Bereiche" that is open keeps the group open
  useEffect(() => {
    if (rare.some((it) => location.pathname.startsWith(it.to))) setMoreOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  const leaveTenant = async () => {
    await api.post("/api/auth/act-as", { tenant_id: null });
    await qc.invalidateQueries();
    navigate("/admin/betriebe");
  };

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        {t("app.skip")}
      </a>
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label={t("common.menu")}>
        <div className="brand">
          <LeafMark />
          <div>
            {t("app.name")}
            <small>{me?.tenant?.name ?? t("nav.platform")}</small>
          </div>
        </div>
        <nav>
          {nav.map((section, i) => {
            const items = visible(section.items).filter((it) => !it.rare);
            if (!items.length) return null;
            return (
              <div key={i}>
                {section.label && <div className="nav-section">{t(section.label)}</div>}
                {items.map((it) => (
                  <NavLink key={it.to} to={it.to} end={it.end}>
                    {t(it.label)}
                  </NavLink>
                ))}
              </div>
            );
          })}
          {rare.length > 0 && (
            <div className="nav-more">
              <button className="nav-section nav-more-toggle" onClick={() => toggleMore(!moreOpen)} aria-expanded={moreOpen}>
                {t("nav.more")} <span aria-hidden="true">{moreOpen ? "▾" : "▸"}</span>
              </button>
              {moreOpen &&
                rare.map((it) => (
                  <NavLink key={it.to} to={it.to} end={it.end}>
                    {t(it.label)}
                  </NavLink>
                ))}
            </div>
          )}
        </nav>
        <div className="sidebar-foot">
          <div>{me?.label}</div>
          <div className="row" style={{ gap: 4, marginTop: 6 }}>
            <NavLink to="/konto">{t("account.title")}</NavLink>
            <button className="btn link" onClick={logout}>
              {t("common.logout")}
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn icon ghost menu-toggle" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={t("common.menu")}>
            ☰
          </button>
          <div className="row">
            {me?.acting_as_tenant && (
              <>
                <span className="badge terra">
                  {t("nav.acting_as")}: {me.tenant?.name}
                </span>
                <button className="btn small ghost" onClick={leaveTenant}>
                  {t("nav.back_to_platform")}
                </button>
              </>
            )}
          </div>
          <div className="row" style={{ gap: 4 }}>
            {me?.tenant && has("ai.use") && <VoiceControl />}
            {me?.tenant && has("tenant.view") && <NotificationBell />}
            <ThemeToggle />
          </div>
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
