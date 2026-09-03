# Discovery Engine

**Status: built (Fase 2), enrichment added (Fase 3), multi-provider (OSM +
Apify) added post-Fase-8.**

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
`permanentlyClosed`, `openingHours`, `categoryName`.

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
