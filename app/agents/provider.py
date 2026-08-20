"""
Phase 2a: the provider abstraction.

Multi-provider from day one (Claude + ChatGPT) so you are never locked in and
have resilience/cost options. BUT a hard rule for calibration integrity:
during a domain's shadow-mode calibration, exactly ONE provider is pinned to
that domain. A 0.8 confidence from Claude is not the same as 0.8 from ChatGPT,
and they drift independently on model updates — mixing them makes the
escalation gate unreasonable.

A provider swap on a calibrated domain is an EVENT that re-opens calibration
(see CalibrationState). The abstraction records which provider produced each
verdict, so confidence is always tracked per (domain x provider).

This module defines the interface and a deterministic fake. Real Claude/OpenAI
adapters implement the same Protocol; no network here so logic stays testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Optional


class Provider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"


@dataclass(frozen=True)
class LLMRequest:
    domain: str
    system_prompt: str
    user_content: str
    web_search: bool = False
    max_tokens: Optional[int] = None


@dataclass(frozen=True)
class LLMResponse:
    provider: Provider
    text: str
    # AI-03: usage is carried on the response so the model gateway can persist it.
    # Previously cache counters were printed to stdout and discarded, which left the
    # platform unable to tell whether caching was saving money or costing 1.25x.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMProvider(Protocol):
    """Every concrete adapter (Claude, OpenAI) implements this."""
    name: Provider
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class ProviderRegistry:
    """
    Maps each domain to its pinned provider. Enforces single-provider-per-domain
    during calibration. Swapping a domain's provider is explicit and auditable.
    """

    def __init__(self) -> None:
        self._adapters: dict[Provider, LLMProvider] = {}
        self._domain_pin: dict[str, Provider] = {}

    def register(self, adapter: LLMProvider) -> None:
        self._adapters[adapter.name] = adapter

    def pin_domain(self, domain: str, provider: Provider) -> None:
        if provider not in self._adapters:
            raise ValueError(f"provider {provider} not registered")
        self._domain_pin[domain] = provider

    def provider_for(self, domain: str) -> Provider:
        if domain not in self._domain_pin:
            raise ValueError(f"no provider pinned for domain '{domain}'")
        return self._domain_pin[domain]

    def complete(self, request: LLMRequest) -> LLMResponse:
        provider = self.provider_for(request.domain)
        return self._adapters[provider].complete(request)
