"use client";

// Who is logged in. The token lives in localStorage (this is a demo-grade single-server login: no cookies, no refresh);
// api.ts reads it through getToken() and sends it as a bearer header on every request.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { AuthUser } from "./types";

const KEY = "rallyos-token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the session lasts until the tab is closed */
  }
}

interface AuthState {
  user: AuthUser | null;
  ready: boolean;                                   // the saved token has been checked
  signIn: (token: string, user: AuthUser) => void;
  signOut: () => void;
}

const Ctx = createContext<AuthState>({ user: null, ready: false, signIn: () => undefined, signOut: () => undefined });

export function AuthProvider({ children, loadMe }: { children: ReactNode; loadMe: () => Promise<AuthUser> }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let live = true;
    if (!getToken()) {
      setReady(true);
      return;
    }
    loadMe()
      .then((u) => live && setUser(u))
      .catch(() => { setToken(null); })               // expired or from another server: start logged out
      .finally(() => live && setReady(true));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signIn = useCallback((token: string, u: AuthUser) => { setToken(token); setUser(u); setReady(true); }, []);
  const signOut = useCallback(() => { setToken(null); setUser(null); }, []);
  return <Ctx.Provider value={{ user, ready, signIn, signOut }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);

/** Where each role starts. */
export const homeFor = (u: AuthUser | null) => (!u ? "/login" : u.role === "coach" ? "/coach" : "/me");
