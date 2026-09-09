"""Domains that are never a business's own website — shared between
discovery providers (Overpass/Apify sometimes report a Facebook/Instagram
page directly as `website` in their own raw data) and the website search
fallback (enrichment/website_search.py). Lives here, not in either of
those modules, because both depend on `companies` already — putting it in
either provider-side or enrichment-side module would create a circular
import with the other.

A hit on one of these is real evidence the business exists online, but
never proof of an *owned* website — directories, social platforms, review
aggregators, and delivery marketplaces are never a business's own site
(spec section 86: don't invent what wasn't verified). `Company.website`
means "the business's own domain" for every downstream consumer
(website_analysis crawls and scores *this* page as if it were the
business's own site) — so this same definition has to be enforced
wherever a `website` value first enters the system, not just in one of
the two places it can come from.
"""

from urllib.parse import urlparse

# Grown reactively from real findings (see docs/DISCOVERY.md's Fase 13/17
# validations), never preemptively guessed — expect this to need more
# entries as more of these networks get hit for real.
EXCLUDED_DOMAINS = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "yelp.com",
        "tripadvisor.com",
        "foursquare.com",
        "opentable.com",
        "doordash.com",
        "ubereats.com",
        "grubhub.com",
        "postmates.com",
        "mapquest.com",
        "maps.google.com",
        "google.com",
        "bing.com",
        "yellowpages.com",
        "bbb.org",
        "indeed.com",
        "glassdoor.com",
        "zomato.com",
        "menupix.com",
        "allmenus.com",
        "waze.com",
        "apple.com",
        "yalp.com",
        "nextdoor.com",
        "wikipedia.org",
        # Confirmed the hard way (Fase 13, real Chicago validation): both
        # are subdomain-per-business directory/listing networks, not any
        # individual business's own domain. "La Cocina de Irma" (a real
        # independent restaurant with no website field anywhere in
        # Overpass/Apify) resolved to `lacocinadeirma.restaurants-us.com`
        # on the first real Brave Search call, then to
        # `la-cocina-de-irma.goto-where.com` after excluding the first —
        # strong evidence this specific business may genuinely have no
        # website of its own, not that the search is failing.
        "restaurants-us.com",
        "goto-where.com",
        "weeblyte.com",
        "local.yahoo.com",
        # Confirmed the hard way (Fase 13, real Denver validation): a
        # downtown-area business directory ("250+ stores... restaurants,
        # bars, hotels, and services" per its own homepage), not the
        # business's own site — matched "Cactus Club" via a URL path
        # (`/Business/Cactus-Club/1621-Blake-Street-...`) that embeds the
        # address, the same per-business-page-on-one-shared-domain shape as
        # every other entry in this list. The site itself links to sibling
        # directories for other cities under similar names.
        "denverdowntown.com",
        # Same real Denver "Cactus Club" search — inspecting the raw
        # unfiltered top 10 (once every existing exclusion was applied and
        # still nothing plausible was found) surfaced these five more, none
        # a business's own site: a stock-photo library, a sibling of
        # denverdowntown.com for a different named district (same operator,
        # same `/Business/<name>/<address>` URL shape), a nonprofit/
        # organization data aggregator, a public library historical
        # archive, an architecture-history database, and a private-clubs
        # directory.
        "gettyimages.com",
        "the16thstreetmall.com",
        "causeiq.com",
        "archives.denverlibrary.org",
        "sah-archipedia.org",
        "cmac.ws",
        # Confirmed the hard way (Fase 18, real Portugal/Lisboa validation
        # of the 8-country rotation): a per-business "spots" directory
        # page (`/spots/europe/portugal/.../restaurante-das-marias-.../
        # menu`), same shared-domain-many-businesses shape as every other
        # entry here.
        "novacircle.com",
        # Same Portugal validation, a different company ("Kasa Mia"): a
        # real European restaurant reservation/review platform (the
        # OpenTable/Resy of Europe), not the restaurant's own site.
        "thefork.com",
        # Same "Kasa Mia" search, next result after excluding thefork.com:
        # a real international restaurant review/directory site (the
        # Yelp/TripAdvisor of the restaurant-specific niche).
        "restaurantguru.com",
        # Same "Kasa Mia" search — inspecting the raw unfiltered top 10
        # (every existing exclusion applied, still nothing plausible)
        # showed every single result was a review/directory/social site.
        # Real evidence this business genuinely has no website of its own
        # (same pattern as "La Cocina de Irma", Fase 13): an AI-summarized
        # review aggregator, a car-navigation POI/restaurant directory
        # (Michelin's), a Portuguese lifestyle/listings magazine, a
        # global city-guide directory, and a menu-aggregator site.
        "trustthecrowd.com",
        "viamichelin.com",
        "lifecooler.com",
        "cityseeker.com",
        "menuweb.menu",
        # Confirmed the hard way (Fase 18, real France/Paris validation of
        # the 8-country rotation): a Paris-specific restaurant review/blog
        # directory ("Le Severo" resolved to a per-restaurant review page
        # embedding its own address, same shape as every other directory
        # entry here).
        "parisbymouth.com",
        # Same France validation, a different restaurant ("La Crypte
        # Polska"): a French local-business directory site
        # ("Restaurants Ile-de-France > Restaurants Paris > ...").
        "gralon.net",
        # Same France validation ("Chez Denise"): a personal travel blog,
        # not a directory network -- but its own snippet states outright
        # "Chez Denise does not have a website", i.e. this exact result is
        # itself evidence there is no owned site to find, not a missed one.
        "scottjosephorlando.com",
        # Same France validation ("Le Petit Marche"): a restaurant
        # reservation platform (the OpenTable/TheFork of this search),
        # not the restaurant's own site.
        "autoreserve.com",
        # Re-running the same 4 France companies after the above exclusions
        # surfaced the *next* result down for each -- Paris being one of the
        # most food-media-saturated cities in the world means this list
        # grows faster here than in smaller cities (Denver, Lisboa): major
        # restaurant-review publications/aggregators, not owned sites.
        # ("Le Severo"'s eater.com result even contained the real site,
        # lesevero.fr, plain-text inside its own snippet -- a real gap this
        # exclusion-list approach can't recover on its own, since it only
        # ever looks at the result's URL, not text embedded inside it.)
        "eater.com",
        "cityzeum.com",
        "theinfatuation.com",
        "mindtrip.ai",
        # Third round on "La Crypte Polska": a Paris going-out/listings
        # guide ("Sortir de Paris" -- category "Restaurants > Polonaise"),
        # same per-venue-page-on-one-shared-domain shape as every other
        # directory entry here.
        "sortiraparis.com",
        # Fourth and fifth rounds, same company ("La Crypte Polska"): two
        # more French restaurant directories ("LesRestos", "Koifaire").
        # This one small Paris business turned out to have unusually deep
        # directory coverage; five clean directory hits in a row with
        # nothing else surfacing is itself the evidence it has no
        # independent site of its own, same conclusion as "La Cocina de
        # Irma" and "Kasa Mia" above, not a search failure.
        "lesrestos.com",
        "koifaire.com",
        # Confirmed the hard way (Fase 18, real UK/London validation of the
        # 8-country rotation): "Nadri" resolved to wheree.com, a global
        # reviews/listings aggregator ("Reviews, Photos & Phone Number...")
        # after excluding tripadvisor.co.uk, same shape as every other
        # directory entry here.
        "wheree.com",
        # Confirmed the hard way (Fase 18, real Germany/Berlin validation
        # of the 8-country rotation): a German food-delivery listings
        # directory ("Nam Thuan" resolved to a per-restaurant
        # "Lieferdienst" [delivery service] page), same shared-domain
        # shape as every other directory entry here.
        "restaurant-reservieren-lieferservice.de",
        # Same Berlin validation ("Tibet Haus"): Wolt, a real European food
        # delivery platform (the DoorDash/UberEats of several EU markets),
        # not the restaurant's own site.
        "wolt.com",
        # Same Berlin validation ("Ach!NikO!Ach!"): Kauperts, a German
        # city-business directory network.
        "kauperts.de",
        # Second round on "Tibet Haus" (after excluding wolt.com):
        # HappyCow, a real vegan/vegetarian restaurant review directory,
        # not the restaurant's own site.
        "happycow.net",
        # Confirmed the hard way (Fase 18, real Italy/Roma validation of
        # the 8-country rotation): Time Out, a real multinational city
        # magazine/listings network (same class as Eater above), not the
        # restaurant's own site.
        "timeout.com",
        # Same Roma validation ("Dar filettaro a Santa Barbara"): a travel-
        # guide/blog directory site.
        "likealocalguide.com",
        # Same Roma validation ("Rosati"): an Italian food/confectionery
        # business directory.
        "dolciumi.info",
        # Same Roma validation ("Trattoria Ada e Mario"): Agrodolce, a real
        # Italian food-media/restaurant-guide site.
        "agrodolce.it",
        # Same Roma validation ("Papero Giallo", "Pizzeria Formula 1"):
        # Rome's own official tourism board site -- a government hospitality
        # listing, not the business's own site, same as denverdowntown.com
        # above (an official/aggregator directory, not evidence of an owned
        # domain).
        "turismoroma.it",
        # Same Roma validation ("Gustosando"): Moovit, a public-transit
        # directions app/site -- surfaced because it has a page for "how to
        # get to" this restaurant, never a business's own site.
        "moovitapp.com",
        # Second round, same Roma validation: an Italian restaurant review/
        # ordering directory (the TheFork/Zomato of this search), surfaced
        # for both "Pizzeria ai Marmi" and "Trattoria Ada e Mario" once
        # timeout.com/agrodolce.it were excluded.
        "sluurpy.it",
        # Second round on "Dar filettaro a Santa Barbara": a Rome city
        # guide/media site.
        "roma.com",
        # Second round on "Papero Giallo": Pagine Gialle, Italy's own
        # Yellow Pages business directory.
        "paginegialle.it",
        # Third round on "Trattoria Ada e Mario" (after restaurantguru.it,
        # sluurpy.it): Bestogoo, another restaurant review/directory
        # aggregator -- like "La Crypte Polska" in France, this one small
        # business turned out to have unusually deep directory coverage.
        "bestogoo.com",
    }
)

# A handful of the networks above are confirmed multinational chains that
# run a separate country-code TLD per market (found the hard way, Fase 18
# UK/London validation: "Nadri" resolved to tripadvisor.co.uk, which the
# exact-domain check above can't catch when only tripadvisor.com is
# listed — the 8-country rotation makes every one of these TLD variants a
# near-certainty eventually, not a one-off). Matched by the registrable
# label alone so any country TLD of a *known* chain is caught without
# having to list every variant one country at a time; kept as its own
# small, explicit set (not applied to every EXCLUDED_DOMAINS entry) so an
# unrelated site that happens to share a generic word isn't swept in.
# "restaurantguru" joined this set the same way: confirmed operating both
# restaurantguru.com (Portugal validation) and restaurantguru.it (Italy
# validation) -- a second real sighting, not a guess.
_MULTINATIONAL_DIRECTORY_LABELS = frozenset({"tripadvisor", "restaurantguru"})


def domain(url: str) -> str:
    """example.com from https://www.example.com/path, host-only, lowercased,
    `www.` stripped. Returns "" for anything that doesn't parse to a real
    host, rather than guessing."""
    host = urlparse(url if "://" in url else f"//{url}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_excluded_domain(host: str) -> bool:
    """Matches the bare domain (facebook.com) and any subdomain of it
    (m.facebook.com, business.facebook.com) — a real bug caught during
    Fase 13's own validation: a directory network's per-business subdomain
    (`lacocinadeirma.restaurants-us.com`) would silently pass an exact
    `host in EXCLUDED_DOMAINS` membership check, since no two businesses
    share the same subdomain."""
    if any(host == excluded or host.endswith(f".{excluded}") for excluded in EXCLUDED_DOMAINS):
        return True
    label = host.split(".", 1)[0]
    return label in _MULTINATIONAL_DIRECTORY_LABELS


def is_excluded_website(url: str | None) -> bool:
    """Convenience wrapper for the common case (a raw `website` string,
    possibly None) — used directly by discovery providers deciding whether
    to trust a `website` value Overpass/Apify reported on their own,
    before it ever becomes `NormalizedRawCompany.website`."""
    if not url:
        return False
    return is_excluded_domain(domain(url))
