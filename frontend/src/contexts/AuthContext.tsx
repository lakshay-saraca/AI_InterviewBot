"use client";

import { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";

export type UserRole = "admin" | "candidate";

interface AuthState {
  name: string;
  role: UserRole;
}

interface AuthContextValue {
  user: AuthState | null;
  isAdmin: boolean;
  login: (name: string, role: UserRole) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  isAdmin: false,
  login: () => {},
  logout: () => {},
});

const STORAGE_KEY = "ai_interview_auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthState | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setUser(JSON.parse(stored));
      }
    } catch {}
    setLoaded(true);
  }, []);

  const login = useCallback((name: string, role: UserRole) => {
    const state: AuthState = { name, role };
    setUser(state);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  if (!loaded) {
    return null;
  }

  return (
    <AuthContext.Provider
      value={{ user, isAdmin: user?.role === "admin", login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
