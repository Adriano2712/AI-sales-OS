from abc import ABC, abstractmethod

from app.modules.companies.service import NormalizedRawCompany

# Sentinel `city` value a campaign uses to mean "the whole country", not a
# literal place name. Only Apify's location search actually supports this
# (its own docs: "you can just set the whole country... it intelligently
# splits it into subregions internally") — Overpass has no equivalent and
# must reject it (see providers/overpass.py), which the existing
# one-provider-fails-the-other-continues fallback already handles without
# any change to the job handler.
NATIONWIDE_CITY_SENTINEL = "BRASIL"


class DiscoveryProviderError(Exception):
    """Raised for any provider failure (timeout, rate limit, malformed
    response, ...). Callers (the discovery job handler) decide whether a
    given instance is retryable — this exception alone doesn't carry that."""


class DiscoveryProvider(ABC):
    name: str

    @abstractmethod
    async def search(
        self, segment: str, city: str, state: str, country: str, limit: int
    ) -> list[NormalizedRawCompany]:
        """Returns up to `limit` companies for the given segment/city. Domain
        code (the discovery job handler) never talks to a provider's actual
        API — only to this interface. Raises DiscoveryProviderError on
        failure rather than returning a partial/empty result silently."""
        raise NotImplementedError
