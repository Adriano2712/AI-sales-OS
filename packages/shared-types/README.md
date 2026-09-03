# packages/shared-types

Empty in Phase 0: no product types exist yet to share between `apps/web` and
`apps/api`. Once there's real request/response shapes worth keeping in sync
(starting Fase 1, Campaigns), this is where generated types from the API's
OpenAPI schema — or hand-written Zod schemas mirroring the Pydantic ones —
will live, so the two apps can't silently drift out of sync on a contract.
