"""Real per-call cost accounting for ``ModelGateway`` (R5-02b).

R5-02a's (814) ``ModelGateway`` logged ``cost_micro_usd=0`` as a deliberate
placeholder; this module computes a real figure from a ``ModelResponse``'s
own token counts and a per-(provider, model) price rate.

**Judgement call (pricing-reuse-vs-local-table):** R1-13's existing price
list (``cairn_modules.finops.pricing.InMemoryPriceList`` /
``cairn_contracts.finops.PriceListRelease``) was read first, as the brief
asked, and deliberately *not* reused here. Its ``PriceListEntry.
unit_price_minor`` is an integer count of a currency's *minor* unit (e.g.
cents) -- the right granularity for GCP SKUs (a VM-hour, a GB-month), but
far too coarse for LLM token pricing: a typical per-1k-token price is a
fraction of a cent, which would round to zero minor units before this
module ever saw it. Forcing LLM pricing through that shape would either
under-report real cost as zero or require redefining "minor unit" as
micro-USD everywhere a non-LLM caller of ``PriceListRelease`` also reads
it -- both worse than keeping the two mechanisms separate. This module's
``ModelPriceTable`` instead prices directly in ``cost_micro_usd``
(matching ``AiCallRecord.cost_micro_usd``'s own unit), scoped to this
unit's one concern, with no ambition to grow into a second general-purpose
price list.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cairn_kernel.errors import ModelPriceUnavailableError, ValidationError


@dataclass(frozen=True, slots=True)
class ModelPriceRate:
    """Price, in micro-USD, per 1,000 input/output tokens for one
    (provider, model) pair."""

    input_micro_usd_per_1k_tokens: int
    output_micro_usd_per_1k_tokens: int

    def __post_init__(self) -> None:
        for name, value in (
            ("input_micro_usd_per_1k_tokens", self.input_micro_usd_per_1k_tokens),
            ("output_micro_usd_per_1k_tokens", self.output_micro_usd_per_1k_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationError(f"model price rate {name} must be a non-negative integer")


def _key(provider: str, model: str) -> tuple[str, str]:
    return (provider, model)


@dataclass(frozen=True, slots=True)
class ModelPriceTable:
    """A simple, local per-model price-per-1k-tokens table (the judgement
    call documented in this module's docstring), keyed by exact
    ``(provider, model)``.

    Deliberately fails closed: ``rate_for`` an unregistered pair raises
    rather than silently returning a zero rate, so a caller cannot forget
    to price a new model and have it pass as free."""

    rates: Mapping[tuple[str, str], ModelPriceRate] = field(default_factory=dict)

    def rate_for(self, provider: str, model: str) -> ModelPriceRate:
        try:
            return self.rates[_key(provider, model)]
        except KeyError as exc:
            raise ModelPriceUnavailableError(
                f"no price rate registered for provider={provider!r} model={model!r}"
            ) from exc

    def with_rate(self, provider: str, model: str, rate: ModelPriceRate) -> ModelPriceTable:
        updated = dict(self.rates)
        updated[_key(provider, model)] = rate
        return ModelPriceTable(rates=updated)


def compute_cost_micro_usd(
    table: ModelPriceTable,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Real cost, in whole micro-USD, for one model call.

    Rounds up to the nearest whole micro-USD (ceiling division) rather than
    truncating: a call that cost a fraction of a micro-USD still cost
    something, and silently truncating every small call's cost to zero
    would reproduce exactly the "placeholder zero" problem this unit exists
    to fix.
    """

    rate = table.rate_for(provider, model)
    raw = (
        input_tokens * rate.input_micro_usd_per_1k_tokens
        + output_tokens * rate.output_micro_usd_per_1k_tokens
    )
    return -(-raw // 1000)  # ceiling division, raw and 1000 both non-negative


def default_price_table() -> ModelPriceTable:
    """Prices covering ``cairn_adapters.model.FakeModelAdapter``'s own
    ``FAKE_PROVIDER``/``FAKE_MODEL`` constants, so a caller that composes
    ``ModelGateway`` against the mandatory fake adapter without supplying
    its own price table still gets a real (non-zero, for any non-trivial
    call) cost figure rather than silently falling back to zero. A
    production composition root supplies its own ``ModelPriceTable`` for
    its real provider/model pairs; this default is scoped to the fake
    adapter's own identity, not a claim about any real provider's pricing.
    """

    return ModelPriceTable(
        rates={
            ("fake", "fake-model-v1"): ModelPriceRate(
                input_micro_usd_per_1k_tokens=500,
                output_micro_usd_per_1k_tokens=1_500,
            ),
        }
    )


__all__ = [
    "ModelPriceRate",
    "ModelPriceTable",
    "compute_cost_micro_usd",
    "default_price_table",
]
