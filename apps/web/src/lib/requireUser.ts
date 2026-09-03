import type { User } from "@supabase/supabase-js";
import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

/** Every authenticated page should call this first — redirects to /login
 * instead of letting the page render and hit the API with no session
 * (which just shows a raw 401, not a real login prompt). */
export async function requireUser(): Promise<User> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }
  return user;
}
