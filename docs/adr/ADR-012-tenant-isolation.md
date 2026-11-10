# ADR-012: Tenant isolation as a kernel contract, enforced by database RLS

- **Status:** Accepted (amended 9 November 2026 after architecture review)
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §8, §12, ADR-004, ADR-013

## Context

Every customer artefact in CAIRN is tenant-scoped: projects, connections, estate observations, findings, costs, plans, approvals and evidence. Application-only filtering has a single point of failure: one missed predicate exposes another tenant's estate.

## Decision

- Every persisted or emitted entity is classified as **Global**, **Tenant-owned** or **Project-owned**. The classification covers tables, API resources, MCP tools/resources, events, object storage, evidence packages, mapping data, background workers and service identities.
- `TenantId` is an explicit, required domain value passed through commands, queries and events; it is not inferred from ambient request state alone.
- Tenant and project context are established by authenticated server-side middleware and set into the database session per transaction. They are never accepted from untrusted request parameters.
- PostgreSQL uses `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` on every tenant-owned and project-owned table. Tenant-owned tables get tenant policy; project-owned tables get tenant and project policies. Application roles must not have `BYPASSRLS`.
- Composite foreign keys enforce tenant/project relationships so a project row cannot reference a tenant that does not own it.
- Published global mapping releases are platform-owned and immutable. Tenants may propose mappings and consume published releases; proposal authority never implies global publication authority.
- BigQuery access uses tenant-scoped datasets or authorized views. Object storage uses tenant/project-prefixed paths with server-side authorization.
- Adversarial cross-tenant and cross-project tests run on every read and write path, including async jobs, MCP tools, evidence retrieval and admin operations.

## Consequences

**Positive**

- Defense in depth: a missing filter does not automatically leak data.
- Isolation is testable and continuously verified.
- Supports the SaaS-first decision (ADR-013).

**Negative**

- Migrations and queries must set session state correctly.
- RLS policies, composite keys and classification tests add schema and test overhead.
- Debugging without tenant context becomes harder by design.
- Global data (published mappings, control metadata) must be explicitly separated from tenant data in code and review.

**Neutral**

- Schema-per-tenant remains a possible future isolation tier, not the default.

## Alternatives considered

1. **Application-only filtering.** Simple but one bug is a breach.
2. **Schema or database per tenant.** Strong isolation, heavy migration and cost at scale.
3. **Separate deployments per tenant.** Reserved for high-assurance customers after R2.

## If rejected

Expect a credible cross-tenant exposure risk and a difficult security review.
