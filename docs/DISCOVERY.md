# Discovery Engine

**Status: built (Fase 2), enrichment added (Fase 3), multi-provider (OSM +
Apify) added post-Fase-8, Google Review + Social Intelligence added (Fase 4),
Smart Refill added (master-plan Fase 8).**

```
Campaign -> Campaign Run -> Discovery Job -> [OSM, Apify] (concurrent) -> Raw Data
    -> Normalization -> Identity Resolution -> Merge -> Company
```

`DiscoveryProvider` (`app/modules/discovery/base.py`) is an abstract
interface, mirroring the `AIProvider` pattern in `ai_gateway/base.py` —
`app/modules/jobs/handlers/discovery.py` (the job handler) depends on the
interface, never on a specific provider's API shape.

`POST /api/v1/campaigns/{id}/runs` enqueues a `DISCOVERY` job
(`app.modules.jobs.handlers.discovery.run`), which loads the campaign,
splits `target_quantity` across `cities` (`split_target()` — remainder to the
first cities, matching the spec's ~33/33/34 example). For each city, every
configured provider (`build_providers()`) searches **concurrently**
(`asyncio.gather`, one provider's latency never blocks another's) up to
`city_target` results each; results are consolidated before identity
resolution runs — overlap between providers is resolved there, not by
pre-splitting the target between them. Each result runs identity resolution
(`app.modules.companies.service.upsert_company_from_raw`) before persisting a
`Company` + `CompanySource`. One provider's failure for a city, one city
failing entirely, or one company's processing raising, doesn't abort the run
(spec section 28/55) — all three are caught independently and recorded in
`CampaignRun.errors` (with a `provider` key for the first case).

## Provider: OpenStreetMap / Overpass API

Free, keyless (spec section 23). `app/modules/discovery/providers/overpass.py`.

Segment -> OSM tag mapping lives in `app/modules/discovery/segment_mapping.py`
— a technical translation table (Overpass has no concept of "restaurants"
without a tag), not campaign-level config; see that file's docstring for why
this is a deliberately different kind of "hardcoding" than the spec's
no-hardcoded-cities rule (section 9) is about.

### Real findings from testing against the live API (not simulated)

- **Overpass rejects generic HTTP-library User-Agents.** httpx's default
  (`python-httpx/0.27.2`) got a hard `406 Not Acceptable` on every request,
  regardless of query correctness — Overpass's own usage policy expects
  self-identifying clients. Fixed with an explicit `User-Agent` header
  (`_USER_AGENT` in `overpass.py`). This would have made the provider
  completely non-functional in production despite passing every mocked test.
- **Overpass rate-limits the shared public instance** — confirmed `429 Too
  Many Requests` on the third back-to-back city query in manual testing. The
  job handler now sleeps `_PROVIDER_REQUEST_DELAY_SECONDS` (2s) between
  cities to reduce this, but it doesn't eliminate it under real load. Fase
  9's pilot spans ~9 segment × city combinations per full run — if 429s
  still show up in practice, the next step is a dedicated/paid Overpass
  instance, not a bigger delay (diminishing returns on a shared resource).
- **The same fact gets tagged under different OSM keys depending on who
  mapped it.** A real Votorantim restaurant's phone number was tagged
  `mobile`, not `phone` or `contact:phone` — `_to_raw_company` only checked
  the latter two, so the number was silently dropped and enrichment then
  asserted "no public evidence of a phone was found", which was simply
  false. Fixed with `_first_present()`, checking `phone` / `contact:phone` /
  `mobile` / `contact:mobile` (and `website` / `contact:website` / `url`) in
  priority order. Caught running a real discovery run against live data in
  Fase 3, not by any mocked test — worth remembering that this class of gap
  (a tag variant nobody added to the lookup list) can't be fully ruled out,
  only reduced as more real runs surface more variants.
- **Real coverage varies by city**, as expected (spec section 84, item 1):
  manually verified non-empty, real results for all three initial segments —
  restaurants/Sorocaba, clinics/Votorantim, b2b_services/Campinas all
  returned genuine OSM data (business names, some with phone/website).
  `office=*` (b2b_services) is the broadest/fuzziest mapping of the three —
  expect more noise there than the other two once Fase 9 runs at volume.
- **City lookup requires an exact OSM administrative boundary name match.**
  A city that doesn't exist in OSM with that exact `name` tag returns an
  empty list, not an error — a legitimate "no coverage" outcome, not a bug.
  Not yet hit in testing (all three pilot cities resolved fine), but expected
  to matter for smaller/less-mapped cities later.

## Provider: Apify (Google Maps Scraper)

`app/modules/discovery/providers/apify.py`. Second provider, alongside OSM —
not a replacement (spec: "OSM + Apify", not "OSM → Apify"). Optional:
`build_providers()` only adds it when `settings.apify_api_token` is set; the
system degrades to OSM-only otherwise, same pattern as
`ai_gateway`/`anthropic_api_key`.

Uses the `compass/crawler-google-places` actor (configurable via
`APIFY_DISCOVERY_ACTOR`) via Apify's synchronous
`POST /v2/actors/{id}/run-sync-get-dataset-items` endpoint — verified against
the real, live API (input schema fetched from the actor's build metadata,
output fields read from a real one-result test run against this project's
own Apify account) before writing the parser, per this integration's own
"não invente endpoints" rule. Segment → search-term mapping lives in
`segment_mapping.py`'s `SEGMENT_TO_APIFY_SEARCH_TERM`, same containment
pattern as OSM's tag mapping.

**Real fields used** (confirmed present in a live response, not guessed):
`title`, `placeId`, `phone`/`phoneUnformatted`, `website`, `street`/`address`,
`permanentlyClosed`, `openingHours`, `categoryName`, `totalScore`,
`reviewsCount`.

**Google Review Intelligence (Fase 4)**: `totalScore`/`reviewsCount` were
already present in every real Apify payload this project had ever captured
(40 of 41 real `company_sources` rows at the time this was written) but were
previously discarded — extracted now into `NormalizedRawCompany.google_rating`/
`google_review_count`, alongside `google_place_id` (`placeId`), and carried
onto `Company` at upsert time. `enrichment/service.py` turns their presence
into a `CUSTOMER_VALIDATION` evidence signal — real third-party proof of an
active, reviewed business — never a judgment on the rating's actual value
(a 2-star vs. 5-star business isn't scored differently yet; that belongs to
Opportunity Score 2.0, a later phase). Absence is `UNKNOWN`, per the
Opportunity Signal's absolute rule, not a negative signal.

**Social/Instagram Intelligence (Fase 4)**: inspected all 41 real captured
Apify payloads — none contain an Instagram/Facebook handle field anywhere.
Apify's Google Maps actor simply doesn't expose this, so it's never guessed
for Apify-sourced companies. Overpass does have it, as an OSM tag
(`contact:instagram`/`instagram`, same `_first_present` priority pattern as
phone) — extracted into `NormalizedRawCompany.instagram` and stored on
`Company.instagram_url`, a field deliberately separate from `website` (spec:
"website != Instagram"). Promoted from a silent-if-absent "supplementary"
field (Fase 3's original treatment) to a core field that always gets an
evidence row, present-or-`UNKNOWN` — the master spec explicitly lists
"Instagram not found" as an `UNKNOWN` example, which the old
silent-when-absent supplementary path didn't satisfy.

**Real finding, permanently closed places**: Apify's Google Maps data
reports `permanentlyClosed` directly — OSM has no equivalent. A place
reported closed is discovered already `INVALID`
(`NormalizedRawCompany.permanently_closed` → `upsert_company_from_raw`), with
an evidence row explaining why. This directly answers the correction from
Fase 3 ("só mostre lugares que ainda estão ativos") with a real signal
instead of relying only on manual marking.

**Security finding, fixed before any further use**: the token was initially
passed as a `?token=` query parameter — httpx logs the full request URL at
INFO level (`configure_logging()` enables this), so the token appeared in
plaintext in a real worker log during this integration's own end-to-end
test. Fixed to use an `Authorization: Bearer` header instead (verified this
still authenticates against the real API) — the token is never in a URL
anywhere in this codebase now. If you're reading this after that token was
ever used with the query-param version, rotate it.

## The telefone/site bug — root cause and fix

Traced the full path (`Fonte -> Discovery -> Normalizer -> Dedup -> Database
-> API -> Frontend`) before touching anything. The frontend, API schema, and
Overpass's own extraction were all already correct. The real bug was in
`upsert_company_from_raw` (`companies/service.py`): a HIGH-confidence
duplicate match only ever recorded the new `CompanySource` row and returned
the existing `Company` untouched — phone/website a *later* duplicate (a
re-run, or a second provider) actually had never made it onto the canonical
record. Fixed with `merge_missing_fields()`: fills a gap (`phone`/`website`/
`address`) from a newly-matched duplicate, never overwrites a value that's
already set (two disagreeing sources keep the first-seen value canonical;
the raw record's own value stays recoverable via `CompanySource.data`
either way). Regression-tested in
`tests/integration/test_discovery_job.py::test_rerunning_discovery_fills_in_phone_found_the_second_time`
and the cross-provider case,
`test_cross_provider_duplicate_is_merged_via_matching_domain`.

## Identity resolution (spec section 27)

`app/modules/companies/service.py`: `classify_match()` is a pure function
(unit tested exhaustively in `tests/unit/test_identity_resolution.py`),
`upsert_company_from_raw()` is the DB-touching orchestration around it.

- **HIGH** (auto-merge — attaches a new source to the existing company,
  doesn't create a duplicate row): matching known `(provider, external_id)`,
  matching website domain, or matching phone — any one of these alone is
  sufficient. Note: because phone-alone is already HIGH, "name + phone" can
  never independently surface as a weaker signal; that combination is
  subsumed.
- **MEDIUM** (creates a new `Company` row, flagged `needs_review=True` — no
  review UI yet, that's Fase 7/Dashboard): same normalized name **and** same
  address.
- **LOW** (creates a new row, not flagged): fuzzy name similarity (≥0.85,
  `difflib.SequenceMatcher`) **and** same address. Never auto-merged, per
  spec's explicit instruction.
- **NONE**: everything else, including same name alone with no address/phone
  corroboration — name matching by itself is deliberately never enough.

Candidate lookup is bounded to the same tenant + segment + city (not the
whole tenant) — reasonable at this project's scale (~30-35 companies per
segment per campaign) and avoids needing fuzzy matching inside SQL.

## Master-plan Fase 8: Smart Refill

**The gap this closes**: before this phase, `_run` (`jobs/handlers/discovery.py`)
ran each provider exactly once per city with `limit=city_target` and marked
the run `COMPLETED` unconditionally, with no check against whether it
actually reached `target_quantity` of real, workable companies. A run that
came up short (many duplicates, invalid/closed businesses, or companies
already contacted by an earlier campaign) just silently under-delivered.

**Mechanism**: the original single-pass loop is unchanged (extracted into
`_discover_and_process_city`, reused rather than duplicated) — its output
still populates `companies_found`/`validated`/`duplicates`/`enriched`/
`analyzed` exactly as before, zero behavior change, zero regression risk to
existing tests that assert exact values there. After that pass,
`_count_usable_companies` computes the real, authoritative number: workable
companies (not `CompanyStatus.INVALID`, not `do_not_contact`) that also
aren't already-contacted anywhere in the tenant (an `Opportunity` with a
tracked `outcome` — `OpportunityOutcome` has no ordering, so `outcome is
not None` is the only reliable "something happened" check; deliberately
tenant-wide, not scoped to this campaign run, since a company a *different*
campaign already contacted must not read as fresh supply just because this
campaign rediscovered it). If that falls short of `target_quantity`, up to
`_MAX_REFILL_PASSES` (2) additional passes re-query the *same* configured
cities with the per-city limit multiplied (`× 2`, `× 3`, ...), reusing the
exact same city-processing/identity-resolution pipeline. A pass that
surfaces zero genuinely new company IDs stops the loop immediately
(`discovery_refill_exhausted`) — no point burning more requests against
exhausted supply.

**Deliberately out of scope**: expanding to cities/regions *not* in the
campaign's own configured list. `NATIONWIDE_CITY_SENTINEL` is a real,
working "expand scope" precedent, but it's Apify-only, all-or-nothing
(whole country), and silently overriding a campaign's explicit `cities`
list would violate the operator's own stated targeting intent. Refill only
asks the same cities harder, never new ones.

**Why "ask harder" can genuinely work, for both providers**: confirmed by
reading both providers' `search()` implementations, not assumed. Overpass's
`limit` only truncates a query whose full result set doesn't change — but
that's exactly the point: `results[:limit]` on a *higher* `limit` surfaces
the tail elements a lower limit cut off, as long as real supply exceeds
what was already asked for. Apify's `limit` is passed straight into the
actor's `run_input` as `maxCrawledPlacesPerSearch` — it genuinely crawls
more. Neither provider gets asked to re-fetch a *smaller* remaining
population; both get a real shot at surfacing more of what's actually
there.

**New `CampaignRun` fields, deliberately separate from the originals**:
`refill_attempts`, `refill_companies_found`, `usable_found`,
`skipped_already_contacted`. `companies_found`/`validated`/`duplicates`/
`enriched`/`analyzed` keep meaning exactly what they meant before this
phase (API/dashboard backward-compatibility, and the exact values existing
integration tests assert) — refill activity and the real "did this run hit
its target" number live in their own fields instead of being folded back
in.

**Real end-to-end validation, three scenarios against the live database**
(via a fake provider respecting `limit` like the real Apify actor does,
and a no-op job queue to isolate the refill logic from the unrelated real
Redis dependency the chained WEBSITE_ANALYSIS/BUSINESS_ANALYSIS jobs would
otherwise need):

1. **Real headroom** (12 available, `target_quantity=5`): the original pass
   found 5, refill passes asked for 10 then (capped by real supply) 12 —
   confirming a higher `limit` genuinely surfaces more real companies, not
   just re-processing the same ones.
2. **Exhausted supply** (2 available, `target_quantity=5`): `companies_found=2`,
   `usable_found=2`, `refill_attempts=1` — the loop tried exactly once more,
   found nothing new (same 2 companies re-matched via `MatchConfidence.HIGH`),
   and stopped immediately rather than wasting a second attempt.
3. **Already-contacted skip**: a provider re-finds an existing company (HIGH-
   confidence phone match) that already has `Opportunity.outcome=CONTACTED`,
   plus one genuinely new company, `target_quantity=2`. Result:
   `companies_found=2`, `duplicates=1`, but `usable_found=1` and
   `skipped_already_contacted=1` — the rediscovered, already-contacted
   company correctly doesn't count toward the campaign's quota, matching
   spec's own "skip already-contacted/duplicate leads" instruction exactly.

**Real bug found and fixed by this validation, not by a unit test**: the
first attempt at scenario 2 returned `usable_found=0` even though both
companies existed with a perfectly workable status. Root cause: `SET LOCAL`
tenant context is transaction-scoped (the same gotcha this project has hit
and fixed repeatedly elsewhere) — the last company's `db.commit()` inside
the original pass ended the transaction `set_tenant_context` was set in,
and `_count_usable_companies`'s query ran without re-establishing it. RLS
silently returned zero rows rather than erroring, which is exactly why this
needed a real query against the real database to catch — a mocked/unit
test would never have exercised RLS at all. Fixed by re-calling
`set_tenant_context` immediately before both call sites.

## Fase 13: Website search fallback (real gap found, not anticipated)

**The gap this closes**: a real Chicago campaign found "La Cocina de Irma" —
a real, active restaurant — with `website=None`, because neither Overpass's
OSM tags nor Apify's Google Maps listing had a website field for it. The
user found a listing for it via a plain Google search and asked why the
system said "no website." Investigation confirmed neither source is wrong
about *its own* data — Google Maps and OSM genuinely don't have that field
for this business — but that doesn't mean no website exists anywhere on the
web.

**Mechanism** (`enrichment/website_search.py`): when `company.website` is
still `None` after discovery + `enrich_company`, `find_website_via_search`
calls the Brave Search API with `"{name}" {city} {state}` and accepts the
first result that (a) isn't on a known directory/social/aggregator domain
and (b) has the company's own normalized name appearing verbatim in its
title or snippet. A match sets `company.website`, records a `CompanySource`
(`provider="brave_search"`), and a `MEDIUM`-confidence `Evidence` row
distinct from `enrich_company`'s own earlier `UNKNOWN` claim (kept side by
side, not overwritten — an honest record of what was known at each point).
Runs inline (a single bounded, ~8s-timeout HTTP call), not as a separate
queued job like `website_analysis` — proportionate to its actual cost, and
its result feeds directly into the very next `if company.website:` decision
that already exists in the discovery loop.

**Google Custom Search was tried first and rejected** — not a design
preference, a real blocker: Google retired "search the entire web" for any
Custom Search Engine created from 2026-01-20 onward (confirmed against
Google's own support docs after the toggle in the console UI simply
wouldn't respond). New engines are hard-limited to an explicit list of up
to 50 pre-chosen domains, which defeats the entire purpose of finding an
*unknown* business's site. Brave Search API has no such restriction.

**Real finding during validation, not anticipated in the design**: the
first live call for "La Cocina de Irma" returned
`lacocinadeirma.restaurants-us.com` — a subdomain-per-business menu
directory network, not the business's own domain. Excluding it surfaced a
*second* one (`goto-where.com`), then excluding that surfaced a *third*
(`weeblyte.com`) plus a fourth generic listing site (`local.yahoo.com`).
Inspecting the raw top-10 Brave results with no filtering at all showed
every single one was either a known review/social platform (Yelp,
TripAdvisor, Facebook, MapQuest, Apple Maps, Reddit) or one of these four
directory networks — strong evidence this specific business genuinely has
no website of its own, not that the search or the filtering is broken. The
correct behavior here is reporting "not found," which is what happens once
all four are excluded — a missed real website is an acceptable cost;
confidently linking a directory page as if it were the business's own site
is not (spec section 35).

`_EXCLUDED_DOMAINS` is deliberately grown reactively from real findings
like these, never preemptively guessed, and matched by
`_is_excluded_domain` against the full host *and* any subdomain of it — a
bug caught in the same validation pass, since a bare `host in
_EXCLUDED_DOMAINS` membership check can never catch a per-business
subdomain (no two businesses share one).

**Real validation, full Chicago campaign**: of the 3 companies that
actually had `website=None` after discovery (Jollibee, Sbarro, La Cocina de
Irma), the search fallback correctly found real, verified corporate
websites for the first two (`locations.jollibeefoods.com`,
`sbarro.com/locations/...`) and correctly returned nothing for the third
after excluding all four confirmed directory networks — 2 real gaps closed,
1 correctly left as "not found" rather than mislinked.

## Fase 17: 8-country rotation — Apify search terms for restaurants

Daily-automation planning added 6 countries to the rotation (Brazil and the
US already had verified terms): Spain, Portugal, France, the UK, Germany,
Italy. Each new `SEGMENT_TO_APIFY_SEARCH_TERM["restaurants"]` entry was
checked with a real `ApifyProvider.search()` call against a real city in
that country before being trusted — not just translated from memory, same
discipline as the original US fix (a guessed-but-untested translation is
exactly the class of bug that fix was for).

| Country | Term | Verified against | Real sample result |
|---|---|---|---|
| ES | restaurante | Madrid | "+ que delicia \| Restaurante brasileño Madrid" |
| PT | restaurante | Lisboa | "Restaurante Das Marias" |
| FR | restaurant | Paris | "Restaurant Bar des 'Deux Gares'" |
| GB | restaurant | London | "Casa Nostra Restaurant" |
| DE | Restaurant | Berlin | "Bollenpiepe Restaurant" |
| IT | ristorante | Roma | "Ristorante NOA" |

`clinics`/`b2b_services` are deliberately **not** extended to these
countries yet — no one has run a real search to confirm those terms work
outside BR/US, and per this file's own established rule, an untested
translation is never trusted here just because it looks obviously right.
