# infrastructure

Empty in Phase 0 by design: local dev uses free-tier cloud services (Supabase,
Upstash) directly rather than Docker Compose (see the Phase 0 report — Docker
wasn't installed on the dev machine, and the cloud-first path was chosen to
unblock immediately). Deploy target (Vercel for `apps/web`, a container host
for `apps/api`/`workers`) is an explicit future decision, not made yet — see
spec section 24/67. This directory is where that configuration lands once
decided.
