# ADR-013: SaaS multi-tenant control plane first, customer-deployed deferred

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §9, §13, ADR-012, ADR-005

## Context

CAIRN must decide its product boundary before identity, tenancy, billing and support are built. A customer-deployed product at launch would change all four. The PRD leaves this open; the implementation needs a default.

## Decision

- Launch as a SaaS multi-tenant control plane, with tenant isolation per ADR-012.
- Identity is OIDC-based; enterprise SSO and SCIM follow the first release.
- A customer-deployed (single-tenant) option is deferred until after R2 and delivered via the Helm/Terraform path, not a separate codebase.
- Data residency is handled by regional deployment plus jurisdiction packs (ADR-016), not by per-customer forks.

## Consequences

**Positive**

- Smallest operational surface for the first release.
- One deployment model to secure and support.
- Billing and onboarding are straightforward to instrument.

**Negative**

- Customers who require in-tenant deployment must wait.
- Some regulated prospects will not be addressable at launch.
- Deferred single-tenant work still constrains packaging decisions later.

**Neutral**

- Helm charts exist from R0, so the deferred option is not a rewrite.

## Alternatives considered

1. **Customer-deployed first.** Strong for regulated buyers, but multiplies support and release burden.
2. **Both models at launch.** Highest flexibility with the highest early cost.
3. **SaaS only, permanently.** Rejects enterprise accounts that cannot use a hosted service.

## If rejected

Expect a redesign of identity, tenancy, billing and support, or a launch blocked by procurement requirements.
