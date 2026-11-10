# ADR-010: Operation classes and governed customer-environment mutations

- **Status:** Accepted (amended 9 November 2026 after architecture review)
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §1, §3.3, §9, §10, §11, §12, §16, §20; ADR-008; ADR-009; ADR-012

## Context

The PRD requires that the first usable release must not mutate customer environments. The initial amendment allowed gated writes from R1, which conflicted with that product boundary and created ambiguity about workspace mutations, MCP tools and API endpoints. The architecture review also found that a gate spread across interfaces would be bypassable.

## Decision

### Operation classes

Every operation in CAIRN is classified before implementation.

| Class | Name | Effect | Examples |
|---|---|---|---|
| A | Read | Retrieves information; no persisted state change that alters customer or project decisions | read workload, finding, recommendation, mapping, evidence, assessment result |
| B | Workspace mutation | Changes CAIRN project/assessment records; does not change customer infrastructure, IAM, configuration or deployed workloads | confirm workload classification, record disposition, accept/reject recommendation, accept exception, propose mapping, create/update plan or design, generate artefacts, create project/membership/settings |
| C | Governed environment mutation | Changes a customer cloud environment or deployment target | change cloud config, modify IAM, apply remediation, execute migration, apply IaC, change workload deployment |

### Class A rules

- Authentication and authorization required.
- Tenant and project isolation enforced (ADR-012).
- Audit/read evidence where the operation returns sensitive or evidentiary data.

### Class B rules

- Authentication and authorization.
- Tenant and project isolation.
- Idempotency for externally invoked mutating operations.
- Audit trail with actor attribution.
- Provenance and evidence where the mutation affects an assessment, recommendation, plan or decision.
- Optimistic concurrency (`ETag`/`If-Match`) for mutable records.

Class B operations are **not** "gated writes" in the ADR-009 execution-gate sense. They do not require the customer-environment execution gate unless a specific operation is later reclassified as Class C.

### Class C rules

A Class C operation must pass all of the following before any external effect:

1. Policy evaluation.
2. Approval bound to an immutable revision (ADR-009).
3. Separation-of-duties validation.
4. Audit-before-effect.
5. Execution authorization with scoped, short-lived credentials.
6. Evidence capture.
7. Outcome verification.
8. Rollback handling where supported.

No Class C operation may execute outside the shared execution gate, regardless of origin: UI, API, MCP, agent, job, provider adapter or internal tool. The execution gate is a kernel capability. Interfaces call the gate; they do not implement their own mutation path.

### Release boundary

- R0/R1/R2/R3: **no Class C operations against customer environments**. Assessment is read-only against customer sources (Class A collection with read-only provider credentials). Workspace decisions are Class B.
- R4: Class C operations are introduced only with provider adapters, approval-bound execution, rollback and independently verifiable evidence.
- R1 validates the execution-gate lifecycle against a **deterministic test adapter**. The test adapter cannot be substituted with a production provider adapter, and R1 components cannot obtain execution credentials.

### Credential and network isolation

- Assessment/read credentials are read-only and separate from any future execution credentials.
- Execution credentials are not provisioned before R4 design/implementation and are never available to assessment, design or console components.
- The applier and execution gate run in an isolated module/service identity with no inbound path from assessment workers except through audited control-plane contracts.

## Consequences

**Positive**

- Preserves the PRD first-release boundary: no customer-environment mutation in the first usable release.
- Removes ambiguity between workspace changes and environment changes.
- Makes the execution gate a single kernel invariant that all interfaces must use.
- Allows R1 to prove governance design without exposing customer estates to execution risk.

**Negative**

- R1 cannot remediate findings in customer environments.
- API and MCP contracts must be classified and reviewed before implementation.
- The R4 execution design remains substantial and must not be under-scoped.

**Neutral**

- Workspace mutations still carry audit, idempotency and tenancy obligations.
- The deterministic test adapter is an architecture-validation asset, not a customer feature.

## Alternatives considered

1. **Gated Class C writes from R1.** Rejected because it conflicts with the PRD and moves blast radius too early.
2. **No execution path ever.** Rejected because it blocks the long-term product direction.
3. **Per-interface gates.** Rejected because UI, MCP, API and agents would each reimplement governance.

## If rejected

CAIRN would either mutate customer environments before the PRD allows it, or rely on inconsistent interface-level controls that cannot be proven safe.
