# ADR-013: SaaS-only multi-tenant product; no supported customer-deployed edition

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §9, §13, ADR-012, ADR-018

## Context

CAIRN must fix its product boundary before identity, tenancy, billing and support are built. The source is open (ADR-018), so third parties can read and self-host the code, but that is different from CAIRN selling and supporting a customer-deployed edition. A supported single-tenant edition would multiply release, support and security work for a solo maintainer.

## Decision

- CAIRN is delivered as a SaaS multi-tenant control plane, with tenant isolation per ADR-012.
- There is no supported customer-deployed or self-hosted edition. The open-source licence allows third parties to self-host without CAIRN support.
- Identity is OIDC-based; enterprise SSO and SCIM follow the first release.
- The first market is mid-market; regulated and enterprise segments follow after R1 is proven.
- Data residency is handled by regional deployment plus jurisdiction packs (ADR-016), not by per-customer forks.
- Helm remains an internal deployment and disaster-recovery tool, not a customer product.

## Consequences

**Positive**

- Smallest operational surface for a solo maintainer.
- One deployment model to secure and support.
- Billing and onboarding are straightforward to instrument.
- Mid-market focus keeps the first release scope bounded.

**Negative**

- Regulated and enterprise prospects wait for later releases.
- Customers who demand a vendor-supported deployment are not addressable.
- The open-source code can be self-hosted by others, so the hosted service must compete on evidence and operations, not on code access alone.

**Neutral**

- Helm charts exist from R0 for internal use; they do not imply a supported customer edition.

## Alternatives considered

1. **Customer-deployed first.** Strong for regulated buyers, but multiplies support and release burden.
2. **Both models at launch.** Highest flexibility with the highest early cost.
3. **SaaS first, supported self-hosting later.** Reasonable, but it is deferred until a new ADR justifies the support load.

## If rejected

Expect a redesign of identity, tenancy, billing and support, or a launch blocked by procurement requirements.
