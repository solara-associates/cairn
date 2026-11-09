# CAIRN Architecture Decision Records

This directory holds the architecture decisions for CAIRN. Each ADR is a short, immutable record of a decision, its context and its consequences. ADRs are the mechanism for settling the open product decisions in `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` §19 before code is committed to them.

## Status vocabulary

| Status | Meaning |
|---|---|
| Proposed | Written and awaiting review. It is the working default, not a final commitment. |
| Accepted | Approved by the architecture review. Code may rely on it. |
| Rejected | Considered and declined. The ADR stays to preserve the reasoning. |
| Superseded | Replaced by a later ADR, which is named in the header. |

ADR-017 is Accepted as a product constraint. All other ADRs are Proposed as of 2026-11-09.

## Decision log

| ADR | Title | Status | Date | Blocks R0 exit |
|---|---|---|---|---|
| [ADR-001](ADR-001-monorepo.md) | Monorepo with independently deployable apps | Proposed | 2026-11-09 | Yes |
| [ADR-002](ADR-002-hexagonal-ddd.md) | Clean/Hexagonal architecture with DDD, enforced by import-linter | Proposed | 2026-11-09 | No |
| [ADR-003](ADR-003-canonical-estate-model.md) | One canonical estate model, versioned | Proposed | 2026-11-09 | No |
| [ADR-004](ADR-004-mapping-registry.md) | One mapping registry with immutable releases | Proposed | 2026-11-09 | No |
| [ADR-005](ADR-005-gcp-first.md) | GCP-first adapters behind provider-neutral contracts | Proposed | 2026-11-09 | Yes |
| [ADR-006](ADR-006-python-rust.md) | Python 3.12 for domain and application, Rust only for the transformation hot path | Proposed | 2026-11-09 | No |
| [ADR-007](ADR-007-postgres-bigquery.md) | PostgreSQL for OLTP and registry metadata, BigQuery for analytics | Proposed | 2026-11-09 | Yes |
| [ADR-008](ADR-008-evidence.md) | Signed JSON evidence plus a human-readable report, with audit-before-effect | Proposed | 2026-11-09 | No |
| [ADR-009](ADR-009-approval-binding.md) | Approval is bound to an immutable plan revision | Proposed | 2026-11-09 | No |
| [ADR-010](ADR-010-read-only-mvp.md) | Read-only MVP; no customer environment mutation before R4 | Proposed | 2026-11-09 | Yes |
| [ADR-011](ADR-011-mcp-a2a.md) | MCP per bounded context, with an A2A bridge | Proposed | 2026-11-09 | No |
| [ADR-012](ADR-012-tenant-isolation.md) | TenantId is a domain concept, with database RLS as a backstop | Proposed | 2026-11-09 | No |
| [ADR-013](ADR-013-saas-first.md) | SaaS multi-tenant control plane first, customer-deployed deferred | Proposed | 2026-11-09 | Yes |
| [ADR-014](ADR-014-model-port.md) | One MVP model provider behind ModelPort; additional providers are adapters | Proposed | 2026-11-09 | Yes |
| [ADR-015](ADR-015-clean-room-transform-engine.md) | Build one transformation engine clean-room in Rust | Proposed | 2026-11-09 | No |
| [ADR-016](ADR-016-launch-jurisdiction.md) | One launch jurisdiction pack first, versioned like a mapping release | Proposed | 2026-11-09 | No |
| [ADR-017](ADR-017-clean-room.md) | Greenfield clean-room implementation; no code reuse from reference repositories | Accepted | 2026-11-09 | Yes (constraint) |

**Blocking set for R0 exit:** ADR-001, ADR-005, ADR-007, ADR-010, ADR-013, ADR-014. These change repository shape, adapter scope, data stores, the mutation boundary, the product boundary or the model dependency. Everything else can be amended during R0/R1 without rework.

**Accepted constraint:** ADR-017 fixes the build as greenfield. It is not reopened by review; reversing it requires a new ADR and a rewrite of spec section 17, ADR-015 and the delivery outlook.

## How decisions change

1. A proposed ADR is reviewed as a document; amend it in place until it is accepted or rejected.
2. Once accepted, an ADR is not edited except for status, typo fixes and link updates.
3. A changed decision gets a new ADR that supersedes the old one; the old header gains `Superseded by ADR-0xx`.
4. Any change to a contract in technical spec §7-§13 requires an ADR and a version bump, per spec §0.

## Review checklist

For each ADR, the reviewer should be able to answer:

- Is the context factual and free of assumptions presented as facts?
- Is the decision specific enough that two engineers would implement it the same way?
- Are the consequences honest, including the negative ones?
- Is the rejected alternative genuinely viable, or a straw man?
- Does the decision conflict with any other Proposed or Accepted ADR?

## Template

```md
# ADR-0xx: Title

- **Status:** Proposed
- **Date:** YYYY-MM-DD
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §x, ADR-0yy

## Context

## Decision

## Consequences

**Positive**

**Negative**

**Neutral**

## Alternatives considered

## If rejected
```
