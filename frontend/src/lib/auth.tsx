"use client";

/**
 * Auth state for the whole app.
 *
 * - Supabase owns the session (sign in, refresh, sign out).
 * - Every API call carries the access token via setTokenProvider.
 * - After a real sign-in this browser's guest downloads are attached to the account.
 */

import type { Session, User } from "@supabase/supabase-js";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setTokenProvider, type AuthConfig, type Profile } from "@/lib/api";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

type AuthState = {
  /** false until the initial session lookup has finished */
  ready: boolean;
  /** true when the browser has Supabase keys and can show account features */
  available: boolean;
  config: AuthConfig | null;
  session: Session | null;
  user: User | null;
  me: Profile | null;
  refreshMe: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // Without Supabase keys there is no session to look up, so we are ready immediately.
  const [ready, setReady] = useState(() => !supabaseConfigured);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [me, setMe] = useState<Profile | null>(null);

  const refreshMe = useCallback(async () => {
    const sb = getSupabase();
    if (!sb) return;
    const { data } = await sb.auth.getSession();
    if (!data.session) {
      setMe(null);
      return;
    }
    try {
      setMe(await api.me());
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    api
      .authConfig()
      .then(setConfig)
      .catch(() => setConfig(null));

    const sb = getSupabase();
    if (!sb) return;

    setTokenProvider(async () => {
      const { data } = await sb.auth.getSession();
      return data.session?.access_token ?? null;
    });

    let cancelled = false;
    sb.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSession(data.session);
      setReady(true);
      if (data.session) void refreshMe();
    });

    const { data: sub } = sb.auth.onAuthStateChange((event, next) => {
      setSession(next);
      if (event === "SIGNED_OUT") {
        setMe(null);
        return;
      }
      if (event === "SIGNED_IN") {
        // Attach guest downloads from this browser, then load the profile.
        api
          .claimHistory()
          .catch(() => undefined)
          .finally(() => void refreshMe());
        return;
      }
      if (event === "USER_UPDATED" || event === "TOKEN_REFRESHED") void refreshMe();
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [refreshMe]);

  const signOut = useCallback(async () => {
    const sb = getSupabase();
    if (sb) await sb.auth.signOut();
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      ready,
      available: supabaseConfigured,
      config,
      session,
      user: session?.user ?? null,
      me,
      refreshMe,
      signOut,
    }),
    [ready, config, session, me, refreshMe, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
