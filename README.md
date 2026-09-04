# AI Sales OS

Máquina de inteligência comercial: descobre empresas automaticamente, analisa
presença digital e negócio, identifica oportunidades, prioriza e ajuda um
humano a abordá-las. Ferramenta interna, construída para nascer pronta para
multi-tenant.

Ver a especificação completa de produto e arquitetura no prompt original do
projeto. Este README cobre o estado atual do código.

## Stack

| Camada | Escolha |
|---|---|
| Frontend | Next.js 16 + React 19 + TypeScript, Tailwind CSS |
| Backend | Python 3.12 + FastAPI, SQLAlchemy 2.0 (async) + Alembic |
| Banco | PostgreSQL 16 (Supabase — Postgres + Auth + RLS) |
| Fila | Redis + RQ |
| IA | AI Gateway próprio, provider default Anthropic (Claude) |

Justificativas em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Estrutura

```
apps/web        Next.js (frontend)
apps/api        FastAPI + domínio (modular monolith)
workers/        Processo RQ (importa handlers de apps/api) + scheduler.py (opcional, descoberta diária)
database/       Migrations (Alembic) + seeds de dev
docs/           Documentação
```

## Começando

Ver [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

## Documentação

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — desenho geral e por quê
- [ENVIRONMENT.md](docs/ENVIRONMENT.md) — setup local
- [DATABASE.md](docs/DATABASE.md) — schema, RLS, migrations
- [AI.md](docs/AI.md) — AI Gateway
- [DISCOVERY.md](docs/DISCOVERY.md) — Discovery Engine
- [WEBSITE_ANALYSIS.md](docs/WEBSITE_ANALYSIS.md) — crawler + Digital Score
- [BUSINESS_ANALYSIS.md](docs/BUSINESS_ANALYSIS.md) — scores determinísticos + AI Analyst
- [OPPORTUNITIES.md](docs/OPPORTUNITIES.md) — Opportunity Engine
- [DASHBOARD.md](docs/DASHBOARD.md) — Dashboard + métricas
- [MESSAGES.md](docs/MESSAGES.md) — SDR Assistido / Message Generation
- [DAILY_DIGEST.md](docs/DAILY_DIGEST.md) — Descoberta diária (Brasil inteiro) + resumo por email
- [SECURITY.md](docs/SECURITY.md) — secrets, authN/authZ, LGPD

## Fases

| Fase | Escopo | Status |
|---|---|---|
| 0 | Fundação: monorepo, auth, tenancy, RLS, jobs, AI Gateway skeleton | Completa |
| 1 | Campaigns | Completa |
| 2 | Discovery Engine | Completa |
| 3 | Enrichment | Completa |
| 4 | Website Analysis | Completa |
| 5 | Business Analysis | Completa |
| 6 | Opportunity Engine | Completa |
| 7 | Dashboard | Completa |
| 8 | SDR Assistido | Em revisão |
| 9 | Experimento real (100 empresas) | Não iniciada |

Cada fase segue: analisar → planejar → apresentar → aguardar aprovação →
implementar → testar → autorrevisar → relatar → aguardar aprovação. Nenhuma
fase avança sem aprovação explícita.
