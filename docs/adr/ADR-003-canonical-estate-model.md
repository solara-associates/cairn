# ADR-003: One canonical estate model, versioned

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §6, ADR-004, ADR-007

## Context

Assessment, target design, migration planning and generated infrastructure must describe the same estate. In the source repositories these are separate models, which produces inconsistent outputs and false confidence. Missing data is also frequently treated as zero or as passing.

## Decision

Define a single provider-neutral canonical estate model in `contracts/estate`, covering the full assessment-to-operate domain up front rather than only the first assessment slice:

- Core entities: resource, workload, dependency, finding, cost record, target service, migration plan, approval, execution record, observation and provenance.
- Every attribute carries provenance and an observation timestamp.
- Unknown or uncollected data uses an explicit `UNVERIFIED` / `UNKNOWN` status, never an implicit zero or pass.
- Conflicting observations are preserved, not overwritten.
- The model is explicitly versioned with migrations; adapters may not import cloud SDK types into it.

All assessment, design, planning and IaC generation consume this model. No module may define a competing estate representation.

## Consequences

**Positive**

- One source drives every artefact, so diagram, plan and IaC agree.
- Evidence can explain where each value came from.
- Coverage gaps stay visible to the customer.
- Later releases do not pause to extend the model.

**Negative**

- Schema evolution requires versioning discipline.
- Full-model scope increases R0 and R1 design effort and risks speculative fields; unused entities must be marked and versioned.
- Some provider-specific detail is intentionally lossy in the neutral model.

**Neutral**

- Provider-specific extensions live in a typed `attributes` map with documented keys.

## Alternatives considered

1. **Per-module models mapped at the edges.** Faster initially, but guarantees divergence.
2. **Provider-native passthrough.** Preserves detail but blocks cross-cloud comparison and single-model guarantees.
3. **One model per product archetype.** Directly contradicts the platform premise.

## If rejected

Duplicate models return, design outputs disagree with assessments, and fabricated precision becomes likely.
