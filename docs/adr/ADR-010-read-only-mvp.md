# ADR-010: Read-only MVP; no customer environment mutation before R4

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §1, §3.3, ADR-009

## Context

The first products are Assess and Design. Mutation adds credential risk, blast radius, incident handling and approval complexity long before those are justified. The source portfolio shows that an "apply" path built early becomes an unreviewed default.

## Decision

- R1 to R3 operate strictly read-only against customer environments.
- The assessment and design plane contains no applier and cannot mutate a customer environment by construction.
- Provider credentials requested and validated for read-only scope only.
- Design produces Terraform **plan previews**, not applies.
- Modernization produces diffs, validation results and proposals, not write-backs.
- Execution is introduced only in R4, behind approval (ADR-009) and evidence (ADR-008).

## Consequences

**Positive**

- Safe pilots and evaluations with a small blast radius.
- Security review is materially shorter.
- The product must prove value before asking for write access.

**Negative**

- Customers who expect automated remediation wait until R4.
- Some value stories are deferred, for example cost remediation.
- Read-only scopes differ per provider and need per-provider validation.

**Neutral**

- The architecture still reserves the execution seam so R4 is additive, not a rewrite.

## Alternatives considered

1. **Gated writes from R1.** Faster remediation story, much higher risk and review cost.
2. **Writes only behind a feature flag.** Flags leak; the applier still exists in the read-only plane.
3. **No execution ever.** Rejects the Modernize and Operate product direction.

## If rejected

Expect premature operational risk and a security review that blocks the assessment pilot.
