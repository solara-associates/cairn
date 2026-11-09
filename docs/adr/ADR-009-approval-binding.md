# ADR-009: Approval is bound to an immutable plan revision

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §11, §12, ADR-008, ADR-010

## Context

A common failure in migration tooling is "approve once, apply anything": an approver signs off on a plan, then the plan or its inputs change before execution. That is a compliance failure, not a usability detail.

## Decision

- Every plan is an immutable revision with a content hash covering inputs, estate model version, mapping release, pattern versions and generated change set.
- An approval references a specific revision hash and the approver identity.
- Execution refuses to run if the current revision hash does not match the approved hash.
- Any change produces a new revision and requires re-approval.
- Separation of duties is enforced by risk tier; the author of a change cannot be its sole approver where the policy forbids it.

## Consequences

**Positive**

- What was approved is exactly what executes.
- Auditors can verify revision, hash and approver.
- Prevents silent drift between plan and apply.

**Negative**

- Late edits force re-approval, which can feel slow.
- Approval UX must surface revision differences clearly.
- Hash canonicalization must be deterministic and tested.

**Neutral**

- Approval records live in Postgres; evidence packages reference the approval id and hash.

## Alternatives considered

1. **Approve the current plan at execution time.** Simple but reintroduces the original risk.
2. **Approve a plan family or scope.** Flexible but not verifiable.
3. **Approval on the Terraform plan file only.** Misses model, mapping and pattern inputs.

## If rejected

Approvals become advisory, and CAIRN cannot claim governed execution.
