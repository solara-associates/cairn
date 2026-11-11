# CAIRN Architecture Decision Records

This directory holds the architecture decisions for CAIRN. Each ADR is a short, immutable record of a decision, its context and its consequences. ADRs settle the product and architecture choices behind `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` before code relies on them.

## Status vocabulary

| Status | Meaning |
|---|---|
| Proposed | Written and awaiting review. It is the working default, not a final commitment. |
| Accepted | Approved by the product owner. Code may rely on it. |
| Rejected | Considered and declined. The ADR stays to preserve the reasoning. |
| Superseded | Replaced by a later ADR, which is named in the header. |

All ADRs are Accepted as of 2026-11-09, with ADR-009, ADR-010 and ADR-012 amended on 2026-11-10. The product owner accepted the recommended defaults, with the deviations recorded in ADR-003, ADR-010 and ADR-013.

## Decision log

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-monorepo.md) | Monorepo with independently deployable apps, public at `solara-associates/cairn` | Accepted | 2026-11-09 |
| [ADR-002](ADR-002-hexagonal-ddd.md) | Clean/Hexagonal architecture with DDD, enforced by import-linter | Accepted | 2026-11-09 |
| [ADR-003](ADR-003-canonical-estate-model.md) | One canonical estate model, versioned; full model defined up front | Accepted | 2026-11-09 |
| [ADR-004](ADR-004-mapping-registry.md) | One mapping registry with immutable releases; Allan Smeyatsky approves | Accepted | 2026-11-09 |
| [ADR-005](ADR-005-gcp-first.md) | GCP-first adapters behind provider-neutral contracts | Accepted | 2026-11-09 |
| [ADR-006](ADR-006-python-rust.md) | Python 3.12 for domain and application, Rust for transformation and measured hot paths, from R0 | Accepted | 2026-11-09 |
| [ADR-007](ADR-007-postgres-bigquery.md) | Cloud SQL PostgreSQL (europe-west2) for OLTP, BigQuery for analytics | Accepted | 2026-11-09 |
| [ADR-008](ADR-008-evidence.md) | Canonical signed JSON evidence, chain-head integrity, audit-before-effect and CAIRN-held keys | Accepted (amended) | 2026-11-09 |
| [ADR-009](ADR-009-approval-binding.md) | Immutable revisions; approvals and executions bind to exact revision rows, mutation class and recovery strategy | Accepted (amended) | 2026-11-09 |
| [ADR-010](ADR-010-gated-writes.md) | Operation and mutation classes; recovery preconditions; no Class C customer mutation before R4; kernel execution gate | Accepted (amended) | 2026-11-09 |
| [ADR-011](ADR-011-mcp-a2a.md) | MCP per bounded context, with an A2A bridge, internal until R5 | Accepted | 2026-11-09 |
| [ADR-012](ADR-012-tenant-isolation.md) | Tenant isolation as a kernel contract, with forced database RLS and application-role conformance tests | Accepted (amended) | 2026-11-09 |
| [ADR-013](ADR-013-saas-first.md) | SaaS-only multi-tenant product; no supported customer-deployed edition; mid-market first | Accepted | 2026-11-09 |
| [ADR-014](ADR-014-model-port.md) | Gemini-only model provider behind ModelPort; no customer BYO key | Accepted | 2026-11-09 |
| [ADR-015](ADR-015-clean-room-transform-engine.md) | Build one transformation engine clean-room in Rust; Terraform and Python first | Accepted | 2026-11-09 |
| [ADR-016](ADR-016-launch-jurisdiction.md) | United Kingdom launch jurisdiction pack, versioned like a mapping release | Accepted | 2026-11-09 |
| [ADR-017](ADR-017-clean-room.md) | Greenfield clean-room implementation; no code reuse from reference repositories | Accepted | 2026-11-09 |
| [ADR-018](ADR-018-open-source.md) | Open-source distribution under Apache-2.0 with professional services revenue | Accepted | 2026-11-09 |

## Decisions that differ from the original proposal

- **ADR-003:** the full estate model is defined up front, not an assessment-only slice.
- **ADR-010:** corrected by the architecture review. No Class C customer-environment mutation before R4. R1 is read-only assessment plus Class B workspace decisions and deterministic gate validation.
- **ADR-013:** SaaS only. There is no supported customer-deployed edition; the open-source licence permits unsupported self-hosting.
- **ADR-006:** Rust starts in R0, not R3.
- **ADR-014:** Gemini is the only provider at launch.

## Architecture review amendments (9 November 2026)

The R0 architecture and security review corrected contradictions before implementation started. These are deliberate pre-implementation corrections directed by the product owner, not silent edits; the normal supersession rule applies after R0 acceptance.

- **ADR-009:** approvals and executions bind to immutable revision rows with database-enforced hashes and explicit state machines.
- **ADR-010:** operations are classified as A/read, B/workspace or C/governed environment mutation. No Class C operation is possible before R4. The execution gate is a kernel capability that every interface must call.
- **ADR-012:** tenancy is a kernel contract covering tables, APIs, MCP, events, storage, mappings and workers. RLS is forced, with composite tenant/project keys and explicit global-versus-tenant mapping authority.
- **ADR-008:** evidence canonicalization, signature coverage, chain-head uniqueness and offline verification are explicit.

## Second architecture review amendments (10 November 2026)

The second pre-implementation review hardened recovery, idempotency and RLS conformance before R0 scaffolding. As with the first review, these are deliberate pre-implementation corrections directed by the product owner, recorded in the decision log and the ADR status.

- **ADR-009:** approvals and executions additionally bind to the mutation class and recovery strategy. A reversible mutation without a validated rollback reference, or a compensatable mutation without a compensation reference, cannot reach `APPROVED`. Idempotency is scoped to tenant, project, operation and key with a canonical request hash.
- **ADR-010:** every operation gains a recovery-oriented mutation class (read-only, internal, reversible external, compensatable external, irreversible external). External mutations require a rollback, compensation or explicit risk-acceptance precondition defined and validated before authorization. Irreversible mutations cannot transition to `ROLLED_BACK`.
- **ADR-012:** migration and adversarial tenancy tests run under the application database role, not the table owner, and assert forced RLS and that no application role holds `BYPASSRLS`.

## How decisions change

1. An accepted ADR is not edited except for status, typo fixes and link updates. Pre-implementation corrections approved by the product owner are recorded in the decision log and the ADR status; after R0 acceptance this exception closes.
2. A changed decision gets a new ADR that supersedes the old one; the old header gains `Superseded by ADR-0xx`.
3. Any change to a contract in technical spec §7-§13 requires an ADR and a version bump, per spec §0.

## Review checklist

For each new or superseding ADR, the reviewer should be able to answer:

- Is the context factual and free of assumptions presented as facts?
- Is the decision specific enough that two engineers would implement it the same way?
- Are the consequences honest, including the negative ones?
- Is the rejected alternative genuinely viable, or a straw man?
- Does the decision conflict with any other Accepted ADR?

## Template

```md
# ADR-0xx: Title

- **Status:** Proposed
- **Date:** YYYY-MM-DD
- **Deciders:** Product owner (Allan Smeyatsky)
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
