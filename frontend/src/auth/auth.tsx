import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";

export type Me = {
  user: { id: string; name: string; email: string | null; role: string; totp_enabled: boolean; staff_member_id: string | null } | null;
  label: string;
  role: string;
  via: string;
  permissions: string[];
  tenant: { id: string; name: string; slug: string } | null;
  acting_as_tenant: boolean;
  mfa_setup_required: boolean;
};

type AuthState = {
  me: Me | null;
  loading: boolean;
  has: (perm: string) => boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.get<Me>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
  const me = query.data ?? null;
  const value: AuthState = {
    me,
    loading: query.isLoading,
    has: (perm) => !!me?.permissions.includes(perm),
    refresh: async () => {
      await qc.invalidateQueries();
    },
    logout: async () => {
      await api.post("/api/auth/logout");
      qc.clear();
      window.location.href = me?.role === "driver" ? "/fahrer" : "/login";
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function homeFor(me: Me | null): string {
  if (!me) return "/login";
  if (me.mfa_setup_required) return "/konto/2fa";
  if (me.role === "driver") return "/fahrer";
  if (me.role === "admin" && !me.acting_as_tenant) return "/admin";
  return "/betrieb";
}
