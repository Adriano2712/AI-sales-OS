from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class AIRequest:
    task: str
    """Short identifier for what this call is for, e.g. 'business_analysis'."""
    system_prompt: str
    user_prompt: str
    output_schema: type[BaseModel]
    model: str | None = None
    """Overrides the provider's default model for this task."""


@dataclass
class AIResponse:
    output: BaseModel
    raw_text: str
    provider: str
    model: str
    tokens_input: int
    tokens_output: int
    latency_ms: int
    estimated_cost_usd: float


class AIProviderError(Exception):
    """Raised for any provider failure (timeout, rate limit, invalid response, ...).

    The caller (ai_gateway.service) is responsible for classifying whether a given
    error is retryable — this exception alone doesn't carry that distinction.
    """


class AIProvider(ABC):
    name: str

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        """Executes the request and returns schema-validated output.

        Implementations MUST validate the model's raw output against
        `request.output_schema` before returning, and raise AIProviderError
        (not return a partial/invalid AIResponse) when validation fails.
        """
        raise NotImplementedError
