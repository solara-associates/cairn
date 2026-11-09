# ADR-012: TenantId is a domain concept, with database RLS as a backstop

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §8, §12, ADR-013

## Context

Every customer artefact in CAIRN is tenant-scoped: projects, connections, estate observations, findings, costs, plans, approvals and evidence. Application-only filtering has a single point of failure: one missed predicate exposes another tenant's estate.

## Decision

- `TenantId` is an explicit, required domain value passed through commands, queries and events; it is not inferred from ambient request state alone.
- Tenant context is established by authenticated middleware and propagated explicitly.
- PostgreSQL uses row-level security on every tenant-scoped table as a backstop, with the tenant set on the connection/session.
- BigQuery access uses tenant-scoped datasets or authorized views.
- Adversarial cross-tenant tests run on every read and write path, including async jobs, MCP tools and evidence retrieval.

## Consequences

**Positive**

- Defense in depth: a missing filter does not automatically leak data.
- Isolation is testable and continuously verified.
- Supports the SaaS-first decision (ADR-013).

**Negative**

- Migrations and queries must set session state correctly.
- RLS policies add schema and test overhead.
- Debugging without tenant context becomes harder by design.

**Neutral**

- Schema-per-tenant remains a possible future isolation tier, not the default.

## Alternatives considered

1. **Application-only filtering.** Simple but one bug is a breach.
2. **Schema or database per tenant.** Strong isolation, heavy migration and cost at scale.
3. **Separate deployments per tenant.** Reserved for high-assurance customers after R2.

## If rejected

Expect a credible cross-tenant exposure risk and a difficult security review.
