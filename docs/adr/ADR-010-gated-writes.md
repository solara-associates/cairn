# ADR-010: Operation classes and governed customer-environment mutations

- **Status:** Accepted (amended 10 and 11 November 2026 after the second and third architecture reviews)
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §1, §3.3, §9, §10, §11, §12, §16, §20; ADR-008; ADR-009; ADR-012

## Context

The PRD requires that the first usable release must not mutate customer environments. The initial amendment allowed gated writes from R1, which conflicted with that product boundary and created ambiguity about workspace mutations, MCP tools and API endpoints. That amendment is superseded: the decision below keeps all customer-environment writes in R4. The architecture review also found that a gate spread across interfaces would be bypassable.

## Decision

### Operation classes

Every operation in CAIRN is classified before implementation.

| Class | Name | Effect | Examples |
|---|---|---|---|
| A | Read | Retrieves information; no persisted state change that alters customer or project decisions | read workload, finding, recommendation, mapping, evidence, assessment result |
| B | Workspace mutation | Changes CAIRN project/assessment records; does not change customer infrastructure, IAM, configuration or deployed workloads | confirm workload classification, record disposition, accept/reject recommendation, accept exception, propose mapping, create/update plan or design, generate artefacts, create project/membership/settings |
| C | Governed environment mutation | Changes a customer cloud environment or deployment target | change cloud config, modify IAM, apply remediation, execute migration, apply IaC, change workload deployment |

### Mutation classification

Operation class answers "may this mutate a customer environment?". Mutation class answers "how recoverable is the effect, and what must be true before authorization?".

| Mutation class | Operation class | Recovery precondition |
|---|---|---|
| `READ_ONLY` | A | None |
| `INTERNAL_MUTATION` | B | No external recovery required |
| `REVERSIBLE_EXTERNAL_MUTATION` | C | Rollback action identified and validated before authorization |
| `COMPENSATABLE_EXTERNAL_MUTATION` | C | Compensating action and trigger identified and validated before authorization |
| `IRREVERSIBLE_EXTERNAL_MUTATION` | C | Explicit risk acceptance, blast-radius declaration and preflight/dry-run where supported; no rollback promise |

Every command declares both classes, and the kernel rejects a mismatch. The execution gate uses the mutation class to set approval tier, evidence obligations and recovery handling. The undo or compensating action is defined before execution, never after.

### Compensation contract

Every external mutation declares a formal compensation contract before it can be proposed for approval. The contract is an immutable artifact bound to the revision and approval, and the execution gate validates it against the mutation class before authorization. A missing or incomplete element blocks authorization.

| Element | Meaning |
|---|---|
| Strategy | `ROLLBACK`, `COMPENSATE` or `ACCEPT_IRREVERSIBLE`, matching the mutation class |
| Preconditions | The rollback or compensating action, its scope, target state, trigger condition and validation checks; blast radius, preflight results and residual risk for irreversible mutations |
| Authority | The approval tier required for the mutation, and the named roles that may trigger and execute recovery |
| Evidence | What must be captured before, during and after the effect, including recovery outcome evidence |
| Failure handling | What happens when recovery itself fails: incident escalation, reconciliation and recorded residual state; never a silent success |

Rules:
- Only the execution plane may execute a rollback or compensation, and only within the scope the approval names.
- A rollback or compensation executes under the authority pre-delegated by the approved contract; deviation from the declared plan requires a new revision and approval.
- Recovery failure is an incident with reconciliation; the execution is `FAILED`, never silently `SUCCEEDED`.

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
8. Recovery handling that matches the mutation class per its declared compensation contract: rollback for reversible, compensation for compensatable, and explicit risk acceptance for irreversible. An irreversible mutation cannot transition to `ROLLED_BACK`.

No Class C operation may execute outside the shared execution gate, regardless of origin: UI, API, MCP, agent, job, provider adapter or internal tool. The execution gate is a kernel capability. Interfaces call the gate; they do not implement their own mutation path.

### Release boundary

- R0/R1/R2/R3: **no Class C operations against customer environments**. Assessment is read-only against customer sources (Class A collection with read-only provider credentials). Workspace decisions are Class B.
- R4: Class C operations are introduced only with provider adapters, approval-bound execution, recovery handling and independently verifiable evidence.
- R1 validates the execution-gate lifecycle against a **deterministic test adapter**. The test adapter cannot be substituted with a production provider adapter, and R1 components cannot obtain execution credentials. R1 does not move gated customer-environment writes forward.

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
