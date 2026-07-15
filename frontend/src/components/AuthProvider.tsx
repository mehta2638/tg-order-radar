"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { ApiClient, getDefaultApiBaseUrl } from "@/lib/api";
import type { Role } from "@/lib/types";

const STORAGE_KEY = "tg-order-radar-admin-session";

interface AuthState {
  apiBaseUrl: string;
  apiKey: string;
  role: Role;
}

interface AuthContextValue {
  session: AuthState | null;
  api: ApiClient | null;
  isReady: boolean;
  login: (session: AuthState) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthState | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setSession(JSON.parse(stored) as AuthState);
    }
    setIsReady(true);
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const api = session ? new ApiClient(session) : null;
    return {
      session,
      api,
      isReady,
      login(nextSession) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession));
        setSession(nextSession);
      },
      logout() {
        window.localStorage.removeItem(STORAGE_KEY);
        setSession(null);
      }
    };
  }, [isReady, session]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}

export function createDefaultSession(): AuthState {
  return {
    apiBaseUrl: getDefaultApiBaseUrl(),
    apiKey: "",
    role: "admin"
  };
}
