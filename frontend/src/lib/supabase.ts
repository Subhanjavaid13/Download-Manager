/**
 * Browser-side Supabase client, used only for auth (sign in, session, password reset,
 * Google login). All app data goes through the FastAPI backend.
 *
 * Returns null when NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set,
 * so the app keeps working in guest mode without accounts.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let client: SupabaseClient | null | undefined;

export function getSupabase(): SupabaseClient | null {
  if (client !== undefined) return client;
  if (!url || !anonKey || typeof window === "undefined") {
    client = null;
    return client;
  }
  client = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      // Implicit flow: the email confirmation link works even when it is opened in a
      // different browser than the one that signed up (common on phones).
      flowType: "implicit",
    },
  });
  return client;
}

export const supabaseConfigured = Boolean(url && anonKey);
