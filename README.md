# AI Sales OS

Máquina de inteligência comercial: descobre empresas automaticamente, analisa
presença digital e negócio, identifica oportunidades, prioriza e ajuda um
humano a abordá-las. Ferramenta interna, construída para nascer pronta para
multi-tenant, hoje rodando em produção real (automação diária, sozinha, sem
supervisão) descobrindo empresas em 8 países.

Ver a especificação completa de produto e arquitetura no prompt original do
projeto. Este README cobre o estado atual do código.

## O que o sistema faz, de ponta a ponta

```
Campanha (segmento + cidades + quantidade)
   │
   ▼
Discovery Engine ──> OpenStreetMap + Apify (Google Maps), em paralelo
   │   identidade resolvida (HIGH/MEDIUM/LOW/NONE match), sem duplicar
   ▼
Enrichment ──> evidências (telefone, site, Instagram, reviews do Google, ...)
   │   fallback: se não achou site, tenta Brave Search antes de desistir
   ▼
Website Analysis ──> crawler próprio (sem JS) ──> Digital Score (6 dimensões)
   │   + diagnóstico de problemas em português + parágrafo de impacto (IA)
   ▼
Business Analysis ──> scores determinísticos + AI Analyst (Claude)
   │   fit, atividade, maturidade digital, necessidade, compatibilidade
   ▼
Opportunity Engine ──> score 0-100 (9 fatores) + classificação
   │   HIGH / GOOD / REVIEW / LOW, sem chamada de IA (tudo já é conhecido)
   ▼
Dashboard / Analytics ──> "com quem devo falar" + métricas do funil completo
   │
   ▼
SDR Assistido ──> humano escolhe canal ──> rascunho de mensagem (IA) ──>
   aprova/edita ──> envia manualmente (ou cria rascunho real no Gmail)
```

Tudo isso roda **automaticamente e encadeado** a partir da criação de uma
campanha — descoberta, enriquecimento, análise de site, análise de negócio e
pontuação de oportunidade disparam um no outro via fila de jobs, sem
intervenção humana. A única etapa que exige uma ação humana explícita é a
geração de mensagem (gasta IA de propósito, só quando alguém decide abordar
aquela oportunidade).

Além disso, um **scheduler autônomo** (`workers/scheduler.py`) roda 24/7 e,
sem nenhum humano abrir um terminal: dispara descoberta todos os dias
alternando entre 8 países já validados manualmente, reenfileira jobs que
ficaram travados, e manda um resumo por email (oportunidades boas + diagnóstico
de sites) sempre que uma campanha termina.

## Stack

| Camada | Escolha |
|---|---|
| Frontend | Next.js 16 + React 19 + TypeScript, Tailwind CSS |
| Backend | Python 3.12 + FastAPI, SQLAlchemy 2.0 (async) + Alembic |
| Banco | PostgreSQL 16 (Supabase — Postgres + Auth + RLS) |
| Fila | Redis (Upstash) + RQ |
| IA | AI Gateway próprio — Model Router multi-provider: Anthropic (Claude, default) + Gemini |
| Descoberta | OpenStreetMap/Overpass (grátis, sem chave) + Apify/Google Maps (opcional) |
| Busca de fallback | Brave Search API (achar site quando nenhum provider de descoberta tem) |
| Email | Gmail via SMTP/IMAP (digest diário + rascunhos reais na pasta de Rascunhos) |

Justificativas em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Sem Docker e
sem n8n de propósito — ver a mesma doc para o porquê.

## Arquitetura

Modular monolith: um processo FastAPI serve a API, um ou mais processos RQ
processam jobs assíncronos, ambos compartilham o mesmo código de domínio
(`apps/api/src/app/modules/*`). Sem microsserviços — nada aqui justifica essa
complexidade ainda.

```
apps/web (Next.js)  --HTTPS-->  apps/api (FastAPI)  <--RLS-scoped SQL-->  Postgres (Supabase)
                                       |
                                       v
                                    Redis  <-- workers/run.py (RQ)
                                       ^
                                       |
                              workers/scheduler.py (tick a cada 15min)
```

`apps/web` nunca consulta o Postgres diretamente para dados de negócio — só a
API faz isso. Supabase Auth só autentica (emite o JWT que a API verifica);
autorização e isolamento de tenant vivem na API + RLS do Postgres (defesa em
duas camadas — ver [docs/SECURITY.md](docs/SECURITY.md)).

## Estrutura

```
apps/web/               Next.js (frontend) — login, dashboard, campaigns, companies, opportunities, analytics
apps/api/               FastAPI + domínio (modular monolith)
  src/app/modules/        auth, tenancy, jobs, ai_gateway, audit, campaigns, discovery,
                           companies, enrichment, evidence, website_analysis,
                           business_analysis, opportunities, messages, notifications, dashboard
  tests/unit/              29 arquivos — lógica pura, sem dependências externas
  tests/integration/       24 arquivos — contra banco/fila reais (RLS, jobs, pipeline completo)
workers/                Processos de longa duração (importam handlers de apps/api)
  run.py                   worker RQ (processa jobs da fila)
  scheduler.py             scheduler autônomo (rotação diária de países, retries, digest por email)
  scripts/                 daemons PowerShell (auto-restart) + scripts de diagnóstico pontuais
database/
  migrations/              Alembic — única fonte de verdade do schema
  seeds/                   seed de tenant de dev
docs/                   Documentação por módulo (ver abaixo)
packages/shared-types/  Reservado para tipos TS compartilhados entre apps (ainda vazio)
infrastructure/         Reservado para IaC (ainda vazio — hoje tudo é Supabase/Upstash hospedados)
tests/                  Reservado para testes end-to-end cross-app (ainda vazio)
```

## Documentação

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — desenho geral e por quê
- [ENVIRONMENT.md](docs/ENVIRONMENT.md) — setup local
- [DATABASE.md](docs/DATABASE.md) — schema, RLS, migrations
- [AI.md](docs/AI.md) — AI Gateway, Model Router, custos por tarefa
- [DISCOVERY.md](docs/DISCOVERY.md) — Discovery Engine, providers, resolução de identidade, Smart Refill
- [WEBSITE_ANALYSIS.md](docs/WEBSITE_ANALYSIS.md) — crawler + Digital Score + diagnóstico
- [BUSINESS_ANALYSIS.md](docs/BUSINESS_ANALYSIS.md) — scores determinísticos + AI Analyst
- [OPPORTUNITIES.md](docs/OPPORTUNITIES.md) — Opportunity Engine, Opportunity Score 2.0
- [DASHBOARD.md](docs/DASHBOARD.md) — Dashboard + métricas
- [MESSAGES.md](docs/MESSAGES.md) — SDR Assistido / Message Generation
- [DAILY_DIGEST.md](docs/DAILY_DIGEST.md) — automação diária (8 países) + resumo por email
- [ANALYTICS.md](docs/ANALYTICS.md) — métricas completas e página /analytics
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — rodando worker/scheduler como processo persistente (Windows)
- [SECURITY.md](docs/SECURITY.md) — secrets, authN/authZ, LGPD

## Módulos e o que cada um resolve

| Módulo | Resolve | IA? |
|---|---|---|
| `discovery` | Encontra empresas reais via OSM + Apify, resolve duplicatas (HIGH/MEDIUM/LOW/NONE), Smart Refill quando a busca fica curta do alvo | Não |
| `enrichment` | Extrai telefone/site/Instagram/reviews, fallback de busca de site via Brave | Não |
| `website_analysis` | Crawler próprio → 6 sub-scores (Funcionamento/Mobile/UX/Conversão/Conteúdo/Design), nunca pontua falha técnica como site ruim | Opcional (parágrafo de impacto) |
| `business_analysis` | Combina scores determinísticos com julgamento do AI Analyst (fit, compatibilidade, potencial de compra) | Sim (Claude Sonnet) |
| `opportunities` | Score final 0-100 (9 fatores, pesos configuráveis por campanha) + classificação HIGH/GOOD/REVIEW/LOW | Não |
| `messages` | Gera rascunho de abordagem sob demanda, nunca inventa cliente/resultado, cria rascunho real no Gmail | Sim (Claude Sonnet) |
| `ai_gateway` | Interface única para IA — Model Router decide o provider por tarefa, loga custo real de todo call | — |
| `campaigns` | Define segmento/cidades/quantidade/serviços/pesos de uma busca; liga `auto_discovery_enabled` | — |
| `companies` | Registro canônico de empresa, resolução de identidade | — |
| `evidence` | Log de evidências com polaridade (POSITIVE/NEGATIVE/NEUTRAL/UNKNOWN) — regra absoluta: ausência de dado nunca é sinal negativo | — |
| `tenancy` / `auth` | Multi-tenant real via JWT (Supabase, JWKS/ES256) + RLS no Postgres | — |
| `jobs` | Fila de trabalho assíncrono, idempotência, retry | — |
| `dashboard` | Lista priorizada de oportunidades ("com quem falar") | — |
| `audit` | Log estruturado de eventos relevantes | — |

## Automação contínua (produção real)

`workers/scheduler.py`, de pé 24/7 (ver [DEPLOYMENT.md](docs/DEPLOYMENT.md)
para como isso persiste através de reinícios no Windows), a cada 15 minutos:

1. **Rotação diária de 8 países** — Brasil, EUA, Espanha, Portugal, França,
   Reino Unido, Alemanha, Itália — um por dia, cada um já validado manualmente
   (termos de busca + domínios de diretório excluídos) antes de entrar na
   rotação automática.
2. **Reenfileira jobs travados** (`RETRYING` há tempo demais) de qualquer
   tenant, até 3 tentativas antes de marcar `FAILED` de verdade.
3. **Envia o digest diário** por email assim que um run termina (negócio +
   diagnóstico de sites, cada um com seu próprio controle de idempotência).

Custo real medido: ~$0,05–0,07/dia (~$1,50–2,00/mês) para 5 empresas/dia via
Apify + Claude.

## Começando

Ver [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) para o passo a passo completo.
Resumo:

```bash
# Backend
cd apps/api
python -m venv .venv
source .venv/Scripts/activate   # .venv/bin/activate no macOS/Linux
pip install -e ".[dev]"

# Migrations (ver docs/DATABASE.md — precisa de DATABASE_URL, MIGRATIONS_DATABASE_URL, APP_ROLE_PASSWORD)
cd database/migrations && alembic upgrade head

# Frontend
pnpm install   # na raiz do repo

# Rodando tudo
cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000 --app-dir src
apps/api/.venv/Scripts/python workers/run.py
pnpm --filter web dev
```

Variáveis de ambiente (ver `.env.example` na raiz): Supabase (Postgres + Auth),
Upstash Redis, Anthropic, Gemini (opcional), Apify (opcional), Brave Search
(opcional), Gmail SMTP/IMAP (opcional, digest e rascunhos) — cada integração
externa é opcional e o sistema degrada graciosamente sem ela (nunca falha
silenciosamente fingindo que funcionou).

## Testes

```bash
# Unitários — lógica pura, sem dependências externas (29 arquivos)
cd apps/api && .venv/Scripts/python -m pytest tests/unit -v

# Integração — contra banco/fila reais, RLS incluído (24 arquivos)
export TEST_ADMIN_DATABASE_URL=...
export TEST_DATABASE_URL=...
export DATABASE_URL=$TEST_DATABASE_URL
.venv/Scripts/python -m pytest tests/integration -v -n auto
```

## Segurança e LGPD

- Isolamento de tenant em **duas camadas**: a API só consulta com contexto de
  tenant já definido, *e* o Postgres (RLS) recusaria linhas de outro tenant
  mesmo que esse contexto fosse esquecido por um bug.
- JWT verificado via JWKS do próprio projeto Supabase (ES256), nunca um
  segredo compartilhado — defende contra algorithm-confusion.
- Dado pessoal (contato nomeado) é mantido distinto de dado público de
  negócio (nome/telefone/site da empresa); `do_not_contact` é checado em
  todo ponto de disparo de mensagem, inclusive no envio, não só na geração.
- Detalhes completos em [docs/SECURITY.md](docs/SECURITY.md).

## Fases

Plano original (master prompt):

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
| 8 | SDR Assistido | Completa |
| 9 | Experimento real (100 empresas) | Completa |

Cada fase segue: analisar → planejar → apresentar → aguardar aprovação →
implementar → testar → autorrevisar → relatar → aguardar aprovação. Nenhuma
fase avança sem aprovação explícita.

Além do plano original, iteração contínua pós-lançamento (rodando campanhas
reais) já passou por mais ~18 fases incrementais — multi-model AI Gateway,
Opportunity Score 2.0, Smart Refill, Daily Opportunity Report, Analytics,
fallback de busca de site via Brave Search, email como campo core, geração
automática de mensagens, e a rotação diária de descoberta em 8 países com
daemons persistentes no Windows (ver [DEPLOYMENT.md](docs/DEPLOYMENT.md) e
`git log --grep="^Fase"` para o histórico completo).
