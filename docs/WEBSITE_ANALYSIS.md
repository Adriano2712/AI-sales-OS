# Website Analysis

**Status: built (Fase 4).**

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

## Real findings

- **Crawler validated against a real, live third-party site** (not just
  mocked tests): `example.com` — 1 page, correctly extracted title/viewport,
  scored funcionamento=100, mobile=100, design=`UNKNOWN` (no stylesheet).
- **Real production signal, unprompted**: running a live Campinas b2b_services
  discovery, one company's real website (`dextraining.com.br`) failed to load
  entirely. The system correctly recorded `score_funcionamento=0`,
  every other dimension `UNKNOWN`, `digital_score=0` — exactly the kind of
  "this business has a real digital problem" signal the whole product exists
  to surface (spec's central thesis), produced automatically end to end
  through the real queue on the very first live company with a website.

## Data model

```
websites          — one per company (1:1), just the root URL
website_pages      — replaced wholesale on every analysis run (a fresh
                      snapshot; no raw HTML stored, only extracted signals)
website_analyses   — append-only, one row per analysis run (score history)
```
