# Website Analysis

**Status: built (Fase 4), status/quality-vs-opportunity split added (Fase 5).**

```
Company (has website) -> WEBSITE_ANALYSIS job -> WebsiteCrawler -> PageSignals
    -> scoring.compute_sub_scores / compute_digital_score -> WebsiteAnalysis
```

Chained automatically off Discovery: after a company is upserted +
enriched, `jobs/handlers/discovery.py` enqueues a `WEBSITE_ANALYSIS` job
(`jobs/handlers/website_analysis.py`) for it if `company.website` is set —
its own queued job, not inline, because crawling a third-party site is real
network I/O that can be slow or fail, and one broken site shouldn't stall
discovery for the rest of the campaign.

## Crawler (spec section 31)

`app/modules/website_analysis/crawler.py`. `httpx` + `BeautifulSoup`, no JS
execution, no headless browser (decision from Fase 0). Defaults: `max_pages=5`,
`max_depth=1` (homepage + one link-hop), `timeout=10s` per request. Same
domain only, no anti-bot/CAPTCHA bypass. Sends a real `User-Agent` (courtesy,
same reasoning as the Overpass provider in Fase 2).

Link prioritization (`signal_extraction.prioritize_links`) prefers, in order:
contact, scheduling, services/menu, about — spec section 31's priority page
list, matched via accent-insensitive keyword search on link href/text.

Pure parsing (`signal_extraction.py`, unit tested) is separated from the
async I/O (`crawler.py`) — the crawler is only integration-tested, against a
mock transport, never a real site in the automated suite.

## Scoring (spec section 32)

`app/modules/website_analysis/scoring.py`. Weights: Funcionamento 20%,
Mobile 20%, UX 15%, Conversão 20%, Conteúdo 15%, Design 10%.

| Dimension | Signal |
|---|---|
| Funcionamento | % of attempted pages that returned < 400 |
| Mobile | `<meta name="viewport" content="width=device-width...">` present on homepage |
| UX | success ratio × a small bonus if a `<nav>` element is present |
| Conversão | any of: contact form, `tel:` link, `mailto:` link, WhatsApp link, a reachable CONTACT-type page |
| Conteúdo | homepage has a title, has a meta description, ≥100 words, and a SERVICES-type page was reached |
| Design | **weak positive-only signal**: 100 if a linked stylesheet is present, otherwise `None` (never scored as bad — see below) |

**A dimension that can't be evaluated is `None`, never a guess** (spec
section 35). If the homepage itself doesn't load, only Funcionamento is
evaluable (= 0) — everything else stays `None`, since nothing else was
meaningfully fetched. `compute_digital_score` averages only the evaluated
dimensions, renormalizing weights over what's available — a company with 2
of 6 dimensions evaluated isn't penalized for the other 4 being unknown.

Design is the one dimension this crawler is honestly bad at: without
rendering the page, presence/absence of a `<link rel="stylesheet">` says very
little either way. Presence is treated as weak positive evidence (worth
recording); absence is left `UNKNOWN` rather than asserted as "bad design",
per the anti-hallucination rule. This was an explicit, approved trade-off
(Fase 4 planning) — a real design score would need a rendering/screenshot
capability, out of scope for now.

## Diagnóstico concreto (`scoring.derive_problems`)

Além dos 6 sub-scores, `derive_problems(pages) -> list[str]` traduz os
mesmos sinais já coletados em problemas em português, defensáveis um a um
("Site não é otimizado para celular", "Nenhuma forma direta de contato",
"Site fora do ar (HTTP 500)", ...). Mesma disciplina anti-alucinação: se a
homepage não carregou, só esse problema é reportado — nada mais foi
avaliado de verdade. Salvo em `website_analyses.findings["problems"]`,
exposto pela API (`findings` já é um `dict` genérico, sem mudança de
schema) e renderizado na página de detalhe da empresa.

## Parágrafo de impacto (IA, opcional — `ai_diagnostic.py`)

Quando `ANTHROPIC_API_KEY` está configurada **e** a homepage carregou
(`digital_score` avaliável), uma chamada adicional de IA (`claude-sonnet-5`,
mesmo modelo do AI Analyst do Fase 5) transforma a lista de problemas num
parágrafo curto de impacto de negócio, em português, salvo em
`findings["ai_diagnostic"]`. Controle de custo explícito (decisão do
usuário): **não é chamada quando o site está fora do ar** — o problema já é
autoexplicativo, uma explicação de IA não agregaria sinal, só custo. Sem
chave configurada, o recurso é pulado silenciosamente — o score e os
problemas determinísticos continuam funcionando normalmente (nunca
dependem de IA).

**Real finding (validação em produção, campanha real de 5 clínicas em
Salvador/BA, 2026-09-04)**: o limite original de `max_length=800` no
schema (`SiteDiagnosticAIOutput.business_impact`) era apertado demais —
uma resposta real, genuinamente dentro do que o prompt pedia (parágrafo de
3-5 frases), ultrapassou 800 caracteres e derrubou o job inteiro de
`website_analysis` (schema validation error, spec section 37 fazendo
exatamente o que deveria — rejeitar o que não passa — só que o limite
estava calibrado errado). Corrigido para `max_length=1600`: continua sendo
uma rede de segurança real contra resposta descontrolada, sem rejeitar
saída válida. A empresa afetada foi reprocessada manualmente com sucesso
depois da correção. Teste de regressão em
`tests/unit/test_website_ai_diagnostic.py`.

## Real findings

- **Crawler validated against a real, live third-party site** (not just
  mocked tests): `example.com` — 1 page, correctly extracted title/viewport,
  scored funcionamento=100, mobile=100, design=`UNKNOWN` (no stylesheet).
- **Real production signal, unprompted**: running a live Campinas b2b_services
  discovery, one company's real website (`dextraining.com.br`) failed to load
  entirely — a genuine, valuable signal ("this business has a real digital
  problem"), produced automatically end to end through the real queue on the
  very first live company with a website. **Superseded by Fase 5**: at the
  time, this was recorded as `score_funcionamento=0`, `digital_score=0` — see
  the Fase 5 section below for why that specific number was actually a bug,
  not the signal it looked like.

## Fase 5: WebsiteStatus + WEBSITE_QUALITY_SCORE vs WEBSITE_OPPORTUNITY_SCORE

**The absolute rule**: a technical failure to observe the site (anti-bot
block, timeout, DNS failure, a JS-only shell this crawler can't render) is
never scored as a *bad* website — that's a business-quality judgment made
from an absence of evidence, exactly what the Opportunity Signal's absolute
rule (Fase 3) forbids. `WebsiteStatus` (`enums.py`) makes this a named,
first-class value instead of an inference from `digital_score is None`:
`WEBSITE_NOT_FOUND`, `OFFLINE`, `BLOCKED`, `JS_REQUIRED`, `TIMEOUT`,
`UNKNOWN` (insufficient evidence, distinct reasons) vs. `ANALYZED`, `GOOD`,
`NEEDS_IMPROVEMENT`, `POOR` (confidently graded from a real, rendered page).
`status.py`'s `derive_website_status` is the one place this gets decided.

**Real bug found and fixed**: `compute_sub_scores` used to compute
`funcionamento` (and therefore `digital_score`) as `0.0` whenever the
homepage was unreachable — 0% of pages responded, so 0.0 was mechanically
correct, but it then single-handedly determined the entire `digital_score`
(100% of the renormalized weight, since every other dimension was already
`None`). A blocked/timed-out/nonexistent site was being scored as literally
the worst possible *quality*, indistinguishable from a real, rendered,
truly terrible page — precisely the false equivalence the absolute rule
forbids. Confirmed against this project's own real data before writing the
fix: **11 of 39 real `website_analyses` rows had `digital_score=0.0`, and
every single one was a fetch failure** (5 real HTTP 403s — a textbook
anti-bot/WAF signal — plus 6 other connection/HTTP failures), never an
actually-rendered bad page. Fixed in `compute_sub_scores`: an unreachable
homepage now returns all six sub-scores as `None`. Migration `0016` fixed
the 11 historical rows to match (reclassified 5 as `BLOCKED`, 6 as
`OFFLINE`, `digital_score`/`score_funcionamento` nulled out on all 11).

**A second instance of the same bug, caught by this phase's own end-to-end
validation (not a unit test)**: a JS-only SPA shell's near-empty HTML still
*has* a homepage that responds 200 — `compute_sub_scores` has no way to
know the real content only exists after JavaScript runs, so it still
produced a real-looking low score (e.g. 33.9) even after the first fix.
`derive_website_status` correctly flagged `JS_REQUIRED`, but nothing yet
stopped `digital_score` itself from silently contradicting that status (and
the AI diagnostic call would still fire, spending money to explain a
fabricated number). Fixed in `service.py`: `digital_score`/
`opportunity_score` are only kept when `status` is in
`status.CONFIDENT_QUALITY_STATUSES` (`GOOD`/`NEEDS_IMPROVEMENT`/`POOR`/
`ANALYZED`) — every other status nulls both back out, regardless of what
`compute_sub_scores` mechanically produced. Regression-tested in
`tests/unit/test_website_status.py::test_js_required_is_not_in_confident_quality_statuses`
and `tests/integration/test_website_analysis_job.py::test_js_only_shell_never_leaks_a_real_quality_score`.

**WEBSITE_OPPORTUNITY_SCORE, distinct from WEBSITE_QUALITY_SCORE**:
`digital_score` (kept under its original name — `business_analysis/
scoring.py` already depends on it) is the site's overall technical/UX
quality. `opportunity_score` (`compute_opportunity_score`) is new and
deliberately narrower: `100 - score_conversao`, the inverse of just the
contact/CTA dimension. A well-built, fast site can still convert poorly
(spec's own positive examples: "CTA fraca", "sem WhatsApp") — a single
blended quality number would dilute exactly that signal. Only computed
when `score_conversao` itself was evaluable, so it inherits the same
absence-handling as `digital_score`.

**Evidence emission, direct (new — Fase 4 never called `get_or_create_evidence`
from this module at all)**: `analyze_website` now records a
`"Website status: {status}"` claim under the new `EvidenceCategory.
WEBSITE_QUALITY`, classified via `_STATUS_SIGNAL` in `service.py` — `GOOD`
is `NEGATIVE` (less room for us — spec's "site moderno adequado" negative
example), `OFFLINE`/`WEBSITE_NOT_FOUND`/`POOR`/`NEEDS_IMPROVEMENT` are
`POSITIVE` (no working site, or a real gap, is itself an opportunity —
spec's "sem site" positive example), `ANALYZED` is `NEUTRAL` (some real
data, not enough to grade), and `BLOCKED`/`TIMEOUT`/`JS_REQUIRED`/`UNKNOWN`
are `UNKNOWN`/`UNKNOWN` — the absolute rule in table form.

**Anti-bot/timeout/DNS classification is real-evidence-based, never a
guess**: `crawler.py`'s `_classify_response` only calls a response
`BLOCKED` for a known anti-bot status code (403, 429) or a genuine
Cloudflare-style challenge marker actually found in the response
body/headers for a 503 — never merely because a request failed. DNS
failure detection (`_is_dns_failure`) walks the exception's `__cause__`
chain for a real `socket.gaierror` (a stable, cross-platform exception
*type*), not a string match on an OS-specific error message.
`JS_REQUIRED` detection (`signal_extraction._looks_js_rendered`) requires
both a near-empty word count *and* a known SPA framework root marker
(`id="root"`, `id="app"`, `id="__next"`, `ng-version=`) actually present in
the fetched HTML — a thin static page with neither marker is still just
thin content (a different, real, already-existing problem), never guessed
as JS-required.

## Data model

```
websites          — one per company (1:1), just the root URL
website_pages      — replaced wholesale on every analysis run (a fresh
                      snapshot; no raw HTML stored, only extracted signals)
website_analyses   — append-only, one row per analysis run (score history)
```
