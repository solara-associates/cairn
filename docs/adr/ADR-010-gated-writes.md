# ADR-010: Gated writes from the first release; no un-gated mutation

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §1, §3.3, §12, ADR-008, ADR-009

## Context

The earlier proposal kept CAIRN read-only until R4. The product owner has chosen gated writes from the start: customers should be able to act on a finding without waiting several releases, provided every mutation is authorized, evidenced and reversible. The risk is that an early apply path becomes an unreviewed default, so the gate has to exist before the first write, not after it.

## Decision

- Mutation is permitted from R1, but only through the execution gate: policy check, approval bound to an immutable revision (ADR-009), audit-before-effect and an evidence record (ADR-008).
- No un-gated write path exists in the codebase. A write that bypasses the gate is a defect, not a configuration option.
- The assessment and design services remain read-only and contain no applier. The applier lives in the isolated execution module and is reached only through the gate.
- Assessment credentials stay read-only by default. Write credentials are separate, opt-in per connection and scoped per action.
- R4 is redefined as execution at scale: drift detection, rollback, remediation workflows and broader apply coverage, not the first introduction of mutation.
- The approval service and audit-before-effect path (R4-01 and R4-04) are pulled forward into R1.

## Consequences

**Positive**

- Customers can remediate a validated finding in the first release.
- One gate for every mutation keeps the audit story coherent.
- The execution seam is designed once, early, instead of being retrofitted.

**Negative**

- Security review, blast-radius analysis and incident runbooks are required from R1.
- Approval, evidence and rollback work moves onto the R1 critical path.
- Write credential handling increases the attack surface and the test matrix.
- A solo maintainer carries operational risk earlier than the read-only plan implied.

**Neutral**

- Read-only collection remains the default for assessment; gated execution is a separate capability that customers opt into.

## Alternatives considered

1. **Read-only until R4.** Safer and simpler, but defers the remediation value customers ask for.
2. **Writes behind a feature flag without the gate.** Flags leak and recreate the un-reviewed apply path.
3. **No execution ever.** Rejects the Modernize and Operate product direction.

## If rejected

Reverting to read-only until R4 removes gated write value from R1 and invalidates the approval and evidence dependencies in R1.
