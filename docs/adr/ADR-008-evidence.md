# ADR-008: Signed JSON evidence plus a human-readable report, with audit-before-effect

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §12, ADR-009, ADR-016

## Context

CAIRN's differentiator is that a customer, auditor or migration partner can verify what CAIRN observed, what it decided and why. Logs alone do not prove integrity, and a PDF alone is not machine-verifiable. Governed writes are only safe if the audit record exists before the effect.

## Decision

- Produce an evidence package for every assessment, design and execution: inputs, provenance, model/mapping/pattern versions, decisions, outputs and timestamps.
- The package is canonical JSON, hash-chained, signed with a KMS-held key, and verifiable offline with a published verifier.
- Pair it with a human-readable report that references the package hash.
- Governed writes record intent and authorization **before** the effect (audit-before-effect) and fail closed if the audit sink is unavailable.
- Key rotation and verification keys are published; verification does not require CAIRN to be online.

## Consequences

**Positive**

- Independent verification of assessments and changes.
- Strong audit story for regulated customers.
- Tamper detection is testable in CI.

**Negative**

- Added write latency for governed actions.
- Key management and rotation become operational requirements.
- Evidence schema becomes a long-lived compatibility surface.

**Neutral**

- Evidence is stored in Cloud Storage with retention policy; indices remain in Postgres.

## Alternatives considered

1. **Application logs plus a PDF.** Cheap, but no integrity proof.
2. **Post-hoc audit reconstruction.** Fails the audit-before-effect requirement.
3. **Database-only audit table.** Tamperable by anyone with database access and not portable.

## If rejected

The audit and trust story weakens, and retrofitting signing and audit-before-effect later is expensive across every governed write.
