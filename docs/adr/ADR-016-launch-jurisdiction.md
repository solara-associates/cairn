# ADR-016: One launch jurisdiction pack first, versioned like a mapping release

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §7, §14, ADR-004, ADR-013

## Context

Compliance claims, data residency and control catalogues differ by jurisdiction. The PRD leaves launch jurisdiction open. Attempting global coverage at launch multiplies legal review and control mapping work, while unversioned jurisdiction rules would contradict the reproducibility guarantees.

## Decision

- Launch with the United Kingdom jurisdiction pack, deployed in `europe-west2` (London).
- A pack defines residency constraints, applicable controls, disclaimer text and mapping rules for that jurisdiction.
- Packs are versioned and published through the same immutable release machinery as the mapping registry (ADR-004).
- Every assessment records the jurisdiction pack and version used.
- CAIRN makes no compliance claim that is not backed by a pack, a control version and an evidence record.
- Additional packs are added as new releases, not as code forks.

## Consequences

**Positive**

- Bounded legal and control-mapping effort for launch.
- Jurisdiction-specific claims remain honest and auditable.
- Adding a market is a release, not a code branch.

**Negative**

- The launch market is narrower than a global product.
- Selection of the first pack is a business decision and may change requirements.
- Pack drift requires release discipline.

**Neutral**

- The architecture keeps controls and residency provider-neutral so packs remain data, not code.

## Alternatives considered

1. **Global claims at launch.** Highest reach with unmanageable review and honesty risk.
2. **Multiple packs at launch.** Broader market, slower release.
3. **No jurisdiction pack; custom per customer.** Not reproducible and not scalable.

## If rejected

Expect residency, control and legal review to delay the assessment release, or unsupported compliance claims to appear in output.
