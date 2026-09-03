import { env } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const headers = new Headers(init?.headers);
  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`);
  }

  return fetch(`${env.apiUrl}${path}`, { ...init, headers, cache: "no-store" });
}
