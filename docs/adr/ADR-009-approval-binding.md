# ADR-009: Immutable revisions and approval-bound execution

- **Status:** Accepted (amended 9 November 2026 after architecture review)
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §8, §11, §12, §16; ADR-008; ADR-010

## Context

The architecture review found that approvals referenced a mutable subject plus a hash, without a database-enforced immutable revision. That allows "approve once, apply anything" through application bugs or race conditions. A Class C governed mutation must be provable from the database, not only from application logic.

## Decision

### Immutable revisions

Approvals and executions never target a mutable object directly. They target an immutable revision row.

Revision-bearing subjects (as applicable by release):
- migration plan revision,
- target design revision,
- transformation manifest/execution package revision,
- policy-controlled remediation package revision.

Each revision stores:
- `revision_id` (stable identifier),
- subject identity (`tenant_id`, `project_id`, subject kind/id),
- monotonically increasing `revision_number` within the subject,
- canonical `content_hash`,
- immutable content reference/payload,
- input versions (estate model, mapping release, pattern/policy versions),
- creator and creation timestamp.

Revisions are append-only. A change creates a new revision and never mutates an approved revision.

### Approval binding

An approval record stores:
- `approval_id`, `tenant_id`, `project_id`,
- `subject_kind`, `subject_id`,
- `revision_id` and `revision_hash`,
- `risk_tier`, required roles, state,
- decision actor, timestamp, reason,
- evidence references.

Database constraints must make the binding enforceable:
- `approval.revision_id` references the exact revision row.
- A composite foreign key `(tenant_id, revision_id, revision_hash)` references `subject_revision (tenant_id, revision_id, content_hash)`, so the hash binding is enforced at rest, not only in application code.
- `execution_record` references `approval (tenant_id, approval_id, revision_id, revision_hash)`, so an execution cannot name an approval while using a different revision or hash.
- `execution_record.revision_id` and `execution_record.approved_hash` record the exact approved revision used.

### Execution rules

- Execution is permitted only when approval state is `APPROVED` and the referenced revision is current for that approval.
- Before any Class C effect, the execution gate verifies: policy decision, approval state, revision hash match, separation of duties, credential scope and audit-before-effect success.
- If the revision hash does not match, execution fails closed with `REVISION_MISMATCH` and no external effect.
- Any new revision invalidates prior approvals for execution purposes and requires re-approval.

### State transitions

Approval states:

```text
DRAFT -> PENDING_APPROVAL -> APPROVED -> CONSUMED
                         \-> REJECTED
                         \-> CANCELLED
APPROVED -> EXPIRED         (policy/time-based, no execution)
```

Execution states:

```text
PROPOSED -> AUTHORIZED -> EXECUTING -> SUCCEEDED
                                  \-> FAILED
                                  \-> ROLLED_BACK
AUTHORIZED -> CANCELLED              (before external effect)
```

Invalid transitions are rejected. Every transition is persisted with actor, timestamp, reason, correlation ID and evidence reference.

### Separation of duties

- The author/requester of a Class C execution cannot be the sole approver when policy requires separation.
- Risk tier determines required roles and whether multiple approvers are needed.
- Admin role does not bypass policy evaluation, revision binding or audit-before-effect.

## Consequences

**Positive**

- The database can prove what was approved and what was executed.
- Revisions, approvals and executions are auditable and independently verifiable.
- Silent plan drift becomes a detectable, fail-closed condition.

**Negative**

- More tables and constraints.
- Late edits require new revisions and re-approval.
- Canonical hashing must be deterministic across services.

**Neutral**

- R1 uses revisions/approvals primarily to validate the gate and workspace planning records; Class C execution remains deferred to R4.

## Alternatives considered

1. **Approval references mutable plan plus hash.** Rejected: not enforceable at rest.
2. **Approval at execution time only.** Rejected: loses pre-authorization.
3. **Terraform plan file hash only.** Rejected: ignores model, mapping, policy and workspace inputs.

## If rejected

CAIRN cannot make a credible governed-execution claim, and compliance evidence would be ambiguous.
