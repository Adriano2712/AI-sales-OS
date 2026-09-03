---
name: phase-report
description: Self-reviews the current AI Sales OS phase (tests, lint, security) and produces the FASE X report in the exact master-prompt format, then stops for approval. Use when a development phase (Fase 0-9) looks done and needs to be reported and approved before moving on.
---

# Phase Report

This project follows a strict phased protocol (master prompt section 75): analisar
→ planejar → apresentar → aguardar aprovação → implementar → testar → validar →
relatar → aguardar aprovação. This skill covers the **testar → validar → relatar**
steps at the end of a phase, right before asking the user to approve moving on.

Never skip straight to writing the report. Always self-review first — that is
the whole point of this skill existing (the user has explicitly asked for this
self-review step every time a phase finishes).

## 1. Figure out what changed

- `git status` and `git diff` (or diff against the last phase's commit/tag if
  one exists) to see everything touched since the previous phase report.
- Read through the diff, don't just glance at file names — you need to be able
  to describe *what* changed in each area (Banco/API/Frontend/Workers/IA) in
  the report.

## 2. Self-review — run everything, don't assume it still passes

Backend (`apps/api`, using its venv, e.g. `apps/api/.venv/Scripts/python` on
Windows):
- `pytest tests/ -v` — note pass/fail/skip counts. Integration tests will skip
  without `TEST_ADMIN_DATABASE_URL`/`TEST_DATABASE_URL` — that's expected and
  must be called out in the report, not silently ignored.
- `ruff check src tests`
- `mypy src`

Frontend (`apps/web`, from repo root or `cd apps/web`):
- `pnpm --filter web build` (or `next build` — also catches TypeScript errors)
- `pnpm --filter web lint`

Security spot-check (don't skip even if nothing "security-related" was
touched — regressions here are silent):
- Any new tenant-scoped table? Confirm it has `TenantScopedMixin`, RLS enabled,
  and a `tenant_isolation` policy in the migration that adds it.
- `git add -A -n` (dry run) and scan the file list for anything that looks like
  a secret (`.env`, credentials, API keys) that shouldn't be tracked.
- Any new endpoint? Confirm it goes through `get_tenant_context`/`get_tenant_db`
  or `require_role()` — nothing should read/write tenant data on a bare
  `get_db` session.

If something fails: fix it if it's small/medium and doesn't change
architecture (master prompt section 77). If it's architectural or a product
question, stop and flag it in the report's "Problemas" section instead of
guessing — do not paper over it to make the report look cleaner.

## 3. Write the report

Use exactly this template (master prompt section 81) — do not add or remove
top-level sections, and do not skip a section even if it's empty (write
"N/A nesta fase" instead of omitting it):

```
# FASE X — RELATÓRIO

Status:
COMPLETA / PARCIAL / BLOQUEADA

## Objetivo
## Implementado
## Arquivos criados
## Arquivos alterados
## Banco
## API
## Frontend
## Workers
## IA
Provider:
Model:
Calls:
Estimated cost:
## Testes
## Segurança
## Performance
## Problemas
## Decisões
## Próxima fase

Aguardando aprovação.
```

Rules for filling it in:
- **Status**: PARCIAL or BLOQUEADA is not a failure to hide — if something
  outside your control (missing credentials, a product decision) is pending,
  say so plainly, the same way the Fase 0 report did.
- **Testes**: report actual counts (e.g. "10 passed, 8 skipped"), not vague
  claims like "tests pass". If integration tests skipped, say why and what's
  needed to unskip them.
- **IA**: even if zero calls were made this phase (common — many phases don't
  touch the AI Gateway), say so explicitly rather than leaving it blank.
- **Decisões**: only decisions actually made this phase, with one line of
  why — not a restatement of Phase 0's decisions.
- Always end with "Aguardando aprovação." and then actually stop. Do not
  start implementing the next phase in the same turn, even if the next steps
  seem obvious — the master prompt is explicit that approval must never be
  skipped (section 76).
