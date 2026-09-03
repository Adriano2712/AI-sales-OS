from abc import ABC, abstractmethod

from app.modules.companies.service import NormalizedRawCompany


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
