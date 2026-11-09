# ADR-005: GCP-first adapters behind provider-neutral contracts

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §4.2, §5, ADR-013

## Context

The portfolio is GCP-leaning, and the first customer-facing products depend on credible provider collection, billing import and posture scanning. Building AWS and Azure parity at the same time multiplies adapter and test scope before the assessment journey is proven.

## Decision

- Define provider-neutral ports in `adapters/provider-core` and the kernel.
- Ship the GCP adapter first for inventory, billing and posture.
- Keep AWS and Azure adapters behind the same contract suite, delivered after the assessment release.
- No provider type may appear in `contracts/` or in domain code.
- A fake adapter must satisfy the full contract suite in CI.

File-import ingestion (CSV/JSON/RVTools/HVTools/BOM) remains the fallback for any provider not yet supported.

## Consequences

**Positive**

- Fastest path to a credible read-only assessment.
- Contract suite prevents adapter drift.
- File import covers early multi-cloud prospects without adapter work.

**Negative**

- AWS- and Azure-first customers wait for native collection.
- Provider parity is deferred, not solved.
- GCP-specific assumptions can creep into the neutral model if review is weak.

**Neutral**

- Adapter order is a schedule decision, not an architecture decision; adding a provider does not change contracts.

## Alternatives considered

1. **All three providers at launch.** Highest coverage, slowest and riskiest first release.
2. **AWS first.** Defensible on market size but weaker portfolio leverage.
3. **File import only.** Trivial to build but not a defensible product.

## If rejected

Expect either a slower first release or significant parity cost; the contract layer is still required either way.
