"""R6-06: ``cairn_adapters.model.vertex_gemini.VertexGeminiAdapter`` --
Gemini on Vertex AI, implementing ``ModelPort.generate`` and nothing
else (ADR-014, design §2).

**Authentication.** Application default credentials only, resolved by
the ``google-genai`` client library itself -- in Cloud Run the attached
service account, on a developer machine ``gcloud auth
application-default login``. There is no API key path anywhere in this
module: no ``api_key`` parameter, no ``GOOGLE_API_KEY`` read, no key
literal. The client is constructed lazily (``_default_client``), the
same shape ``cairn_adapters.evidence_kms`` already uses for Cloud KMS,
so importing this module needs no GCP credential and no network call.

**Configuration.** Three non-secret values, read and validated at
startup, never at first call: ``CAIRN_VERTEX_PROJECT``,
``CAIRN_VERTEX_LOCATION`` (restricted to
``cairn_modules.sovereignty.UK_ALLOWED_REGIONS`` -- ADR-007's residency
choice), ``CAIRN_GEMINI_MODEL`` (an exact model id, no alias, because
the model id is written into evidence and an alias would make a run
unreproducible).

**What this adapter does not do.** It does not validate the response
against the caller's schema (``ModelGateway`` already does that, and
R-AI-01 needs exactly one place that can log ``SCHEMA_INVALID``), does
not retry (the gateway's circuit breaker owns failure policy), does not
log (the gateway owns ``AiCallRecord``), and does not cache.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from cairn_kernel.errors import ConfigurationError, ProviderUnavailableError
from cairn_kernel.model.cost import ModelPriceRate, ModelPriceTable
from cairn_kernel.model.ports import (
    ModelPort,
    ModelRequest,
    ModelResponse,
    SafetyMetadata,
)
from cairn_modules.sovereignty import UK_ALLOWED_REGIONS

ENV_PROJECT = "CAIRN_VERTEX_PROJECT"
ENV_LOCATION = "CAIRN_VERTEX_LOCATION"
ENV_MODEL = "CAIRN_GEMINI_MODEL"

PROVIDER = "vertex"

#: Published Vertex AI list prices (per 1k tokens, converted to
#: micro-USD) for the exact pinned model ids this adapter has been
#: tested against, as of Allan's 2026-11-27 decision for this session --
#: a point-in-time figure read from Google's public price list, not a
#: measurement, and not applied automatically to an unrecognised model
#: id (``price_rate_for_model`` fails closed rather than guessing).
#: Allan's brief: "real numbers come before R6-15 deploys" -- this
#: table exists so a deployment has something to start from, and must
#: be reverified against Google's current price list before being
#: relied on for real budget enforcement.
_KNOWN_PRICE_RATES: dict[str, ModelPriceRate] = {
    "gemini-2.5-pro-002": ModelPriceRate(
        input_micro_usd_per_1k_tokens=1_250,
        output_micro_usd_per_1k_tokens=10_000,
    ),
    "gemini-2.5-flash-002": ModelPriceRate(
        input_micro_usd_per_1k_tokens=150,
        output_micro_usd_per_1k_tokens=600,
    ),
}


def price_rate_for_model(model: str) -> ModelPriceRate:
    """The known price rate for an exact Gemini model id.

    Raises ``ConfigurationError`` for a model id not in
    ``_KNOWN_PRICE_RATES`` -- an unpriced model must be priced
    explicitly by whoever configures it, never silently treated as
    free (the same fail-closed shape as ``ModelPriceTable.rate_for``).
    """

    try:
        return _KNOWN_PRICE_RATES[model]
    except KeyError:
        raise ConfigurationError(
            f"no known Vertex Gemini price rate for model {model!r}; register one explicitly "
            "before relying on cost accounting for it"
        ) from None


def register_vertex_price(
    table: ModelPriceTable, settings: VertexGeminiSettings
) -> ModelPriceTable:
    """Return ``table`` with a real ``(vertex, <model id>)`` rate added
    for ``settings.model`` -- the production composition root's one call
    to make the fake's placeholder-zero problem (``cost.py``'s own
    docstring) not apply to real agent runs.
    """

    return table.with_rate(PROVIDER, settings.model, price_rate_for_model(settings.model))


@dataclass(frozen=True, slots=True)
class VertexGeminiSettings:
    """The three non-secret values Vertex Gemini needs, validated at
    construction time (A5.13) rather than at first call -- a missing
    value or a location outside the residency set must fail loudly at
    startup, not three steps into an agent run.
    """

    project: str
    location: str
    model: str

    def __post_init__(self) -> None:
        if not self.project.strip():
            raise ConfigurationError(f"{ENV_PROJECT} is required to construct VertexGeminiSettings")
        if not self.location.strip():
            raise ConfigurationError(
                f"{ENV_LOCATION} is required to construct VertexGeminiSettings"
            )
        if self.location not in UK_ALLOWED_REGIONS:
            raise ConfigurationError(
                f"{ENV_LOCATION}={self.location!r} is outside the allowed residency set "
                f"{sorted(UK_ALLOWED_REGIONS)!r}"
            )
        if not self.model.strip():
            raise ConfigurationError(f"{ENV_MODEL} is required to construct VertexGeminiSettings")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> VertexGeminiSettings:
        """Read the three settings from the environment (or the given
        mapping, for tests) and validate them immediately. Raises
        ``ConfigurationError`` naming every missing value if one or more
        of the three is absent -- a startup failure, not a lazy one.
        """

        source = env if env is not None else os.environ
        missing = [name for name in (ENV_PROJECT, ENV_LOCATION, ENV_MODEL) if not source.get(name)]
        if missing:
            raise ConfigurationError(
                "Vertex Gemini adapter selected but missing required settings: "
                + ", ".join(sorted(missing))
            )
        return cls(
            project=source[ENV_PROJECT],
            location=source[ENV_LOCATION],
            model=source[ENV_MODEL],
        )


def _default_client(settings: VertexGeminiSettings) -> Any:
    """Lazy import so importing this module needs no GCP credential and
    no network call -- only constructing the real adapter without an
    injected client does.
    """

    from google import genai  # pinned exact version, packages/adapters/pyproject.toml

    return genai.Client(vertexai=True, project=settings.project, location=settings.location)


class VertexGeminiAdapter(ModelPort):
    """``ModelPort.generate`` over Gemini on Vertex AI. One method, no
    more -- the port has exactly one, which is the point (ADR-014).
    """

    def __init__(self, settings: VertexGeminiSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else _default_client(settings)

    def generate(self, request: ModelRequest) -> ModelResponse:
        config = self._build_config(request)
        started = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self._settings.model,
                contents=request.prompt,
                config=config,
            )
        except Exception as exc:  # fail closed: no local fallback output
            raise ProviderUnavailableError(f"Vertex Gemini generate_content failed: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        return self._translate_response(request, response, latency_ms)

    def _build_config(self, request: ModelRequest) -> dict[str, Any]:
        return {
            "response_mime_type": "application/json",
            "response_schema": dict(request.structured_output.schema),
            "max_output_tokens": request.safety.max_output_tokens,
            "safety_settings": [
                {"category": category, "threshold": "BLOCK_LOW_AND_ABOVE"}
                for category in request.safety.disallowed_categories
            ],
        }

    def _translate_response(
        self, request: ModelRequest, response: Any, latency_ms: int
    ) -> ModelResponse:
        output = _parsed_output(response)
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        resolved_model = getattr(response, "model_version", None) or self._settings.model
        safety = _translate_safety(response)
        return ModelResponse(
            output=output,
            provider=PROVIDER,
            model=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            safety=safety,
            correlation_id=request.correlation_id,
            tenant_id=request.tenant_id,
        )


def _parsed_output(response: Any) -> dict[str, object]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        import json

        try:
            loaded = json.loads(text)
        except ValueError as exc:
            raise ProviderUnavailableError(
                f"Vertex Gemini response was not valid JSON: {exc}"
            ) from exc
        if isinstance(loaded, dict):
            return loaded
    raise ProviderUnavailableError("Vertex Gemini response carried no parseable JSON output")


def _translate_safety(response: Any) -> SafetyMetadata:
    """Surfaces a provider safety verdict, never swallows one -- a
    blocked prompt or a flagged candidate is reported, not silently
    treated as a clean response.
    """

    prompt_feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(prompt_feedback, "block_reason", None)
    if block_reason:
        return SafetyMetadata(flagged=True, categories=(str(block_reason),))

    categories: list[str] = []
    candidates = getattr(response, "candidates", None) or ()
    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and str(finish_reason).upper() in {
            "SAFETY",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
        }:
            categories.append(str(finish_reason))
        for rating in getattr(candidate, "safety_ratings", None) or ():
            if getattr(rating, "blocked", False):
                categories.append(str(getattr(rating, "category", "UNKNOWN")))

    return SafetyMetadata(flagged=bool(categories), categories=tuple(categories))


__all__ = [
    "ENV_LOCATION",
    "ENV_MODEL",
    "ENV_PROJECT",
    "PROVIDER",
    "VertexGeminiAdapter",
    "VertexGeminiSettings",
    "price_rate_for_model",
    "register_vertex_price",
]
