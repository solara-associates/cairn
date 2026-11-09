# ADR-018: Open-source distribution with professional services revenue

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** ADR-001, ADR-013, ADR-017

## Context

CAIRN has no pilot customer and no committed delivery team beyond the product owner. Adoption therefore depends on the code being inspectable and credible before revenue exists. The product owner has chosen an open-source solution with professional services engagements, rather than a closed commercial SaaS alone.

## Decision

- The source is public at `github.com/solara-associates/cairn` under the Apache License 2.0.
- The hosted, multi-tenant service (ADR-013) remains the commercial product. Revenue comes from the hosted service, professional services and support, not from withholding the code.
- There is no open-core gate at launch: the same codebase serves the hosted service and public users.
- Contributions are accepted under the Developer Certificate of Origin, without a contributor licence agreement.
- The repository must never contain secrets, customer data or internal runbooks. CI secret scanning is mandatory.
- The CAIRN name and marks remain with Solara Associates; the licence covers code, not branding.
- A public security disclosure policy and a `SECURITY.md` are required before the first public announcement.

## Consequences

**Positive**

- Adoption does not depend on a sales team or a pilot logo.
- Public code and evidence claims are inspectable, which supports the trust proposition.
- Professional services engagements follow from users who adopt the hosted service or self-host.
- Contributors can improve the platform without a commercial contract.

**Negative**

- Competitors can host the code, so CAIRN must compete on operations, evidence and expertise.
- Public issue and security handling becomes a maintainer duty for a solo team.
- Apache-2.0 permits commercial reuse, including by competitors.
- Every commit is public, so experiments and internal notes need a private space.

**Neutral**

- The licence choice can be revisited only with a new ADR and the consent of existing contributors.

## Alternatives considered

1. **Proprietary SaaS.** Simpler competitive moat, but slower adoption with no pilot and no brand.
2. **AGPL-3.0.** Stronger hosted-service protection, but many enterprises avoid it and it complicates professional services.
3. **Open-core with paid enterprise features.** More revenue control, but splits the codebase and the audit story.

## If rejected

Reversing this decision changes repository visibility, the licence, the contribution model and the revenue plan, and requires a new ADR.
