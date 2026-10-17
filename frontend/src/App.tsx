import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { homeFor, useAuth } from "./auth/auth";
import { Spinner } from "./components/ui";
import { AppShell } from "./layouts/AppShell";
import { ADMIN_NAV, TENANT_NAV } from "./layouts/nav";
import { t } from "./i18n";
import { LoginPage } from "./pages/Login";
import { AccountPage } from "./pages/Account";
import { AdminOverviewPage } from "./pages/admin/Overview";
import { AdminTenantDetailPage, AdminTenantsPage } from "./pages/admin/Tenants";
import { AuditPage } from "./pages/common/Audit";
import { JobsPage } from "./pages/common/Jobs";
import { PlatformSettingsPage, TenantSettingsPage } from "./pages/common/Settings";
import { UsersPage } from "./pages/common/Users";
import { TenantOverviewPage } from "./pages/tenant/Overview";
import { tenantRoutes, adminRoutes } from "./routes";

const DriverApp = lazy(() => import("./driver/DriverApp"));

function RequireAuth({ children, roles }: { children: ReactNode; roles?: string[] }) {
  const { me, loading } = useAuth();
  if (loading) return <div style={{ padding: 40 }}><Spinner /></div>;
  if (!me) return <Navigate to="/login" replace />;
  if (me.mfa_setup_required && !window.location.pathname.startsWith("/konto")) return <Navigate to="/konto/2fa" replace />;
  if (roles && !roles.includes(me.role)) return <Navigate to={homeFor(me)} replace />;
  return <>{children}</>;
}

function TenantGate({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  if (me && me.role === "admin" && !me.acting_as_tenant) return <Navigate to="/admin" replace />;
  return <>{children}</>;
}

function Home() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  return <Navigate to={homeFor(me)} replace />;
}

function NotFound() {
  return (
    <div className="empty" style={{ margin: 40 }}>
      <h3>{t("errors.not_found_page")}</h3>
    </div>
  );
}

export function App() {
  return (
    <Suspense fallback={<div style={{ padding: 40 }}><Spinner /></div>}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/fahrer/*" element={<DriverApp />} />
        <Route
          element={
            <RequireAuth>
              <AppShellForRole />
            </RequireAuth>
          }
        >
          <Route path="/konto" element={<AccountPage />} />
          <Route path="/konto/2fa" element={<AccountPage />} />
        </Route>
        <Route
          path="/admin"
          element={
            <RequireAuth roles={["admin"]}>
              <AppShell nav={ADMIN_NAV} />
            </RequireAuth>
          }
        >
          <Route index element={<AdminOverviewPage />} />
          <Route path="betriebe" element={<AdminTenantsPage />} />
          <Route path="betriebe/:id" element={<AdminTenantDetailPage />} />
          <Route path="einstellungen" element={<PlatformSettingsPage />} />
          <Route path="protokoll" element={<AuditPage platformOnly />} />
          <Route path="system" element={<JobsPage admin />} />
          <Route path="konten" element={<UsersPage admin />} />
          {adminRoutes()}
          <Route path="*" element={<NotFound />} />
        </Route>
        <Route
          path="/betrieb"
          element={
            <RequireAuth roles={["owner", "dispatcher", "admin"]}>
              <TenantGate>
                <AppShell nav={TENANT_NAV} />
              </TenantGate>
            </RequireAuth>
          }
        >
          <Route index element={<TenantOverviewPage />} />
          <Route path="einstellungen" element={<TenantSettingsPage />} />
          <Route path="benutzer" element={<UsersPage />} />
          <Route path="protokoll" element={<AuditPage />} />
          <Route path="auftraege-im-hintergrund" element={<JobsPage />} />
          {tenantRoutes()}
          <Route path="*" element={<NotFound />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}

function AppShellForRole() {
  const { me } = useAuth();
  return <AppShell nav={me?.role === "admin" && !me.acting_as_tenant ? ADMIN_NAV : TENANT_NAV} />;
}
