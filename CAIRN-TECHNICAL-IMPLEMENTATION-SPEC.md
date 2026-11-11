# CAIRN Technical Implementation Specification

**Version:** 0.6 (frozen R0 baseline: compensation contract, outbox failure semantics, adversarial RLS)
**Prepared:** 9 November 2026; amended 10 and 11 November 2026
**Source documents:** `Cloud_Modernization_Platform_PRD.docx` v1.0; `CLOUD-ARCHITECTURE-PATTERNS.md`
**Product stake in the ground:** shared kernel first; **CAIRN Assess** and **CAIRN Modernize** are the first customer-facing products; one canonical estate model and one mapping registry drive assessment, design, migration planning and generated infrastructure.

---

## 0. Document control

| Item | Value |
|---|---|
| Status | Draft for engineering review; all ADRs accepted 9 November 2026, amended 10 and 11 November 2026; frozen as the R0 architecture baseline 11 November 2026 |
| Revision | 0.2, 9 November 2026: greenfield decision, no code reuse (ADR-017), sections 16-19 re-baselined |
| Revision | 0.3, 9 November 2026: accepted decisions baseline; solo maintainer, public repository, Apache-2.0, Gemini only, full model up front |
| Revision | 0.4, 9 November 2026: architecture review; operation classes; no Class C before R4; immutable revisions; tenancy, idempotency and evidence amendments |
| Revision | 0.5, 10 November 2026: recovery-aware mutation classes; rollback and compensation preconditions; idempotency scope; application-role RLS conformance tests |
| Revision | 0.6, 11 November 2026: formal compensation contract; outbox failure-mode semantics; adversarial RLS catalogue; R0 acceptance gate locked as a hard release condition |
| Baseline | Frozen at v0.6 on 11 November 2026 as the R0 architecture baseline. Further changes require an ADR and a version bump; pre-implementation amendment rounds are closed |
| Audience | Platform engineering, architecture, security, product, delivery |
| Traceability | Requirements reference PRD IDs (FR-xxx, NFR-xxx) |
| Change rule | Any change to a contract in sections 7-13 requires an ADR and a version bump |
| Naming | Product = CAIRN. Kernel = CAIRN Kernel. Modules = CAIRN Assess, CAIRN Design, CAIRN Modernize, CAIRN Operate, CAIRN Govern |

### 0.1 What this document is

This is the implementation-level bridge between the PRD and code. It fixes the things that are expensive to change later:

1. Repository and package boundaries.
2. The canonical estate model and the mapping registry.
3. Database schemas and ownership.
4. API, MCP, A2A and event contracts.
5. Deployment topology and environment model.
6. Security, tenancy, evidence and conformance mechanisms.
7. An ordered engineering backlog with acceptance criteria.

### 0.2 What this document is not

- It is not a final OpenAPI file, Terraform plan or migration script. Those are generated from this specification during R0.
- It does not reopen settled decisions silently. Section 19 records the accepted outcomes, and any change requires a superseding ADR.
- It does not assume code reuse. CAIRN is greenfield: the 43 reference repositories are design evidence only (ADR-017, section 17).

---

## 1. Scope and traceability

This specification assumes a greenfield build. No source code, assets or configuration from the 43 reference repositories is reused; they are design evidence only (ADR-017). Any statement in earlier documents that implies lifting code is superseded.

### 1.1 Release scope this specification enables

The PRD boundary is preserved: the first usable release must not mutate customer environments.

| Release | Name | Exit capability | Customer environment mutation |
|---|---|---|---|
| R0 | Platform foundation | CI, conformance, contracts, deployable skeleton, tenancy/evidence foundations | None |
| R1 | CAIRN Assess | Read-only assessment, workspace decisions, evidence, and deterministic execution-gate validation | None |
| R2 | CAIRN Design | One canonical model produces diagram, mappings, plan and IaC preview | None |
| R3 | CAIRN Modernize preparation | Transformation preparation, validation, preview and execution-package generation | None; no customer apply |
| R4 | Class C execution | Provider adapters, approval-bound execution, rollback and independently verifiable evidence | Controlled Class C only, through the kernel execution gate |
| R5 | CAIRN Operate | FinOps, AI governance, resilience and vertical packs | Controlled Class C where explicitly approved |

### 1.2 Traceability matrix

| PRD requirement group | Spec section | Release |
|---|---|---|
| FR-001 to FR-006 tenancy and projects | 7, 9, 10, 13 | R0/R1 |
| FR-010 to FR-017 ingestion | 7, 9, 10, 12 | R1 |
| FR-020 to FR-026 canonical estate and 6R | 7, 9, 10 | R1 |
| FR-030 to FR-036 posture and compliance | 8, 9, 10 | R1 |
| FR-040 to FR-046 cost and TCO | 8, 9, 10 | R1 (read-only), R5 (remediation) |
| FR-050 to FR-056 mapping registry | 8, 9, 10 | R1 seed, R2 service |
| FR-060 to FR-066 architecture synthesis | 8, 10, 12 | R2 |
| FR-070 to FR-077 modernization | 6, 8, 10, 12 | R3/R4 |
| FR-080 to FR-086 approval and execution | 12, 13 | R1 deterministic gate validation; R4 live Class C execution |
| FR-090 to FR-096 evidence and provenance | 8, 9, 13 | R0 baseline, R1 full |
| FR-100 to FR-107 AI and agentic | 6, 11, 13 | R0 kernel, R5 control plane |
| FR-110 to FR-116 console | 10, 14 | R1/R2 |
| NFR-001 to NFR-014 | 14, 15, 16 | All |

---

## 2. Architecture decisions adopted for this specification

These architecture decisions are **accepted** as of 9 November 2026. Full records, including context, consequences, alternatives and the decision log, live in `docs/adr/`.

| ADR | Decision | Rationale | Consequence if rejected |
|---|---|---|---|
| ADR-001 | Monorepo with independently deployable apps, public at `solara-associates/cairn` | Shared kernel changes and cross-module conformance are the main integration risk | Package registry and versioning overhead |
| ADR-002 | Clean/Hexagonal plus DDD, enforced by `import-linter` | Proven across the source portfolio | Boundaries drift; reintroduces fragmentation |
| ADR-003 | One canonical estate model, versioned; full model defined up front | Single source for assessment, design, plan and IaC | Duplicate models and inconsistent outputs |
| ADR-004 | One mapping registry, immutable releases; Allan Smeyatsky approves | Prevents fabricated or divergent service mappings | Approximate mappings become invisible |
| ADR-005 | GCP-first adapters with provider-neutral contracts | Controls first-release cost; keeps portability | Slower multi-cloud parity |
| ADR-006 | Python 3.12 for domain/application, Rust for transformation and measured hot paths, from R0 | Best fit for team skills and component needs | Rewrite cost or performance risk |
| ADR-007 | Cloud SQL PostgreSQL (europe-west2) for OLTP; BigQuery for analytics | Clear source-of-truth boundaries | Duplicate truth or poor analytics |
| ADR-008 | Canonical signed JSON plus human-readable report; unique chain head; audit-before-effect; CAIRN-held keys | Trust differentiator; PRD FR-084/FR-092 | Weaker audit story; retrofitting is costly |
| ADR-009 | Immutable revisions; approvals and executions are bound to exact revision rows | Prevents "approve once, apply anything" | Compliance failure |
| ADR-010 | Operation classes; Class C customer mutations only through the kernel gate, and no Class C before R4 | Preserves PRD boundary and makes governance non-bypassable | Bypassable or premature mutation |
| ADR-011 | MCP per bounded context; A2A bridge for agent hosts, internal until R5 | Matches source portfolio; host interoperability | Ad-hoc integrations |
| ADR-012 | Tenant isolation is a kernel contract, with forced database RLS and composite scope keys | Defense in depth for isolation | Cross-tenant exposure risk |
| ADR-013 | SaaS-only multi-tenant product; no supported customer-deployed edition; mid-market first | Lowest first-release operational surface | Identity, tenancy, billing and support redesign later |
| ADR-014 | Gemini-only provider behind ModelPort; no customer BYO key | Controls cost and parity testing scope | Provider lock-in or limited choice |
| ADR-015 | Build one transformation engine clean-room in Rust; Terraform and Python first | Removes divergent engines without inheriting code or licence risk | Multiple engines or implicit reuse |
| ADR-016 | United Kingdom launch jurisdiction pack, versioned like a mapping release | Bounds residency and control scope at launch | Additional packs delay later releases |
| ADR-017 | Greenfield clean-room implementation; no code reuse from the reference repositories | Removes licence and provenance ambiguity; forces clean contracts | Reuse assumption returns and contaminates provenance |
| ADR-018 | Open-source distribution under Apache-2.0 with professional services revenue | Adoption without a pilot customer; code is inspectable | Proprietary or open-core model |

---

## 3. System context and component view

### 3.1 Context

```
                         ┌──────────────────────────────────────────────┐
                         │                  CAIRN                       │
                         │                                              │
 Customer cloud  ──────► │  Assess ──► Design ──► Modernize ──► Operate │
 (read-only APIs,        │     │          │            │            │    │
  exports)               │     └──────────┴────────────┴────────────┘    │
                         │        Canonical Estate Model + Mapping       │
                         │        Registry + Evidence + Policy           │
                         └───────────────┬──────────────────────────────┘
                                         │
        Customer IdP ◄───────────────────┼───────────────────► SIEM / ITSM
        Git / CI    ◄───────────────────┼───────────────────► Model providers
        Terraform   ◄───────────────────┘
```

### 3.2 Logical components

| Component | Type | Responsibility | Release |
|---|---|---|---|
| `api` | Cloud Run service | Control-plane REST, auth, tenant context, orchestration entry | R0 |
| `worker` | Cloud Run service/worker | Async ingestion, assessment, design, transformation jobs | R1 |
| `scheduler` | Cloud Run job / Scheduler | Scheduled collection, drift, retention | R1/R4 |
| `mcp-gateway` | Cloud Run service | MCP registry and bounded-context servers | R5 (internal earlier) |
| `console` | Cloud Run static/SSR | React delivery console | R1 |
| `cli` | Local binary | Air-gapped and engineering workflows | R3 |
| `transform-core` | Rust library + CLI | Deterministic parsing, detection, diff, validation | R3 |
| `postgres` | Cloud SQL | OLTP, registry metadata, jobs, approvals | R0 |
| `bigquery` | BigQuery | Raw/curated/consumption analytics, cost facts | R1 |
| `gcs` | Cloud Storage | Raw uploads, artefacts, evidence packages | R0 |
| `pubsub` | Pub/Sub | Domain and job events | R1 |
| `secretmanager` / `kms` | GCP | Secrets and evidence signing keys | R0 |
| `artifactregistry` | GCP | Signed images | R0 |

### 3.3 Why this shape

- **Assess and design are separate from execution.** The assessment and design planes build no applier and hold no execution credentials, so a code defect cannot mutate a customer estate. Class C mutation exists only from R4, in the isolated execution module, and only through the kernel gate with policy, immutable revision approval and evidence (ADR-010).
- **The canonical model and registry are services, not libraries copied into each module.** This is what makes CAIRN a platform.
- **Async by default for anything touching a provider.** Long scans, ingestion and transformations run as resumable jobs; the API returns `202` with an operation resource.

---

## 4. Monorepo structure

### 4.1 Top-level tree

```
cairn/
├── README.md
├── LICENSE
├── Makefile
├── pyproject.toml                  # uv workspace root
├── uv.lock
├── Cargo.toml                      # Rust workspace root
├── pnpm-workspace.yaml
├── package.json
├── .importlinter
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── conformance.yml
│       ├── security.yml
│       ├── deploy-dev.yml
│       ├── deploy-staging.yml
│       └── deploy-prod.yml
├── docs/
│   ├── adr/
│   ├── specs/
│   ├── runbooks/
│   └── diagrams/
├── packages/
│   ├── kernel/
│   │   ├── hex/
│   │   ├── tenancy/
│   │   ├── config/
│   │   ├── errors/
│   │   ├── evidence/
│   │   ├── observability/
│   │   ├── security/
│   │   ├── execution-gate/          # operation/mutation classification and Class C gate
│   │   ├── conformance/
│   │   └── testing/
│   ├── contracts/
│   │   ├── estate/
│   │   ├── mapping/
│   │   ├── events/
│   │   └── api/
│   ├── kits/
│   │   ├── mcp/
│   │   ├── a2a/
│   │   └── loop/
│   ├── adapters/
│   │   ├── provider-core/
│   │   ├── provider-gcp/
│   │   ├── provider-aws/
│   │   ├── provider-azure/
│   │   ├── scanners/
│   │   ├── persistence-postgres/
│   │   ├── persistence-bigquery/
│   │   ├── model/
│   │   └── evidence-kms/
│   ├── modules/
│   │   ├── tenancy/
│   │   ├── projects/
│   │   ├── connections/
│   │   ├── ingestion/
│   │   ├── estate/
│   │   ├── posture/
│   │   ├── finops/
│   │   ├── mappings/
│   │   ├── design/
│   │   ├── planning/
│   │   ├── transformation/
│   │   ├── approvals/
│   │   ├── execution/               # R4 Class C orchestration
│   │   ├── evidence-service/
│   │   └── reporting/
│   └── transform-core/             # Rust crates: parser, detector, patcher, validator
├── apps/
│   ├── api/
│   ├── worker/
│   ├── scheduler/
│   ├── mcp-gateway/
│   ├── console/
│   └── cli/
├── patterns/                       # versioned pattern YAML
├── mappings/                       # seed service maps, region catalogues, jurisdiction packs
├── infra/
│   ├── terraform/
│   │   ├── modules/
│   │   └── envs/
│   ├── helm/cairn/
│   └── pipelines/
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   └── security/
└── tools/
    ├── conformance/
    ├── seed/
    └── scripts/
```

### 4.2 Package responsibility and ownership

| Package | Owns | May import | Must not import |
|---|---|---|---|
| `kernel/hex` | Base entity, value object, port, use case, DI, settings | stdlib, Pydantic | any adapter, any app, any cloud SDK |
| `kernel/tenancy` | `TenantId`, tenant context, isolation helpers | `kernel/hex` | adapters, apps |
| `kernel/evidence` | Evidence envelope, hashing, signing interface | `kernel/hex` | cloud SDK except through port |
| `kernel/observability` | OTel setup, RED middleware, AI-call logger | `kernel/hex`, OTel SDK | module internals |
| `kernel/security` | AuthZ policies, redaction, secret resolver ports | `kernel/hex` | apps |
| `kernel/conformance` | Rule registry, rule-to-check runner | stdlib, tooling | domain modules |
| `contracts/estate` | Canonical estate schemas | stdlib, Pydantic | infrastructure |
| `contracts/mapping` | Mapping and pattern schemas | stdlib, Pydantic | infrastructure |
| `contracts/events` | Event envelope and payload schemas | stdlib, Pydantic | infrastructure |
| `contracts/api` | Shared API DTOs and error model | stdlib, Pydantic | infrastructure |
| `kits/mcp` | MCP transport, auth, registration, audit | kernel, contracts | module internals |
| `kits/a2a` | A2A schemas, cards, bridge | kernel, contracts | module internals |
| `kits/loop` | Observe/Decide/Act runtime | kernel, contracts | module internals |
| `adapters/provider-*` | Provider inventory, billing, posture adapters | provider-core, kernel | modules, apps |
| `adapters/scanners` | Prowler, Steampipe, OPA adapters | provider-core, kernel | modules, apps |
| `adapters/persistence-*` | Repositories behind ports | kernel, contracts | modules' domain internals |
| `adapters/model` | ModelPort adapters (Gemini, Bedrock, Azure OpenAI, fake) | kernel, contracts | modules |
| `modules/*` | Domain, application, presentation for one bounded context | kernel, contracts, kits, own adapters | other modules' infrastructure |
| `apps/*` | Composition root, deployment entrypoints | all modules, adapters | none (top of graph) |
| `transform-core` | Deterministic parsing, detection, diff, validation | Rust stdlib, Tree-sitter | Python modules except via FFI boundary |

### 4.3 Enforced dependency contracts

`.importlinter` must encode at least:

```ini
[importlinter]
root_packages =
    cairn_kernel
    cairn_contracts
    cairn_modules
    cairn_adapters
    cairn_apps

[importlinter:contract:layers]
name = Kernel and contracts are leaves
type = forbidden
source_modules = cairn_kernel, cairn_contracts
forbidden_modules = cairn_modules, cairn_adapters, cairn_apps

[importlinter:contract:domain-purity]
name = Domain imports no adapters, frameworks or cloud SDKs
type = forbidden
source_modules = cairn_modules.*.domain
forbidden_modules =
    cairn_adapters
    cairn_apps
    google.cloud
    boto3
    azure
    fastapi
    sqlalchemy

[importlinter:contract:module-isolation]
name = Modules do not import each other's infrastructure
type = forbidden
source_modules = cairn_modules.estate
forbidden_modules = cairn_modules.finops.infrastructure, cairn_modules.posture.infrastructure
```

Each module repeats the module-isolation contract. Cross-module communication uses shared `contracts` DTOs or events, never direct infrastructure imports.

---

## 5. Shared kernel contracts

### 5.1 Core primitives

```python
# kernel/hex/primitives.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")

class OperationClass(str, Enum):
    READ = "READ"                 # Class A
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"  # Class B
    GOVERNED_ENV_MUTATION = "GOVERNED_ENV_MUTATION"  # Class C

class MutationClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    INTERNAL_MUTATION = "INTERNAL_MUTATION"
    REVERSIBLE_EXTERNAL_MUTATION = "REVERSIBLE_EXTERNAL_MUTATION"
    COMPENSATABLE_EXTERNAL_MUTATION = "COMPENSATABLE_EXTERNAL_MUTATION"
    IRREVERSIBLE_EXTERNAL_MUTATION = "IRREVERSIBLE_EXTERNAL_MUTATION"

OPERATION_CLASS_BY_MUTATION = {
    MutationClass.READ_ONLY: OperationClass.READ,
    MutationClass.INTERNAL_MUTATION: OperationClass.WORKSPACE_MUTATION,
    MutationClass.REVERSIBLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
    MutationClass.COMPENSATABLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
    MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
}

@dataclass(frozen=True, slots=True)
class TenantId:
    value: str

@dataclass(frozen=True, slots=True)
class ProjectId:
    value: str

@dataclass(frozen=True, slots=True)
class Fact(Generic[T]):
    value: T | None
    status: str                 # OBSERVED | INFERRED | CONFIRMED | APPROXIMATE | UNAVAILABLE | UNVERIFIED
    source: str
    observed_at: datetime | None
    ingested_at: datetime
    confidence: float | None
    mapping_version: str | None
    provenance_ref: str

@dataclass(frozen=True, slots=True)
class CommandContext:
    tenant_id: TenantId
    project_id: ProjectId | None
    actor_id: str
    actor_roles: tuple[str, ...]
    correlation_id: str
    operation_class: OperationClass
    mutation_class: MutationClass
    idempotency_key: str | None = None
    source: str = "api"         # console | api | mcp | agent | job

class Port(Protocol):
    """Marker protocol for all outbound ports."""

class UnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

### 5.2 Mutation classification and compensation contract

Every command declares exactly one operation class and one mutation class. The two must agree; the kernel rejects a mismatch at construction time.

| Mutation class | Operation class | Gate requirement | Recovery precondition |
|---|---|---|---|
| `READ_ONLY` | A | None; normal authorization and sensitive-read audit | Not applicable |
| `INTERNAL_MUTATION` | B | Authorization, tenancy, idempotency and audit | Not applicable; no customer-environment effect |
| `REVERSIBLE_EXTERNAL_MUTATION` | C | Full gate, risk-tiered approval, audit-before-effect and evidence | Rollback action identified, scoped and validated **before** authorization |
| `COMPENSATABLE_EXTERNAL_MUTATION` | C | Full gate plus higher risk tier and explicit compensation review | Compensating action and its trigger identified, scoped and validated **before** authorization |
| `IRREVERSIBLE_EXTERNAL_MUTATION` | C | Full gate plus highest approval tier, explicit risk acceptance, blast-radius declaration and preflight/dry-run where supported | No rollback promise; execution is refused unless the residual risk is explicitly accepted before authorization |

Rules:
- Classification is part of the command contract, not an implementation detail. Changing it requires a new revision and approval.
- The execution gate derives required approval roles, risk tier, evidence obligations and recovery handling from the mutation class.
- The undo or compensating action is defined before execution, never after. A missing or invalid recovery reference blocks authorization.
- `IRREVERSIBLE_EXTERNAL_MUTATION` must not be presented as reversible, and an execution in that class cannot transition to `ROLLED_BACK`.
- The approval and execution records store the classification and recovery strategy. Execution must match the approved classification exactly.

### 5.3 Compensation contract

Every external mutation declares a formal compensation contract before it can be proposed for approval. The contract is an immutable artifact referenced by `recovery_plan_ref` (or `risk_acceptance_ref` for irreversible mutations) and is validated against the mutation class at proposal time. A missing or incomplete element blocks authorization.

| Element | Reversible | Compensatable | Irreversible |
|---|---|---|---|
| Strategy | `ROLLBACK` | `COMPENSATE` | `ACCEPT_IRREVERSIBLE` |
| Preconditions | Rollback action, scope, target state and post-rollback validation checks | Compensating action, trigger condition, scope and post-compensation validation checks | Blast-radius declaration, preflight/dry-run results where supported, residual-risk statement |
| Authority | Approval tier for the mutation; rollback executes in the execution plane within the approved scope | Higher approval tier; the trigger authority and the execution authority are named roles | Highest approval tier; risk acceptance is signed by the accountable approver |
| Evidence | Before/after state capture and rollback outcome evidence | Trigger evidence, before/after state capture and compensation outcome evidence | Preflight evidence, signed risk acceptance and execution outcome evidence |
| Failure handling | Rollback failure escalates to an incident with reconciliation; the execution is `FAILED`, never silently `SUCCEEDED` | Compensation or trigger failure escalates to an incident; the original effect remains with recorded residual state | No recovery promise exists; failure escalates to an incident against the declared blast radius |

Contract rules:
- The contract is bound to the immutable revision and approval; changing it requires a new revision and re-approval.
- Only the execution plane may execute a rollback or compensation, and only within the scope the approval names.
- Recovery failure is an incident, never a silent success, and is reconciled against the recorded execution state.
- A rollback or compensation executes under the authority pre-delegated by the approved contract. Any deviation from the declared plan requires a new revision and approval.

### 5.4 Required port catalogue (v0)

| Port | Owner module | v0 adapters |
|---|---|---|
| `ProjectRepository` | projects | Postgres |
| `ProviderConnectionRepository` | connections | Postgres |
| `InventorySourcePort` | ingestion | GCP, file upload, fake |
| `BillingSourcePort` | ingestion/finops | GCP, file upload, fake |
| `PostureScannerPort` | posture | Prowler, Steampipe, OPA, fake |
| `EstateRepository` | estate | Postgres, fake |
| `FindingRepository` | posture | Postgres, fake |
| `CostRepository` | finops | BigQuery, Postgres summary, fake |
| `MappingRepository` | mappings | Postgres, fake |
| `PatternRepository` | design | Postgres/YAML, fake |
| `DiagramRendererPort` | design | drawio emitter, fake |
| `IaCGeneratorPort` | planning | Terraform emitter, fake |
| `RepositorySourcePort` | transformation | Git/upload, fake |
| `TransformationPort` | transformation | Rust core, fake |
| `ValidationPort` | transformation | test/static runner, fake |
| `RevisionRepository` | approvals/planning/design | Postgres append-only, fake |
| `ApprovalRepository` | approvals | Postgres, fake |
| `ExecutionGatePort` | execution | Kernel gate + deterministic test adapter in R1; no production provider adapter before R4 |
| `ProviderExecutionPort` | execution | **None before R4**; production adapters only in R4 behind `ExecutionGatePort` |
| `EvidenceStore` | evidence-service | Postgres + GCS + KMS, fake |
| `AuditSink` | kernel/security | Postgres append-only, fake |
| `IdempotencyStore` | kernel/security | Postgres, fake |
| `ModelPort` | adapters/model | Gemini, fake |
| `EventPublisher` | kernel | Pub/Sub, in-memory |
| `Clock`, `IdGenerator` | kernel | system, fixed test |

Before R4, `modules/execution` and any production `ProviderExecutionPort` adapter are absent from the deployable. The deterministic test adapter lives in test code, is selected only by the test harness, and cannot be enabled by runtime configuration.

### 5.5 Conformance harness rule map (v0)

| Rule | Check | Failure mode |
|---|---|---|
| R-ARCH-01 | `importlinter` all contracts kept | CI fail |
| R-ARCH-02 | Domain imports no SDK/framework | CI fail |
| R-TENANT-01 | Every repository query enforces tenant context | Unit + adversarial test |
| R-TENANT-02 | Every tenant-owned and project-owned table has forced RLS and required policies; app roles lack `BYPASSRLS`; tests run under the app role | Migration + role-level test |
| R-AUDIT-01 | Class B/C mutations append audit trail; Class C appends before external effect | Integration test |
| R-EVID-01 | Evidence tamper/fork is detected | Tamper/fork test |
| R-AI-01 | Model output schema-validated | Eval test |
| R-AI-02 | Model cannot approve/execute | Policy test |
| R-MAP-01 | Approximate/unavailable never rendered as exact | Resolver test |
| R-REV-01 | Approvals/executions bind to immutable revision rows and exact hashes | DB constraint + integration test |
| R-GATE-01 | No Class C path outside `ExecutionGatePort`; no production provider adapter before R4 | Static + integration test |
| R-MUT-01 | Every command declares a mutation class; operation and mutation classes agree; external classes have a validated recovery strategy before authorization | Contract + gate test |
| R-MUT-02 | Every external mutation has a complete compensation contract (strategy, preconditions, authority, evidence, failure handling) matching its mutation class; an incomplete contract blocks authorization | Contract + gate test |
| R-IDEM-01 | Class B and Class C mutations require tenant/project/operation/key scoped idempotency, canonical request hashing, replay/conflict handling and expiry | Contract test |
| R-OUTBOX-01 | Outbox failure semantics proven by failure injection: crash after commit before dispatch loses nothing; duplicate delivery is idempotent; consumer crash after effect before acknowledgement does not repeat the effect; dead-letter replay preserves ordering and runbook; replay cannot cross tenant scope | Failure-injection test |
| R-TENANT-03 | Adversarial RLS under the application role: missing tenant context fails closed; pooled connections cannot leak tenant context; tenant-context change attempts are rejected and audited | Adversarial test |
| R-COV-01 | Coverage floor per critical package | CI fail |
| R-SEC-01 | No critical/high findings; high needs risk acceptance | CI gate |
| R-SEC-02 | SBOM and image signature present | CI gate |
| R-CONF-01 | Every mandatory rule maps to a check | Harness self-test |

---

## 6. Canonical estate model

The model is provider-neutral, immutable, versioned and provenance-bearing. It lives in `packages/contracts/estate`.

### 6.1 Core entities

```python
# contracts/estate/model.py (illustrative)
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class FactStatus(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"

class Outcome(str, Enum):
    PASS = "PASS"
    ACCEPTED_EXCEPTION = "ACCEPTED_EXCEPTION"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"

class Disposition(str, Enum):
    REHOST = "REHOST"
    REPLATFORM = "REPLATFORM"
    REFACTOR = "REFACTOR"
    REPURCHASE = "REPURCHASE"
    RETIRE = "RETIRE"
    RETAIN = "RETAIN"

@dataclass(frozen=True, slots=True)
class Provenance:
    source_system: str
    source_id: str
    source_version: str | None
    observed_at: datetime | None
    ingested_at: datetime
    parser_version: str
    ingest_run_id: str
    raw_ref: str

@dataclass(frozen=True, slots=True)
class Resource:
    resource_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    region: str
    service: str
    resource_type: str
    native_id: str
    name: str | None
    tags: dict[str, str]
    facts: dict[str, "FactValue"]
    provenance: tuple[Provenance, ...]
    status: FactStatus

@dataclass(frozen=True, slots=True)
class Workload:
    workload_id: str
    tenant_id: str
    project_id: str
    name: str
    environment: str
    owner: str | None
    business_context: str | None
    resource_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    facts: dict[str, "FactValue"]
    disposition: Disposition | None
    disposition_confidence: float | None

@dataclass(frozen=True, slots=True)
class Dependency:
    dependency_id: str
    tenant_id: str
    project_id: str
    source_workload_id: str
    target_workload_id: str
    kind: str                  # NETWORK | DATA | IDENTITY | API | SCHEDULE | OTHER
    direction: str             # ONE_WAY | BIDIRECTIONAL
    status: FactStatus
    provenance: tuple[Provenance, ...]

@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    tenant_id: str
    project_id: str
    control_id: str
    control_version: str
    severity: str
    affected_resource_id: str | None
    affected_workload_id: str | None
    outcome: Outcome
    evidence_refs: tuple[str, ...]
    remediation: str | None
    source: str
    status: str

@dataclass(frozen=True, slots=True)
class CostRecord:
    cost_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    service: str
    region: str
    period_start: datetime
    period_end: datetime
    currency: str
    amount_minor: int
    tags: dict[str, str]
    provenance: Provenance

@dataclass(frozen=True, slots=True)
class DispositionDecision:
    decision_id: str
    tenant_id: str
    project_id: str
    workload_id: str
    disposition: Disposition
    rationale: str
    confidence: float
    status: str                # PROPOSED | ACCEPTED | AMENDED | REJECTED
    decided_by: str | None
    decided_at: datetime | None

@dataclass(frozen=True, slots=True)
class MappingResolution:
    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    equivalence: str           # EXACT | APPROXIMATE | UNAVAILABLE | UNSUPPORTED
    caveat: str | None
    region: str | None
    mapping_version: str
```

### 6.2 Model rules

1. A `FactValue` is never `None` without a `status` explaining why. Missing is `UNVERIFIED`, not zero.
2. Conflicting observations are stored as separate facts, both retrievable. Derived values reference the observation set used.
3. Every derived entity (workload, disposition, plan) stores the model and mapping versions used.
4. No cloud SDK types enter this package.
5. Additive changes only within a major model version; breaking changes require a new version and a migration.

### 6.3 Status semantics

| Status | Allowed in | Rule |
|---|---|---|
| `OBSERVED` | facts | Must have provenance and observation time |
| `INFERRED` | facts | Must state inference rule/version |
| `CONFIRMED` | facts | Must have confirming user and time |
| `APPROXIMATE` | mappings, facts | Must display caveat; material cases require review |
| `UNAVAILABLE` | mappings, capabilities | Must not be substituted |
| `UNVERIFIED` | facts, outcomes | Must display coverage gap; never treated as pass |

---

## 7. Mapping registry

### 7.1 Purpose

The registry is the shared source for service equivalence, region availability, jurisdiction rules and pattern definitions. Assessment, TCO, design, diagrams and transformation all resolve through it.

### 7.2 Schema

```yaml
# mappings/service-map.yaml (illustrative)
version: "2026.11.1"
released_at: "2026-11-09T00:00:00Z"
status: published
entries:
  - id: s3-to-gcs
    source_provider: aws
    source_service: s3
    target_provider: gcp
    target_service: cloud-storage
    equivalence: APPROXIMATE
    caveat: "Object storage semantics differ for consistency and lifecycle transitions"
    regions: [europe-west2, us-central1, asia-south1]
    evidence: "cloudshift pattern catalogue; GCP storage docs"
    effective_from: "2026-11-01"
  - id: dynamodb-to-bigtable
    source_provider: aws
    source_service: dynamodb
    target_provider: gcp
    target_service: bigtable
    equivalence: APPROXIMATE
    caveat: "Access patterns and secondary indexes require redesign"
  - id: step-functions-to-workflows
    source_provider: aws
    source_service: step-functions
    target_provider: gcp
    target_service: workflows
    equivalence: APPROXIMATE
  - id: sagemaker-to-vertex
    source_provider: aws
    source_service: sagemaker
    target_provider: gcp
    target_service: vertex-ai
    equivalence: APPROXIMATE
  - id: azure-openai-to-vertex
    source_provider: azure
    source_service: openai
    target_provider: gcp
    target_service: vertex-ai-gemini
    equivalence: APPROXIMATE
    caveat: "Model behaviour and API contracts differ; requires prompt and eval migration"
  - id: s3-object-lock-to-gcs-retention
    source_provider: aws
    source_service: s3-object-lock
    target_provider: gcp
    target_service: gcs-retention-policy
    equivalence: UNAVAILABLE
    caveat: "No exact equivalent for legal-hold semantics in the target registry version"
```

### 7.3 Registry rules

- Published versions are immutable. Corrections create a new version.
- Every resolution returns `equivalence`, `caveat`, `regions`, `mapping_version` and `evidence`.
- `UNAVAILABLE` fails generation with an explanation; it never invents a substitute.
- Region availability and jurisdiction packs are separate versioned files.
- The registry is read by assessment, TCO, design, diagram and transformation through one `MappingRepository` port.
- Changes follow propose, review, approve, publish, retire, with an audit record.

### 7.4 Seed datasets for R1/R2

| Dataset | Source repos | Minimum seed |
|---|---|---|
| Service map | `cloudshift` (134 patterns), `infracc`, `mlops-aws`, `Meridian` | Top 40 services per provider pair used in pilot |
| Region catalogue | `tda-uk-accelerator`, `nelc` | UK, GCC/MENA, India, EU, US |
| Jurisdiction packs | `taa`, `temenos_ldm_accelerator`, `fhir-omop`, `dpdp` | UK, Saudi, UAE, India (initial launch pack chosen in ADR) |
| Pattern catalogue | `drawio-gen` | 8-12 patterns: web app, data platform, AI app, landing zone, event-driven, analytics, migration, resilient multi-region |

---

## 8. Data architecture

### 8.1 Tenancy classification

Every persisted, emitted and stored entity is classified before implementation.

| Class | Meaning | Examples |
|---|---|---|
| Global | Not tenant-owned; CAIRN-operated control data | published global mapping releases, control catalogue metadata, platform config |
| Tenant-owned | Scoped to one tenant; not project-specific | tenant, app_user, tenant-wide role grants, tenant settings, tenant mapping proposals, ledger entries with optional project |
| Project-owned | Scoped to one tenant and one project | projects, connections, ingestion, estate facts, findings, costs, designs, plans, approvals, executions, evidence, artifacts, model telemetry |

The same classification applies to APIs, MCP tools/resources, events, Pub/Sub attributes, object-storage paths, worker jobs and service identities. Tenant/project scope comes from authenticated server-side context and is never accepted from untrusted request parameters.

### 8.2 Source-of-truth boundaries

| Data class | Store | Reason |
|---|---|---|
| Tenants, users, projects, connections metadata | PostgreSQL | Transactional, audited, relational |
| Canonical estate facts, findings, costs summary | PostgreSQL | OLTP plus tenant/project isolation |
| Raw observations, high-volume facts | GCS raw + BigQuery raw | Volume, replay, analytics |
| Cost line items | BigQuery | Scale and query patterns |
| Global published mappings | PostgreSQL + published export in GCS | Immutable global releases |
| Tenant mapping proposals | PostgreSQL | Tenant-scoped review; no global publish authority |
| Revisions, approvals, executions, idempotency, outbox, jobs, evidence index | PostgreSQL | Transactional state machines, dispatch and audit ordering |
| Evidence packages | GCS immutable + PostgreSQL index | Tamper-evident storage |
| Cache (mapping resolution, sessions) | Redis/Memorystore | Latency |
| Agent/session state | PostgreSQL | Avoid duplicate truth; Firestore only if realtime UI requires |

### 8.3 PostgreSQL schema (core DDL)

Tenant-owned and project-owned tables carry `tenant_id`; project-owned tables also carry `project_id`. Every tenant-owned and project-owned table uses `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. `app.tenant_id` and, where applicable, `app.project_id` are set per transaction from authenticated server-side context only.

The DDL is normative for shape and constraints. Migrations must add composite foreign keys, uniqueness constraints, and a test that enumerates every tenant-owned and project-owned table for RLS coverage.

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Tenancy
CREATE TABLE tenant (
  tenant_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name             text NOT NULL,
  status           text NOT NULL DEFAULT 'ACTIVE',
  retention_days   integer NOT NULL DEFAULT 365,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
  user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  subject          text NOT NULL,
  email            text,
  status           text NOT NULL DEFAULT 'ACTIVE',
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, subject),
  UNIQUE (tenant_id, user_id)
);

CREATE TABLE project (
  project_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  customer_name    text NOT NULL,
  name             text NOT NULL,
  scope            text,
  providers        text[] NOT NULL DEFAULT '{}',
  regions          text[] NOT NULL DEFAULT '{}',
  assessment_start date,
  assessment_end   date,
  selected_modules text[] NOT NULL DEFAULT '{}',
  retention_days   integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, project_id)
);

CREATE TABLE role_grant (
  grant_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  user_id          uuid NOT NULL,
  project_id       uuid,
  role             text NOT NULL CHECK (role IN ('TENANT_ADMIN','PROJECT_OWNER','ARCHITECT','ENGINEER','REVIEWER','AUDITOR','VIEWER')),
  granted_by       uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app_user(tenant_id, user_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  UNIQUE NULLS NOT DISTINCT (tenant_id, user_id, project_id)
);

-- Connections and ingestion
CREATE TABLE provider_connection (
  connection_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  provider         text NOT NULL CHECK (provider IN ('gcp','aws','azure')),
  account_ref      text NOT NULL,
  auth_ref         text NOT NULL,          -- secret reference only, never plaintext
  scopes           text[] NOT NULL DEFAULT '{}',
  status           text NOT NULL DEFAULT 'PENDING',
  last_validated_at timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE TABLE ingestion_run (
  run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  source_kind      text NOT NULL,          -- INVENTORY | BILLING | ESTATE_EXPORT | SECURITY
  source_system    text NOT NULL,
  parser_version   text NOT NULL,
  scope            jsonb NOT NULL,
  status           text NOT NULL DEFAULT 'QUEUED',
  started_at       timestamptz,
  finished_at      timestamptz,
  coverage         jsonb NOT NULL DEFAULT '{}',
  error_summary    jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, project_id, run_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE TABLE source_observation (
  observation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  run_id           uuid NOT NULL,
  source_system    text NOT NULL,
  source_id        text NOT NULL,
  source_version   text,
  observed_at      timestamptz,
  ingested_at      timestamptz NOT NULL DEFAULT now(),
  raw_ref          text NOT NULL,
  payload_hash     text NOT NULL,
  status           text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, run_id) REFERENCES ingestion_run(tenant_id, project_id, run_id)
);

-- Canonical estate
CREATE TABLE workload (
  workload_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  name             text NOT NULL,
  environment      text,
  owner            text,
  business_context text,
  status           text NOT NULL DEFAULT 'UNVERIFIED',
  model_version    text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE resource (
  resource_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  workload_id      uuid REFERENCES workload(workload_id),
  provider         text NOT NULL,
  account_id       text NOT NULL,
  region           text,
  service          text NOT NULL,
  resource_type    text NOT NULL,
  native_id        text NOT NULL,
  name             text,
  tags             jsonb NOT NULL DEFAULT '{}',
  facts            jsonb NOT NULL DEFAULT '{}',
  status           text NOT NULL,
  provenance_refs  uuid[] NOT NULL DEFAULT '{}',
  model_version    text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE estate_fact (
  fact_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  entity_kind      text NOT NULL,          -- RESOURCE | WORKLOAD | DEPENDENCY
  entity_id        uuid NOT NULL,
  fact_key         text NOT NULL,
  fact_value      jsonb,
  status           text NOT NULL,
  source_system    text NOT NULL,
  observed_at      timestamptz,
  ingested_at      timestamptz NOT NULL,
  confidence       numeric(5,4),
  mapping_version  text,
  provenance_ref   uuid NOT NULL
);

CREATE TABLE dependency (
  dependency_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  source_workload_id uuid NOT NULL,
  target_workload_id uuid NOT NULL,
  kind             text NOT NULL,
  direction        text NOT NULL,
  status           text NOT NULL,
  provenance_refs  uuid[] NOT NULL DEFAULT '{}'
);

-- Posture
CREATE TABLE control (
  control_id       text NOT NULL,
  version          text NOT NULL,
  provider         text NOT NULL,
  pillar           text NOT NULL,
  title            text NOT NULL,
  description      text NOT NULL,
  severity_default text NOT NULL,
  PRIMARY KEY (control_id, version)
);

CREATE TABLE control_evaluation (
  evaluation_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  control_id       text NOT NULL,
  control_version  text NOT NULL,
  resource_id      uuid,
  outcome          text NOT NULL CHECK (outcome IN ('PASS','ACCEPTED_EXCEPTION','MISMATCH','UNVERIFIED')),
  evidence_refs    uuid[] NOT NULL DEFAULT '{}',
  evaluator        text NOT NULL,
  evaluated_at     timestamptz NOT NULL
);

CREATE TABLE finding (
  finding_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  control_id       text NOT NULL,
  control_version  text NOT NULL,
  severity         text NOT NULL,
  resource_id      uuid,
  workload_id      uuid,
  outcome          text NOT NULL,
  source           text NOT NULL,
  remediation      text,
  evidence_refs    uuid[] NOT NULL DEFAULT '{}',
  status           text NOT NULL DEFAULT 'OPEN',
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Cost
CREATE TABLE cost_baseline (
  baseline_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  period_start     date NOT NULL,
  period_end       date NOT NULL,
  currency         text NOT NULL,
  amount_minor     bigint NOT NULL,
  coverage         jsonb NOT NULL DEFAULT '{}',
  pricing_source   text NOT NULL,
  pricing_as_of    timestamptz NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tco_scenario (
  scenario_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  name             text NOT NULL,
  target_provider  text NOT NULL,
  assumptions      jsonb NOT NULL,
  pricing_as_of    timestamptz NOT NULL,
  mapping_version  text NOT NULL,
  result           jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Mapping registry (global published data; tenant-owned proposals are separate)
CREATE TABLE mapping_release (
  mapping_version  text PRIMARY KEY,
  scope            text NOT NULL DEFAULT 'GLOBAL' CHECK (scope = 'GLOBAL'),
  status           text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
  released_at      timestamptz,
  released_by      text NOT NULL,          -- platform-controlled identity
  content_hash     text NOT NULL,
  notes            text
);

CREATE TABLE service_mapping (
  mapping_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mapping_version  text NOT NULL REFERENCES mapping_release(mapping_version),
  source_provider  text NOT NULL,
  source_service   text NOT NULL,
  target_provider  text NOT NULL,
  target_service   text,
  equivalence      text NOT NULL CHECK (equivalence IN ('EXACT','APPROXIMATE','UNAVAILABLE','UNSUPPORTED')),
  caveat           text,
  regions          text[] NOT NULL DEFAULT '{}',
  evidence         text,
  effective_from   date,
  effective_to     date
);

CREATE TABLE mapping_proposal (
  proposal_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid,
  target_release   text REFERENCES mapping_release(mapping_version),
  proposed_by      uuid NOT NULL,
  status           text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SUBMITTED','ACCEPTED','REJECTED')),
  content          jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, proposed_by) REFERENCES app_user(tenant_id, user_id)
);

-- Disposition and planning
CREATE TABLE disposition (
  disposition_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  workload_id      uuid NOT NULL,
  disposition      text NOT NULL,
  rationale        text NOT NULL,
  confidence       numeric(5,4),
  status           text NOT NULL DEFAULT 'PROPOSED',
  decided_by       uuid,
  decided_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE migration_wave (
  wave_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  name             text NOT NULL,
  sequence         integer NOT NULL,
  constraints      jsonb NOT NULL DEFAULT '{}',
  status           text NOT NULL DEFAULT 'DRAFT'
);

-- Immutable revision-bearing subjects
CREATE TABLE subject_revision (
  revision_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid NOT NULL,
  subject_kind     text NOT NULL CHECK (subject_kind IN ('MIGRATION_PLAN','TARGET_DESIGN','TRANSFORMATION_PACKAGE','REMEDIATION_PACKAGE')),
  subject_id       uuid NOT NULL,
  revision_number  integer NOT NULL CHECK (revision_number > 0),
  content_hash     text NOT NULL,
  content_ref      text NOT NULL,
  mapping_version  text,
  model_version    text,
  pattern_version  text,
  policy_version   text,
  created_by       uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, subject_kind, subject_id, revision_number),
  UNIQUE (tenant_id, revision_id, content_hash),
  UNIQUE (tenant_id, project_id, revision_id, content_hash),
  UNIQUE (tenant_id, revision_id),
  UNIQUE (tenant_id, project_id, revision_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES app_user(tenant_id, user_id)
);

CREATE TABLE migration_plan (
  plan_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid NOT NULL,
  status           text NOT NULL DEFAULT 'DRAFT',
  current_revision_id uuid,
  created_by       uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, plan_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, current_revision_id) REFERENCES subject_revision(tenant_id, project_id, revision_id)
);

-- Design artefacts
CREATE TABLE target_architecture (
  architecture_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  pattern_id       text NOT NULL,
  pattern_version  text NOT NULL,
  target_provider  text NOT NULL,
  mapping_version  text NOT NULL,
  model_version    text NOT NULL,
  parameters       jsonb NOT NULL,
  content          jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE artifact (
  artifact_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  kind             text NOT NULL,          -- DIAGRAM | IAC | REPORT | DIFF | EVIDENCE
  content_ref      text NOT NULL,
  content_hash     text NOT NULL,
  metadata         jsonb NOT NULL DEFAULT '{}',
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Transformation
CREATE TABLE transformation_run (
  run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid NOT NULL,
  repository_ref   text NOT NULL,
  revision_ref     text NOT NULL,
  detector_version text NOT NULL,
  pattern_set_version text NOT NULL,
  status           text NOT NULL DEFAULT 'QUEUED',
  manifest         jsonb NOT NULL DEFAULT '{}',
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Approvals and execution (Class B approval; Class C execution gate; no production Class C execution before R4)
CREATE TABLE approval (
  approval_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid NOT NULL,
  operation_class  text NOT NULL CHECK (operation_class IN ('WORKSPACE_MUTATION','GOVERNED_ENV_MUTATION')),
  mutation_class   text NOT NULL CHECK (mutation_class IN ('INTERNAL_MUTATION','REVERSIBLE_EXTERNAL_MUTATION','COMPENSATABLE_EXTERNAL_MUTATION','IRREVERSIBLE_EXTERNAL_MUTATION')),
  recovery_strategy text NOT NULL CHECK (recovery_strategy IN ('NOT_APPLICABLE','ROLLBACK','COMPENSATE','ACCEPT_IRREVERSIBLE')),
  recovery_plan_ref text,
  risk_acceptance_ref text,
  action_kind      text NOT NULL,
  subject_kind     text NOT NULL,
  subject_id       uuid NOT NULL,
  revision_id      uuid NOT NULL,
  revision_hash    text NOT NULL,
  risk_tier        text NOT NULL,
  state            text NOT NULL CHECK (state IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED','CONSUMED','EXPIRED')),
  required_roles   text[] NOT NULL DEFAULT '{}',
  requested_by     uuid,
  decided_by       uuid,
  decided_at       timestamptz,
  reason           text,
  evidence_ref     text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, approval_id),
  UNIQUE (tenant_id, project_id, approval_id, revision_id, revision_hash, mutation_class, recovery_strategy),
  CHECK (
    (mutation_class = 'INTERNAL_MUTATION'
      AND operation_class = 'WORKSPACE_MUTATION'
      AND recovery_strategy = 'NOT_APPLICABLE'
      AND recovery_plan_ref IS NULL
      AND risk_acceptance_ref IS NULL)
    OR (mutation_class = 'REVERSIBLE_EXTERNAL_MUTATION'
      AND operation_class = 'GOVERNED_ENV_MUTATION'
      AND recovery_strategy = 'ROLLBACK'
      AND recovery_plan_ref IS NOT NULL
      AND risk_acceptance_ref IS NULL)
    OR (mutation_class = 'COMPENSATABLE_EXTERNAL_MUTATION'
      AND operation_class = 'GOVERNED_ENV_MUTATION'
      AND recovery_strategy = 'COMPENSATE'
      AND recovery_plan_ref IS NOT NULL
      AND risk_acceptance_ref IS NULL)
    OR (mutation_class = 'IRREVERSIBLE_EXTERNAL_MUTATION'
      AND operation_class = 'GOVERNED_ENV_MUTATION'
      AND recovery_strategy = 'ACCEPT_IRREVERSIBLE'
      AND recovery_plan_ref IS NULL
      AND risk_acceptance_ref IS NOT NULL)
  ),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, requested_by) REFERENCES app_user(tenant_id, user_id),
  FOREIGN KEY (tenant_id, decided_by) REFERENCES app_user(tenant_id, user_id),
  FOREIGN KEY (tenant_id, project_id, revision_id, revision_hash)
    REFERENCES subject_revision(tenant_id, project_id, revision_id, content_hash)
);

CREATE TABLE idempotency_record (
  idempotency_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid,
  operation        text NOT NULL,
  operation_class  text NOT NULL CHECK (operation_class IN ('WORKSPACE_MUTATION','GOVERNED_ENV_MUTATION')),
  mutation_class   text NOT NULL CHECK (mutation_class IN ('INTERNAL_MUTATION','REVERSIBLE_EXTERNAL_MUTATION','COMPENSATABLE_EXTERNAL_MUTATION','IRREVERSIBLE_EXTERNAL_MUTATION')),
  idempotency_key  text NOT NULL,
  request_hash     text NOT NULL,
  actor_id         text NOT NULL,
  status           text NOT NULL CHECK (status IN ('IN_PROGRESS','COMPLETED','FAILED','CONFLICT')),
  result_ref       text,
  response_code    integer,
  error_code       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  CHECK (
    (operation_class = 'WORKSPACE_MUTATION' AND mutation_class = 'INTERNAL_MUTATION')
    OR (operation_class = 'GOVERNED_ENV_MUTATION' AND mutation_class IN ('REVERSIBLE_EXTERNAL_MUTATION','COMPENSATABLE_EXTERNAL_MUTATION','IRREVERSIBLE_EXTERNAL_MUTATION'))
  ),
  UNIQUE NULLS NOT DISTINCT (tenant_id, project_id, operation, idempotency_key),
  UNIQUE (tenant_id, idempotency_id),
  UNIQUE (tenant_id, project_id, idempotency_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE TABLE execution_record (
  execution_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid NOT NULL,
  approval_id      uuid NOT NULL,
  revision_id      uuid NOT NULL,
  approved_hash    text NOT NULL,
  mutation_class   text NOT NULL CHECK (mutation_class IN ('INTERNAL_MUTATION','REVERSIBLE_EXTERNAL_MUTATION','COMPENSATABLE_EXTERNAL_MUTATION','IRREVERSIBLE_EXTERNAL_MUTATION')),
  recovery_strategy text NOT NULL CHECK (recovery_strategy IN ('NOT_APPLICABLE','ROLLBACK','COMPENSATE','ACCEPT_IRREVERSIBLE')),
  idempotency_id   uuid NOT NULL,
  status           text NOT NULL CHECK (status IN ('PROPOSED','AUTHORIZED','EXECUTING','SUCCEEDED','FAILED','ROLLED_BACK','CANCELLED')),
  target_adapter   text NOT NULL,          -- deterministic-test only before R4
  target_refs      jsonb NOT NULL DEFAULT '{}',
  before_state     jsonb,
  after_state      jsonb,
  logs_ref         text,
  recovery_ref     text,
  audit_intent_ref text,
  evidence_ref     text,
  started_at       timestamptz,
  finished_at      timestamptz,
  UNIQUE (tenant_id, execution_id, approval_id, revision_id),
  CHECK (mutation_class <> 'IRREVERSIBLE_EXTERNAL_MUTATION' OR status <> 'ROLLED_BACK'),
  CHECK (mutation_class = 'IRREVERSIBLE_EXTERNAL_MUTATION' OR status <> 'ROLLED_BACK' OR recovery_ref IS NOT NULL),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, approval_id, revision_id, approved_hash, mutation_class, recovery_strategy)
    REFERENCES approval(tenant_id, project_id, approval_id, revision_id, revision_hash, mutation_class, recovery_strategy),
  FOREIGN KEY (tenant_id, project_id, revision_id, approved_hash)
    REFERENCES subject_revision(tenant_id, project_id, revision_id, content_hash),
  FOREIGN KEY (tenant_id, project_id, idempotency_id) REFERENCES idempotency_record(tenant_id, project_id, idempotency_id)
);

CREATE TABLE outbox_event (
  outbox_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid,
  aggregate_kind   text NOT NULL,
  aggregate_id     uuid NOT NULL,
  event_type       text NOT NULL,
  event_version    integer NOT NULL,
  payload          jsonb NOT NULL,
  headers          jsonb NOT NULL DEFAULT '{}',
  status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
  attempts         integer NOT NULL DEFAULT 0,
  available_at     timestamptz NOT NULL DEFAULT now(),
  created_at       timestamptz NOT NULL DEFAULT now(),
  published_at     timestamptz,
  UNIQUE (tenant_id, outbox_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE INDEX outbox_dispatch ON outbox_event (status, available_at);

-- Evidence
CREATE TABLE evidence_package (
  package_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid NOT NULL,
  subject_kind     text NOT NULL,
  subject_id       uuid NOT NULL,
  schema_version   text NOT NULL,
  canonicalization text NOT NULL DEFAULT 'RFC8785',
  payload_ref      text NOT NULL,
  payload_hash     text NOT NULL,
  previous_hash    text,
  chain_head       boolean NOT NULL DEFAULT true,
  signature_ref    text NOT NULL,
  signature_alg    text NOT NULL DEFAULT 'EC_SIGN_P256_SHA256',
  signer_key_id    text NOT NULL,
  status           text NOT NULL DEFAULT 'SEALED',
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, package_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE UNIQUE INDEX evidence_single_chain_head
  ON evidence_package (tenant_id, subject_kind, subject_id)
  WHERE chain_head;

CREATE TABLE ledger_entry (
  entry_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid,
  package_id       uuid,
  sequence         bigint NOT NULL,
  entry_hash       text NOT NULL,
  previous_hash    text,
  actor            text NOT NULL,
  action           text NOT NULL,
  operation_class  text NOT NULL CHECK (operation_class IN ('READ','WORKSPACE_MUTATION','GOVERNED_ENV_MUTATION')),
  payload          jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sequence),
  UNIQUE (tenant_id, project_id, sequence),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, package_id) REFERENCES evidence_package(tenant_id, package_id)
);

-- AI telemetry
CREATE TABLE model_call (
  call_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  project_id       uuid,
  agent_run_id     uuid,
  provider         text NOT NULL,
  model            text NOT NULL,
  input_hash       text NOT NULL,
  schema_valid     boolean NOT NULL,
  outcome          text NOT NULL,
  latency_ms       integer,
  input_tokens     integer,
  output_tokens    integer,
  cost_micro_usd   bigint,
  correlation_id   text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);
```

### 8.4 RLS pattern

```sql
ALTER TABLE workload ENABLE ROW LEVEL SECURITY;
ALTER TABLE workload FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON workload
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

CREATE POLICY project_isolation ON workload
  USING (project_id = nullif(current_setting('app.project_id', true), '')::uuid)
  WITH CHECK (project_id = nullif(current_setting('app.project_id', true), '')::uuid);
```

- Tenant context is set with `set_config('app.tenant_id', ..., true)` inside the transaction, from the authenticated principal.
- Project context is set only after the tenant-scoped project lookup succeeds.
- Table owners and application roles must not have `BYPASSRLS`. Migration and break-glass roles are separate, audited and never used by application requests.
- The outbox relay is a separate platform identity. It processes one tenant context per batch and never joins tenant business tables. Any cross-tenant dispatch view exposes outbox identifiers and routing metadata only, and every access is audited.
- Every tenant-owned table gets the tenant policy. Every project-owned table gets both policies. A missing project context denies project rows rather than widening access. The migration test enumerates tables from the tenancy classification and fails if a table is missing RLS, forced RLS, or the required policies.
- Cross-tenant and cross-project tests run under the application database role for every repository, API, MCP resource, background job and evidence path. They fail if any application role has `BYPASSRLS` or if forced RLS is missing.

### 8.5 BigQuery layout

| Dataset | Tables | Partition | Cluster |
|---|---|---|---|
| `cairn_raw` | `source_observation`, `cost_line_item`, `scanner_finding_raw` | `ingested_at` (day) | `tenant_id`, `project_id` |
| `cairn_curated` | `estate_resource`, `estate_workload`, `estate_dependency`, `finding`, `cost_fact` | `snapshot_date` (day) | `tenant_id`, `project_id` |
| `cairn_consumption` | `assessment_summary`, `tco_summary`, `mapping_coverage`, `ai_call_log` | `summary_date` (day) | `tenant_id`, `project_id` |

Raw is immutable and replayable. Curated is derived and versioned by `model_version`. Consumption is optimized for console and reports.

### 8.6 Retention and deletion

| Data | Default retention | Mechanism |
|---|---|---|
| Raw uploads | Tenant policy, default 90 days | GCS lifecycle |
| Raw observations | Tenant policy, default 365 days | BigQuery partition expiry |
| Canonical facts | Engagement lifetime plus policy | Soft delete plus tombstone |
| Evidence packages | 7 years or tenant policy | GCS immutable bucket |
| Audit ledger | 7 years or tenant policy | Append-only, no delete |
| Model call telemetry | 180 days | Partition expiry |

---

## 9. API contracts

### 9.1 Conventions

| Concern | Rule |
|---|---|
| Base path | `/v1` |
| Tenant context | From OIDC token claim; never from a request parameter |
| Auth | Bearer JWT; service-to-service workload identity |
| Content type | `application/json`; problem details `application/problem+json` |
| Errors | RFC 7807 with `type`, `title`, `status`, `detail`, `instance`, `trace_id`, `code` |
| Pagination | Cursor-based: `?limit=&cursor=`; response `{items, next_cursor}` |
| Idempotency | `Idempotency-Key` required on externally invoked Class B/C operations; scoped to tenant, project, operation and key. The canonical request hash covers method, path, query and body. Same key and hash replays the stored result; same key with a different hash returns `409 IDEMPOTENCY_CONFLICT` |
| Async | `202 Accepted` plus `Location: /v1/operations/{id}`; operation has `state`, `progress`, `result_ref` |
| Versioning | Additive within `/v1`; breaking changes require `/v2` |
| Concurrency | `ETag`/`If-Match` on mutable resources (plans, mappings, approvals) |
| Audit | Every mutation returns `x-cairn-audit-id` |
| Evidence | Read operations expose `evidence_refs` where applicable |

Idempotency records are created in the same database transaction as the state change and the outbox event. For Class C, the idempotency record and the `PROPOSED` execution record commit together before any external effect. The event is dispatched only after commit. A retry never attaches a different request to an existing execution.

The scope is deliberately `(tenant_id, project_id, operation, idempotency_key)` rather than tenant plus key alone. Keys are endpoint-scoped: a tenant-global key would turn an unrelated operation's key reuse into a false conflict. The canonical request hash closes the retry-substitution risk within the scope. A retry with the same key and same hash returns the stored result. A retry with the same key and a different hash is rejected with `409 IDEMPOTENCY_CONFLICT` before any state change. The idempotency record is immutable after creation, and `execution_record` references it by `(tenant_id, project_id, idempotency_id)`, so a later request cannot attach a different command to an existing execution.

### 9.2 Endpoint surface (v1)

Class A = read, Class B = CAIRN workspace mutation, Class C = governed customer-environment mutation. No endpoint is unclassified, and no Class C endpoint is available before R4.

| Method | Path | Purpose | Scope | Class | Release |
|---|---|---|---|---|---|
| GET | `/v1/me` | Current principal and roles | authenticated | A | R0 |
| POST | `/v1/projects` | Create project/engagement | PROJECT_OWNER | B | R1 |
| GET | `/v1/projects` | List projects | VIEWER+ | A | R1 |
| GET | `/v1/projects/{id}` | Project detail | VIEWER+ | A | R1 |
| PATCH | `/v1/projects/{id}` | Update scope/settings | PROJECT_OWNER | B | R1 |
| GET | `/v1/projects/{id}/members` | List members | PROJECT_OWNER | A | R1 |
| POST | `/v1/projects/{id}/members` | Grant role | TENANT_ADMIN | B | R1 |
| POST | `/v1/projects/{id}/connections` | Create provider connection | PROJECT_OWNER | B | R1 |
| POST | `/v1/projects/{id}/connections/{cid}:validate` | Validate connection | PROJECT_OWNER | B | R1 |
| DELETE | `/v1/projects/{id}/connections/{cid}` | Revoke connection | PROJECT_OWNER | B | R1 |
| POST | `/v1/projects/{id}/ingestions` | Start ingestion (file or provider) | ENGINEER+ | B | R1 |
| GET | `/v1/ingestions/{run_id}` | Run status and coverage | VIEWER+ | A | R1 |
| GET | `/v1/ingestions/{run_id}/errors` | Validation errors | VIEWER+ | A | R1 |
| POST | `/v1/projects/{id}/assessments` | Start assessment | ARCHITECT+ | B | R1 |
| GET | `/v1/assessments/{assessment_id}` | Summary and status | VIEWER+ | A | R1 |
| GET | `/v1/projects/{id}/workloads` | List canonical workloads | VIEWER+ | A | R1 |
| GET | `/v1/workloads/{id}` | Workload with facts and provenance | VIEWER+ | A | R1 |
| PATCH | `/v1/workloads/{id}` | Confirm/correct metadata | ARCHITECT+ | B | R1 |
| GET | `/v1/projects/{id}/findings` | Posture findings | VIEWER+ | A | R1 |
| POST | `/v1/findings/{id}/exceptions` | Accept exception | REVIEWER+ | B | R1 |
| GET | `/v1/projects/{id}/cost/baseline` | Cost baseline and coverage | VIEWER+ | A | R1 |
| POST | `/v1/projects/{id}/cost/scenarios` | Create TCO scenario | ARCHITECT+ | B | R1 |
| GET | `/v1/projects/{id}/cost/scenarios/{sid}` | Scenario result | VIEWER+ | A | R1 |
| GET | `/v1/projects/{id}/dispositions` | 6R recommendations | VIEWER+ | A | R1 |
| POST | `/v1/workloads/{id}/dispositions` | Accept/amend/reject | ARCHITECT+ | B | R1 |
| GET | `/v1/mappings` | List mapping releases | VIEWER+ | A | R1 |
| GET | `/v1/mappings/{version}` | Release metadata | VIEWER+ | A | R1 |
| POST | `/v1/mappings/resolve` | Resolve source to target (read-only) | VIEWER+ | A | R2 |
| POST | `/v1/mappings/proposals` | Propose a mapping change (tenant-scoped) | ARCHITECT+ | B | R2 |
| POST | `/v1/mappings/{version}:publish` | Publish global release | PLATFORM_OPERATOR (internal) | B | R2 |
| POST | `/v1/projects/{id}/designs` | Generate target design | ARCHITECT+ | B | R2 |
| GET | `/v1/designs/{design_id}` | Design and resolved services | VIEWER+ | A | R2 |
| GET | `/v1/designs/{design_id}/diagram` | Diagram artefact | VIEWER+ | A | R2 |
| POST | `/v1/projects/{id}/plans` | Generate migration plan | ARCHITECT+ | B | R2 |
| GET | `/v1/plans/{plan_id}/revisions/{rev}` | Plan revision | VIEWER+ | A | R2 |
| POST | `/v1/plans/{plan_id}/approvals` | Submit for approval | PROJECT_OWNER | B | R4 |
| GET | `/v1/approvals/{id}` | Approval state | VIEWER+ | A | R4 |
| POST | `/v1/approvals/{id}:decide` | Approve/reject | REVIEWER | B | R4 |
| POST | `/v1/executions` | Request Class C execution of an approved revision | PROJECT_OWNER | C | R4 |
| GET | `/v1/executions/{id}` | Execution state and evidence | VIEWER+ | A | R4 |
| POST | `/v1/projects/{id}/transformations` | Scan and produce preview | ENGINEER+ | B | R3 |
| GET | `/v1/transformations/{run_id}` | Run summary | VIEWER+ | A | R3 |
| GET | `/v1/transformations/{run_id}/diff` | Unified diff artefact | VIEWER+ | A | R3 |
| POST | `/v1/transformations/{run_id}:validate` | Run validation | ENGINEER+ | B | R3 |
| GET | `/v1/evidence/{package_id}` | Evidence metadata | VIEWER+ | A | R1 |
| GET | `/v1/evidence/{package_id}/download` | Signed package | VIEWER+ | A | R1 |
| POST | `/v1/evidence/{package_id}:verify` | Independent verification (read-only) | VIEWER+ | A | R1 |
| GET | `/v1/operations/{id}` | Async operation status | VIEWER+ | A | R0 |
| GET | `/healthz` | Liveness | public | A | R0 |
| GET | `/readyz` | Readiness incl. DB/queue | internal | A | R0 |

### 9.3 Representative contracts

**Create project**

```http
POST /v1/projects
Idempotency-Key: 2b1c...
Content-Type: application/json

{
  "customer_name": "Example Bank",
  "name": "UK core banking modernization",
  "scope": "Retail banking estate, 420 workloads",
  "providers": ["aws", "gcp"],
  "regions": ["eu-west-2", "europe-west2"],
  "assessment_start": "2026-11-01",
  "assessment_end": "2026-11-30",
  "selected_modules": ["ASSESS", "DESIGN"]
}
```

```json
201 Created
Location: /v1/projects/8f1e...
{
  "project_id": "8f1e...",
  "tenant_id": "t-...",
  "status": "ACTIVE",
  "created_at": "2026-11-09T10:00:00Z"
}
```

**Resolve mapping**

```http
POST /v1/mappings/resolve
{
  "mapping_version": "2026.11.1",
  "source_provider": "aws",
  "source_service": "s3",
  "target_provider": "gcp",
  "region": "europe-west2"
}
```

```json
{
  "source": {"provider": "aws", "service": "s3"},
  "target": {"provider": "gcp", "service": "cloud-storage"},
  "equivalence": "APPROXIMATE",
  "caveat": "Object storage semantics differ for consistency and lifecycle transitions",
  "region_supported": true,
  "mapping_version": "2026.11.1",
  "evidence": "cloudshift pattern catalogue; GCP storage docs"
}
```

**Start assessment**

```http
POST /v1/projects/{id}/assessments
Idempotency-Key: ...
{ "modules": ["POSTURE", "COST", "ESTATE", "6R"], "provider_scope": ["aws"] }
```

```json
202 Accepted
Location: /v1/operations/op-123
{ "operation_id": "op-123", "state": "QUEUED" }
```

**Evidence verification**

```http
POST /v1/evidence/{package_id}:verify
{}
```

```json
{
  "package_id": "...",
  "hash_valid": true,
  "signature_valid": true,
  "chain_valid": true,
  "signer_key_id": "kms/.../cryptoKeyVersions/3",
  "verified_at": "2026-11-09T10:05:00Z",
  "outcome": "PASS"
}
```

### 9.4 Error model

```json
{
  "type": "https://cairn.example/errors/tenant-scope",
  "title": "Tenant scope violation",
  "status": 403,
  "detail": "The requested resource is not in the caller's tenant",
  "instance": "/v1/workloads/abc",
  "trace_id": "4bf92f3577b34da6",
  "code": "TENANT_SCOPE_VIOLATION"
}
```

Canonical codes include `UNAUTHENTICATED`, `FORBIDDEN`, `TENANT_SCOPE_VIOLATION`, `NOT_FOUND`, `VALIDATION_FAILED`, `IDEMPOTENCY_CONFLICT`, `REVISION_MISMATCH`, `MUTATION_CLASS_MISMATCH`, `RECOVERY_PLAN_REQUIRED`, `RISK_ACCEPTANCE_REQUIRED`, `MAPPING_UNAVAILABLE`, `EVIDENCE_VERIFICATION_FAILED`, `AUDIT_UNAVAILABLE`, `PROVIDER_UNAVAILABLE`, `COVERAGE_INCOMPLETE`.

---

## 10. MCP and A2A contracts

### 10.1 MCP servers (one per bounded context)

| Server | Concept | Tools (Class B writes) | Resources (Class A reads) | Release |
|---|---|---|---|---|
| `estate-mcp` | Estate | `confirm_workload`, `record_disposition` | `estate://projects/{id}/workloads`, `estate://workloads/{id}` | R1 |
| `posture-mcp` | Posture | `accept_exception`, `request_remediation` (request only) | `posture://projects/{id}/findings`, `posture://controls/{id}` | R1 |
| `cost-mcp` | FinOps | `create_scenario` | `cost://projects/{id}/baseline`, `cost://scenarios/{id}` | R1 |
| `mapping-mcp` | Registry | `propose_mapping` | `mapping://releases/{version}`, `mapping://resolve?...` | R2 |
| `design-mcp` | Design | `generate_design` | `design://projects/{id}/current`, `design://designs/{id}` | R2 |
| `plan-mcp` | Planning | `create_plan`, `submit_for_approval` | `plan://projects/{id}/plans`, `plan://plans/{id}/revisions/{rev}` | R2 |
| `transform-mcp` | Modernize | `start_preview`, `validate_preview` | `transform://runs/{id}`, `transform://runs/{id}/diff` | R3 |
| `evidence-mcp` | Evidence | `seal_package` (internal evidence only) | `evidence://packages/{id}`, `evidence://verify/{id}` | R1 |

No MCP server exposes a Class C tool before R4. When Class C tools are introduced, they call the kernel execution gate and carry the same approval, evidence and recovery obligations as the API.

### 10.2 MCP rules

1. Tools map to application commands; resources map to queries. No business logic in the server.
2. Every tool validates input with Pydantic and authorizes against RBAC plus tenant scope.
3. Every write emits an audit event and requires an idempotency key.
4. OAuth against the customer IdP or CAIRN issuer; per-key tool allowlist; per-agent RBAC.
5. StreamableHTTP at `/mcp`; SSE only where a host requires it.
6. Each server ships a generated manifest and a conformance test.

### 10.3 A2A agent cards

```json
{
  "name": "cairn-assess",
  "description": "Runs read-only cloud estate assessments and returns evidence-backed findings",
  "url": "https://mcp.cairn.example/a2a",
  "version": "1.0.0",
  "capabilities": {"streaming": true, "pushNotifications": false},
  "skills": [
    {"id": "assess-estate", "name": "Assess estate", "inputModes": ["application/json"], "outputModes": ["application/json"]}
  ],
  "securitySchemes": {"oauth2": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "https://idp.example/token", "scopes": {"cairn.assess": "Run assessment"}}}}}
}
```

The A2A bridge accepts `POST /v1/message:send`, routes to one MCP server by declared skill or keyword, calls the tool, and returns an A2A response. It is a thin adapter with no domain logic.

---

## 11. Events and asynchronous workflows

### 11.1 Event envelope

```json
{
  "event_id": "evt-...",
  "event_type": "assessment.completed.v1",
  "event_version": 1,
  "tenant_id": "t-...",
  "project_id": "p-...",
  "operation_class": "WORKSPACE_MUTATION",
  "occurred_at": "2026-11-09T10:00:00Z",
  "correlation_id": "4bf92f3577b34da6",
  "causation_id": "op-123",
  "producer": "assess-worker",
  "payload": {},
  "evidence_ref": "evidence://packages/..."
}
```

### 11.2 Topics

| Topic | Events | Consumer |
|---|---|---|
| `cairn.ingestion` | `ingestion.requested.v1`, `ingestion.completed.v1`, `ingestion.failed.v1` | estate worker, console |
| `cairn.estate` | `estate.normalized.v1`, `estate.fact.confirmed.v1` | posture, finops, 6R |
| `cairn.assessment` | `assessment.requested.v1`, `assessment.completed.v1` | reporting, evidence |
| `cairn.posture` | `finding.recorded.v1`, `exception.accepted.v1` | reporting, roadmap |
| `cairn.cost` | `cost.imported.v1`, `baseline.created.v1`, `scenario.created.v1` | design, reporting |
| `cairn.mapping` | `mapping.release.published.v1`, `mapping.proposed.v1` | design, transformation, cache invalidation |
| `cairn.design` | `design.generated.v1`, `plan.created.v1`, `plan.revised.v1` | console, approvals |
| `cairn.approval` | `approval.requested.v1`, `approval.decided.v1` | execution, console |
| `cairn.execution` | `execution.started.v1`, `execution.completed.v1`, `execution.failed.v1` | evidence, console |
| `cairn.evidence` | `evidence.sealed.v1`, `evidence.verified.v1` | governance, reporting |
| `cairn.ai` | `model.call.completed.v1` | observability, cost attribution |

Event rules:
- State changes and their outbox rows commit in the same database transaction. A dispatcher publishes asynchronously; no external provider call happens inside that transaction.
- Consumers are idempotent by `event_id` and verify tenant/project scope from the envelope.
- Event types are versioned (`.v1`). Additive fields are compatible; removal, rename or semantic change requires a new version and a migration window.
- Failed deliveries retry with backoff, then move to a dead-letter subscription with alerting and a replay runbook.
- Execution events exist in the contract from R0, but no producer or consumer may perform a Class C effect before R4.

Outbox failure semantics are mandatory test cases (R-OUTBOX-01), not assumptions:
1. **Crash after commit, before dispatch.** The process dies after the database transaction commits and before publish. On restart, the dispatcher resumes and publishes the pending outbox rows exactly once, with no loss and no duplication.
2. **Duplicate event delivery.** The transport redelivers an event. The consumer's `event_id` idempotency suppresses the second application of the effect.
3. **Consumer crash after effect, before acknowledgement.** The consumer applies the effect and dies before ack. Redelivery does not repeat the effect, and any partial state is reconcilable from the recorded outcome.
4. **Dead-letter replay.** Events that exhaust retries are dead-lettered with alerting; replay from the dead-letter subscription preserves ordering guarantees, correlation IDs and the replay runbook.
5. **Tenant context isolation during replay.** A replayed or re-dispatched event carries its original tenant/project scope; it cannot act outside that scope even when replayed by a platform operator or a different batch context.

### 11.3 Workflow state machines

**Ingestion run**

```
QUEUED -> RUNNING -> PARSING -> NORMALIZING -> COMPLETED
                    \-> PARTIAL -> COMPLETED_WITH_GAPS
                    \-> FAILED
```

**Assessment**

```
QUEUED -> COLLECTING -> NORMALIZING -> SCORING -> GENERATING_REPORT -> COMPLETED
                                                        \-> COMPLETED_WITH_GAPS
        \-> FAILED
```

**Plan, approval and execution**

```
Plan/design revision:  DRAFT -> IMMUTABLE
Approval:              DRAFT -> PENDING_APPROVAL -> APPROVED -> CONSUMED
                                             \-> REJECTED
                                             \-> CANCELLED
                       APPROVED -> EXPIRED
Execution (Class C):   PROPOSED -> AUTHORIZED -> EXECUTING -> SUCCEEDED
                                  \-> CANCELLED      \-> FAILED
                                                     \-> ROLLED_BACK
```

A revision is immutable once created. A new revision requires a new approval. Execution refuses to start unless the approval is `APPROVED`, the revision and hash match, and separation-of-duties policy passes.

Rules:
- Every transition is persisted with actor, timestamp, reason and correlation ID.
- Approvals and executions bind to immutable revision rows and exact content hashes (ADR-009).
- A new revision invalidates prior approvals for execution purposes and requires re-approval.
- Class C execution requires an `Idempotency-Key` scoped to `(tenant_id, project_id, operation, key)` with a canonical request hash; retries replay the recorded outcome or return a conflict. The idempotency record, `PROPOSED` execution and outbox event commit in one transaction before any external effect.
- Class C appends the intent and authorization to the ledger before the external effect; if the ledger is unavailable, execution fails closed. A database transaction cannot make an external side effect atomic, so R4 must explicitly handle the distributed boundary (outbox, execution state, reconciliation and rollback).

### 11.4 Job execution model

| Job type | Trigger | Runtime | Concurrency | Resumability |
|---|---|---|---|---|
| File ingestion | API | Worker | Per project, bounded | Chunked, checkpoint in Postgres |
| Provider inventory | API/schedule | Worker with provider adapter | Rate-limited per connection | Cursor/next-token checkpoint |
| Cost import | API/schedule | Worker + BigQuery load | Per connection | Idempotent load by run_id |
| Posture scan | Assessment | Worker + scanner adapter | Bounded | Per-control checkpoint |
| Design generation | API | Worker | Per project | Deterministic, restartable |
| Transformation | API | Worker + Rust core | Bounded, sandboxed | Per-repository checkpoint |
| Evidence sealing | Event | Worker | Per package | Idempotent by hash |

---

## 12. Security, tenancy and evidence

### 12.1 Identity and authorization

| Role | Capabilities |
|---|---|
| TENANT_ADMIN | Manage tenant, users, roles, connections; propose mappings; no global registry publication |
| PROJECT_OWNER | Create/manage project, members, submit approvals |
| ARCHITECT | Run assessments, edit workloads, generate designs/plans, propose mappings |
| ENGINEER | Create ingestions/transformations; view |
| REVIEWER | Approve/reject, accept exceptions (separation of duties) |
| AUDITOR | Read evidence, audit, provenance; no mutation |
| VIEWER | Read-only project access |
| PLATFORM_OPERATOR (internal) | Publish global mapping releases and operate the platform; not a tenant role and not reachable from tenant APIs |

Authorization is enforced in the application layer with domain policy objects, and in persistence with RLS. Every command carries an operation class and a mutation class; Class C commands are rejected unless they originate inside the kernel execution gate. The UI, MCP, A2A and provider adapters are not security boundaries.

### 12.2 Tenant isolation tests

Mandatory for every new repository and query:
- Cross-tenant read returns 404/403, not data.
- Cross-tenant write is rejected before persistence.
- RLS is enabled and forced on every tenant-owned and project-owned table, with the required policies. The migration test asserts `pg_class.relrowsecurity` and `pg_class.relforcerowsecurity` are true.
- Tests run under the application database role, not the table owner, and assert `pg_roles.rolbypassrls` is false for every application role.
- The same tests prove cross-tenant and cross-project reads and writes are denied under the application role.
- Background jobs carry tenant context explicitly and re-assert it at each persistence boundary.

Adversarial modes (R-TENANT-03), run under the application role:
- Missing tenant context fails closed. A query issued without tenant context returns nothing or errors; it never defaults to any tenant, any project or an unfiltered result set.
- Connection-pool reuse cannot leak tenant context. A pooled connection handed from one tenant's request to another tenant's request has isolation re-established per use; state left on the session by the previous request is not readable or writable.
- Tenant-context change attempts are rejected and audited. Attempts to alter tenant context mid-request or mid-transaction, including session-variable and `SET LOCAL` tricks, fail closed.

### 12.3 Secrets and provider onboarding

- Read-only roles by default; least privilege; explicit scope.
- Workload identity or short-lived credentials where available; no long-lived keys.
- Secret material is stored by reference only; never returned after write.
- Connection validation records scopes and last-validated time.
- Revocation is immediate and audited.

### 12.4 AI safety

- All model output is schema-validated before use.
- The model cannot approve, execute or alter policy.
- Prompt-injection controls at ingress; PII/DLP redaction before model calls.
- Model calls are logged with input hash, provider, model, tokens, latency, outcome and cost.
- Evaluation sets cover schema validity, grounding, refusal and regression behaviour.

### 12.5 Evidence model

Evidence package schema (signed JSON):

```json
{
  "schema_version": "1.0",
  "package_id": "...",
  "tenant_id": "...",
  "project_id": "...",
  "subject": {"kind": "ASSESSMENT", "id": "..."},
  "created_at": "...",
  "producer": {"service": "assess-worker", "version": "..."},
  "inputs": [{"kind": "INGESTION_RUN", "ref": "...", "hash": "..."}],
  "provenance": [{"fact_ref": "...", "source": "...", "observed_at": "..."}],
  "versions": {"model": "...", "mapping": "...", "pattern": "...", "policy": "..."},
  "assumptions": [],
  "policy_decisions": [],
  "model_calls": [{"provider": "...", "model": "...", "input_hash": "...", "schema_valid": true}],
  "outputs": [{"kind": "REPORT", "ref": "...", "hash": "..."}],
  "outcome": "PASS",
  "previous_hash": "...",
  "payload_hash": "...",
  "signature": {"key_id": "...", "algorithm": "EC_SIGN_P256_SHA256", "value": "..."}
}
```

Evidence rules:
- Payloads are canonicalized (RFC 8785) before hashing; the canonicalization version is recorded.
- The signature covers schema version, tenant/project, subject, payload hash, previous hash, input versions, creation time, algorithm and signer key id.
- The chain head is unique per subject. A fork, gap or second head fails verification.
- Signing keys live in Cloud KMS; rotation, custody, revocation and verification-key publication are documented.
- Verification is independent of CAIRN: hash, signature and chain, using published verifier material.
- Absence of evidence is `UNVERIFIED`, never `PASS`.
- Class C writes require a successful ledger append before the external effect. If the ledger is unavailable, execution fails closed.
- Because an external provider effect and a database commit cannot be atomic, R4 defines reconciliation and rollback for the distributed boundary.

### 12.6 Supply chain and runtime

- Non-root containers; read-only root filesystem where possible.
- SBOM (CycloneDX), dependency audit, container scan, image signing.
- Signature verification at deploy time (policy admission for Kubernetes).
- Network egress allowlist per service; no public ingress except the console/API and explicit webhooks.
- Sandboxed transformation execution with CPU, memory, time and network limits.
- Ingestion parsers enforce file-size, row-count, nesting-depth and decompression limits; reject path traversal and untrusted archives; record parser version.
- HMAC verification, timestamp/nonce and replay protection for webhooks.

---

## 13. Deployment topology

The source is public under Apache-2.0 (ADR-018). The hosted SaaS in 13.1 is the only supported deployment. 13.2 is internal only; there is no supported customer-deployed edition (ADR-013).

### 13.1 Hosted SaaS (initial profile)

```
Region: europe-west2 (primary), secondary per residency decision

Cloud Run services
  cairn-api          (min 1, max N, concurrency tuned, ingress internal+LB)
  cairn-worker       (min 1, max N, no ingress)
  cairn-mcp-gateway  (min 0, max N, internal+LB, OAuth)
  cairn-console      (static/SSR, CDN + LB)

Cloud Run jobs
  cairn-scheduler
  cairn-ingest-job
  cairn-assess-job
  cairn-transform-job

Data
  Cloud SQL PostgreSQL (HA, PITR, private IP)
  BigQuery datasets: cairn_raw, cairn_curated, cairn_consumption
  Cloud Storage: cairn-raw-{env}, cairn-artifacts-{env}, cairn-evidence-{env} (immutable)
  Pub/Sub: cairn.* topics and subscriptions
  Memorystore Redis (cache, rate limit)

Security
  Secret Manager, Cloud KMS, Workload Identity
  Artifact Registry (signed images)
  Cloud Armor, IAP for admin surfaces
  VPC Service Controls boundary where required

Observability
  Cloud Logging, Cloud Monitoring, Cloud Trace, OTel collector
```

### 13.2 Internal portability profile (not a customer offering)

Helm chart `infra/helm/cairn`, used for internal disaster recovery and portability testing only:
- `api`, `worker`, `mcp-gateway`, `console` deployments.
- PostgreSQL (CloudNativePG or managed), Redis, object storage (MinIO/S3-compatible), Kafka or Pub/Sub emulator where required.
- Keycloak for identity, Vault or External Secrets for secrets.
- Same contracts and migrations; provider adapters remain pluggable.
- No air-gapped customer mode and no supported customer-deployed edition (ADR-013). The open-source licence permits unsupported self-hosting by third parties.

### 13.3 Terraform module library

| Module | Contents |
|---|---|
| `cairn-network` | VPC, subnets, private service access, egress, firewall |
| `cairn-iam` | Service accounts, WIF, least-privilege roles, KMS IAM |
| `cairn-data` | Cloud SQL, BigQuery datasets, GCS buckets, retention |
| `cairn-runtime` | Cloud Run services/jobs, scaling, probes, ingress |
| `cairn-events` | Pub/Sub topics, subscriptions, dead-letter, retries |
| `cairn-observability` | Log sinks, metrics, dashboards, alerts, SLOs |
| `cairn-guardrails` | Org policies, budgets, spend caps, Cloud Armor |
| `cairn-evidence` | KMS keys, immutable bucket, audit sink |
| `cairn-connections` | Customer onboarding roles for GCP read-only; separate execution roles only in R4+ after the gate is proven |

Environments: `dev`, `staging`, `prod`, with isolated state, credentials and data.

### 13.4 CI/CD

| Stage | Checks |
|---|---|
| Lint and type | ruff, mypy, eslint, tsc, cargo clippy |
| Architecture | import-linter, TS boundaries, cargo-deny, conformance harness |
| Unit and contract | pytest, vitest, cargo test, adapter contract suite |
| Security | pip-audit, npm audit, Trivy, secret scan, SBOM, image sign |
| Integration | Postgres, BigQuery emulator or test project, Pub/Sub emulator |
| E2E | create project → ingest → assess → design → evidence verify |
| Deploy | plan → approval → apply → drift check |

Promotion is by immutable signed image digest. Plan and apply are tied to the same reviewed revision.

### 13.5 Environment and data isolation

| Environment | Data | Credentials | Access |
|---|---|---|---|
| dev | Synthetic only | Dev service accounts | Engineering |
| staging | Synthetic or anonymized pilot | Staging accounts | Engineering + QA |
| prod | Customer data | Prod accounts, WIF, break-glass | Restricted, audited |

No production data in non-production environments. De-identification is mandatory for any copied dataset.

### 13.6 Operational readiness (R0)

- Backups: automated Cloud SQL backups and BigQuery/GCS retention; restore tested before customer data.
- Incident response: severity levels, on-call expectations for a solo maintainer, customer notification path and evidence preservation.
- Key rotation: KMS signing-key rotation, published verification keys, overlap window and re-signing rules.
- Tenant deletion: suspend, export, delete and certify path covering PostgreSQL, BigQuery, GCS, evidence and backups.
- UK residency matrix: data, backups, keys, logs and support access, mapped to `europe-west2` and approved before customer onboarding.

---

## 14. Observability and non-functional targets

### 14.1 Telemetry standard

- W3C trace context propagated across API, workers, adapters, model calls and MCP/A2A.
- RED metrics for every service and adapter.
- Structured JSON logs with `correlation_id`, `tenant_id` (hashed where required), `project_id`, `operation_id`.
- Per-AI-call record: provider, model, input hash, schema validity, tokens, latency, outcome, micro-USD cost.
- Dashboards: ingestion throughput, provider throttling, job failures, mapping coverage, evidence verification, approval queue.

### 14.2 Targets

| NFR | Target |
|---|---|
| NFR-001 availability | 99.5% monthly for hosted control plane at MVP |
| NFR-002 latency | p95 < 2s for common reads under pilot load; long jobs async |
| NFR-003 scalability | Stateless API/worker horizontal scaling; queued jobs independent |
| NFR-004 resilience | Timeouts, bounded retry with jitter, circuit breakers, resumable workflows |
| NFR-005 integrity | Transactional writes; independently verifiable evidence chain |
| NFR-006 portability | Provider adapters behind ports; Kubernetes profile later |
| NFR-007 security | No critical/high release waiver without documented risk acceptance |
| NFR-008 accessibility | WCAG 2.2 AA for core journeys |
| NFR-009 maintainability | Mandatory boundaries and conformance in CI |
| NFR-010 observability | Correlation IDs and OTel across all paths |
| NFR-011 AI governance | Model call metadata recorded |
| NFR-012 localization | Jurisdiction packs versioned; bilingual later |
| NFR-013 recoverability | Backups, restore tests, RPO/RTO defined before customer data |
| NFR-014 auditability | Assessment/recommendation/approval/execution history retained |

---

## 15. Testing and conformance

### 15.1 Test layers

| Layer | What is tested | Gate |
|---|---|---|
| Domain unit | Invariants, state machines, 6R, cost, mapping resolution, policy | Coverage floor, mutation spot checks |
| Architecture | import-linter, TS boundaries, Rust workspace, rule map | 100% mandatory rules |
| Adapter contract | Same suite for fake and real adapters | Pass for every adapter |
| API integration | AuthN/Z, tenant isolation, persistence, ingestion | Pass |
| MCP/A2A | Tool/resource semantics, OAuth, allowlists, bridge | Pass |
| AI eval | Schema validity, grounding, refusal, regression | Threshold pass |
| Security | Dependency, container, SBOM, signing, injection, cross-tenant | Pass |
| E2E | Project → ingest → assess → design → evidence verify | Pass |
| Resilience | Timeouts, retries, breaker, idempotency, audit outage, partial provider failure | Pass |

### 15.2 Release gates

1. Conformance score 100% for mandatory rules; deviations require ADR and approval.
2. Coverage floor per critical package (default 80%; critical kernel packages higher).
3. No critical security findings; high findings have documented risk acceptance and owner.
4. Tenant isolation tests pass for every repository and query path.
5. Every mutating use case has idempotency, authorization, audit and failure-mode tests.
6. Evidence tamper and fork tests detect altered payloads, broken chains and duplicate chain heads.
7. AI eval set passes; schema-invalid model output is rejected.
8. Every generated diagram/plan records registry and pattern versions and exposes unresolved mappings.

### 15.3 Conformance harness implementation

- `tools/conformance/rules.yaml` maps rule ID to check command and owner.
- `make conformance` runs all checks and emits machine-readable results.
- CI fails on any mandatory failure; the harness self-tests that every mandatory rule has a check.
- Start from the `punjab` conformance map and the `tda-uk-accelerator` gate semantics.

---

## 16. Ordered engineering backlog

Sizing: S (1-2 days), M (3-5 days), L (1-2 weeks), XL (2-4 weeks). Order is the recommended build order; dependencies are explicit.

### 16.0 R0 architecture acceptance gate (mandatory)

R0 does not exit until all gates pass with linked evidence. This gate is a **hard release condition, not a documentation exercise**: every gate is satisfied by evidence produced by CI — test runs, pipeline artefacts, scan outputs and constraint checks — linked from the acceptance record. A gate satisfied only by prose does not pass.

- [ ] ADR-008, ADR-009, ADR-010 and ADR-012 amended and accepted.
- [ ] All API and MCP operations classified as Class A, B or C, with a mutation class, recovery strategy and, for external mutations, a complete compensation contract.
- [ ] No unapproved Class C path and no production execution adapter exist.
- [ ] R1 read-only boundary and deterministic test adapter are documented.
- [ ] Immutable revision, approval and execution schema is implemented with constraints.
- [ ] Idempotency (tenant/project/operation/key scope, canonical request hash) and transactional outbox contracts are defined, including failure-mode semantics for crash-after-commit, duplicate delivery, consumer crash before acknowledgement, dead-letter replay and replay tenant isolation.
- [ ] Complete tenancy matrix is approved for tables, APIs, MCP, events, storage, evidence and workers.
- [ ] RLS forced with cross-tenant and cross-project tests for every classified table, run under the application role, with no application role holding `BYPASSRLS`, including missing-context, connection-pool reuse and context-change adversarial modes.
- [ ] Evidence canonicalization, signing, chain-head and offline verification contracts are defined.
- [ ] CI security baseline is established: secret scan, dependency/container scan, SBOM, image signing.
- [ ] UK data, backup, key and support-access residency matrix is approved.
- [ ] Backup/restore, incident response, key rotation and tenant deletion runbooks are approved and tested where possible.
- [ ] Read-plane and execution-plane identity, credential and network isolation is demonstrated.

### R0 - Platform foundation (exit: deployable skeleton, rules in CI)

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R0-01 | Create monorepo, uv/Cargo/pnpm workspaces, Makefile | S | - | `make bootstrap` installs all workspaces; CI runs on empty packages |
| R0-02 | Implement `kernel/hex` primitives, ports, DI, settings, errors | M | R0-01 | Unit tests; a sample module uses only public kernel APIs |
| R0-03 | Implement `kernel/tenancy` and tenant context propagation | M | R0-02 | Context set from auth middleware; cross-tenant unit test fails closed |
| R0-04 | Implement the full `contracts/estate` v0 model, all entities | XL | R0-02 | All entities validate golden fixtures; no SDK imports |
| R0-05 | Implement `contracts/events` and `contracts/api` | M | R0-02 | JSON schema tests; version field enforced |
| R0-06 | Add `import-linter` contracts and CI job | S | R0-01 | Deliberate violation fails CI |
| R0-07 | Build conformance harness and rule map v0 | M | R0-06 | `make conformance` reports pass/fail; self-test covers all mandatory rules |
| R0-08 | Implement Postgres migrations baseline (tenant, project, user, roles) | M | R0-02 | Migrations up/down pass; RLS test enumerates tables |
| R0-09 | Implement auth middleware (OIDC/JWT) and RBAC skeleton | M | R0-02 | Token maps to principal and roles; unauthorized requests rejected |
| R0-10 | Implement audit sink port and Postgres append-only adapter | M | R0-08 | Audit-before-effect test; outage fails closed |
| R0-11 | Implement evidence kit: hashing, envelope, signing port, fake verifier | L | R0-04 | Tamper test detects modification; chain verification test passes |
| R0-12 | Implement observability kit: OTel, RED, correlation, AI-call logger | M | R0-02 | Trace continuity test; required fields present |
| R0-13 | Define provider adapter contracts and fake adapter | L | R0-04 | Contract suite passes against fake; interface review approved |
| R0-14 | Implement mapping registry schema and seed loader | M | R0-04 | Schema validation; seed loads; immutable release rule test |
| R0-15 | Create `api`, `worker`, `console` skeletons with health/readiness | M | R0-02 | Local compose runs; health endpoints pass |
| R0-16 | Create Terraform module skeletons and dev environment | L | R0-01 | `terraform plan` clean in dev; no long-lived secrets |
| R0-17 | Create CI/CD pipelines: lint, test, conformance, security, build, sign | L | R0-07 | Pipeline green; SBOM and signature artefacts produced |
| R0-18 | Review and accept ADR-001..018 and the architecture-review amendments; record outcomes in `docs/adr/README.md` and maintain the reference register | S | - | All ADRs accepted or amended; ADR-017 acknowledged as a constraint; decision log current |
| R0-19 | Publish the operation and mutation classification plus the tenancy matrix for every API, MCP tool, resource, event, table, bucket and worker | M | R0-03, R0-05 | Every operation has Class A/B/C and a mutation class; every entity is Global/Tenant/Project; external mutations have a recovery strategy and a complete compensation contract; review approved; encoded in contracts |
| R0-20 | Hold the R0 architecture acceptance review against section 16.0 | S | R0-19 | All 13 gates pass with linked CI evidence; no gate passes on documentation alone; failures have owners and dates |

### R1 - CAIRN Assess (exit: read-only assessment, workspace decisions, evidence and gate validation)

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R1-01 | Implement project, membership and settings APIs | M | R0-09 | CRUD with RBAC; cross-tenant tests pass |
| R1-02 | Implement provider connection create/validate/revoke for GCP | L | R0-13 | Read-only scope only; no execution credentials or write scope before R4; secret never returned; revoke audited |
| R1-03 | Implement file ingestion adapters (CSV/JSON/RVTools/HVTools/BOM) | L | R0-13 | Golden fixture per format; parser version recorded |
| R1-04 | Implement ingestion run state machine, checkpoints and errors | L | R1-03 | Resumable after failure; partial coverage recorded |
| R1-05 | Implement GCP inventory adapter (read-only) | XL | R1-02 | Collects projects/regions/resources; rate limit and retry verified |
| R1-06 | Implement canonical estate normalization and provenance | XL | R0-04, R1-03 | Conflicting observations preserved; missing = UNVERIFIED |
| R1-07 | Implement workload derivation and dependency capture | L | R1-06 | Workloads link resources; dependencies queryable |
| R1-08 | Implement control catalogue schema and GCP seed controls | L | R0-04 | Control versions immutable; evaluations reference version |
| R1-09 | Implement scanner adapters (Prowler/Steampipe/OPA) and normalization | XL | R1-08 | Common Finding model; unsupported records reported |
| R1-10 | Implement posture assessment and coverage reporting | L | R1-09 | Deterministic scoring only where rules support; unknown visible |
| R1-11 | Implement GCP billing import and canonical cost records | L | R1-02 | Currency, period, tags, provenance captured |
| R1-12 | Implement cost baseline and coverage/unallocated spend | M | R1-11 | Coverage shown; missing tags reported |
| R1-13 | Implement TCO scenario engine with assumptions and price timestamp | L | R1-12, R0-14 | Assumptions explicit; reproducible result |
| R1-14 | Implement 6R classification and accept/amend/reject flow | L | R1-07 | Rationale and confidence stored; decisions audited |
| R1-15 | Implement assessment orchestration and async operation API | L | R1-04..R1-14 | End-to-end run completes; failures resumable |
| R1-16 | Implement assessment report renderer (human-readable) | M | R1-15 | Report includes coverage, assumptions, versions |
| R1-17 | Implement signed evidence package for assessment | L | R0-11, R1-15 | Package verifies independently; tamper detected |
| R1-18 | Build assessment console screens | XL | R1-01..R1-17 | Journey complete: project → ingest → assess → inspect → export |
| R1-19 | Add cross-tenant, resilience and security tests for R1 | L | R1-01..R1-18 | Mandatory gates pass |
| R1-20 | Pilot runbook, data-handling terms and SLO baseline | M | R1-18 | Pilot can be run without engineering intervention |
| R1-21 | Implement immutable revision, approval and execution state machines | L | R0-10 | DB-bound revision hash; mutation class, recovery precondition and compensation-contract completeness enforced; separation of duties; invalid transitions rejected |
| R1-22 | Implement kernel execution gate with deterministic test adapter and scoped idempotency | L | R1-21, R0-10 | Full gate lifecycle proven for every external mutation class; recovery precondition blocks authorization when absent; test adapter cannot be replaced by production adapter; no execution credentials reachable |
| R1-23 | Implement transactional outbox dispatcher with failure-mode tests | M | R1-15, R0-05 | R-OUTBOX-01 passes by failure injection: crash after commit before dispatch, duplicate delivery, consumer crash after effect before acknowledgement, dead-letter replay and replay tenant isolation |

### R2 - CAIRN Design (exit: one model produces consistent design artefacts)

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R2-01 | Implement mapping registry service, release workflow and resolver | XL | R0-14 | Resolve returns equivalence/caveat/version; published immutable |
| R2-02 | Seed service map for pilot provider pairs | L | R2-01 | Top 40 services per pair; approximate/unavailable labelled |
| R2-03 | Implement pattern catalogue schema and 8-12 seed patterns | L | R0-04 | Parameter schema, preconditions, outputs, validation rules |
| R2-04 | Implement target model generator | XL | R2-01, R2-03 | Deterministic from estate + pattern + parameters; records versions |
| R2-05 | Implement diagram compiler (Draw.io compatible) | XL | R2-04 | Approximate/unavailable/unresolved distinct; no invented shapes |
| R2-06 | Implement migration roadmap and wave sequencing | L | R2-04, R1-14 | Dependencies respected; constraints and risks shown |
| R2-07 | Implement IaC plan preview (Terraform) | L | R2-04 | Plan only; no apply; mapping and pattern versions recorded |
| R2-08 | Implement design artefact export (JSON, diagram, report) | M | R2-04..R2-07 | Machine-readable and human-readable exports |
| R2-09 | Build design console screens | L | R2-04..R2-08 | Parameter edit, regenerate, inspect caveats, export |
| R2-10 | Add version-consistency conformance check | S | R2-05..R2-07 | Diagram, plan and IaC share model/mapping/pattern versions |

### R3 - CAIRN Modernize preview (exit: safe, reviewable transformation proposal)

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R3-01 | Implement repository source adapter (Git and upload) | L | R0-13 | Reads ref; no write-back |
| R3-02 | Implement Rust parser/detector core for pilot languages | XL | R3-01 | Deterministic detection; golden corpus |
| R3-03 | Implement pattern-driven transformation engine and manifest | XL | R3-02, R2-01 | Applies/skips/unsupported recorded with reasons |
| R3-04 | Implement unified diff artefact and preview API | L | R3-03 | Diff retrievable; no source mutation |
| R3-05 | Implement validation adapters (static, tests, dependency) | L | R3-03 | Results per check; failures block approval |
| R3-06 | Implement transformation telemetry and evidence record | M | R3-03 | Detector/pattern versions, inputs, outputs recorded |
| R3-07 | Build diff review and validation console | L | R3-04..R3-06 | Engineer can review, comment, request changes |
| R3-08 | Add sandboxed execution (limits, no network by default) | L | R3-05 | Resource and time limits enforced; egress blocked |

### R4 - Class C execution (exit: controlled customer-environment writes with evidence)

R1 delivered the revision/approval model and a deterministic gate harness (R1-21/R1-22). R4 adds production provider execution, rollback and drift. No production Class C adapter may exist before R4.

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R4-01 | Implement risk-tier policy engine keyed by mutation class | M | R1-21 | Role requirements per tier and mutation class enforced; irreversible mutations require explicit risk acceptance |
| R4-02 | Implement GCP production provider execution adapter behind the kernel gate | XL | R1-22, R4-01 | No bypass path; scoped short-lived credentials; adapter cannot be called directly; class and recovery match the approved revision |
| R4-03 | Implement Terraform plan/apply/drift on top of the provider adapter | XL | R2-07, R4-02 | Plan and apply tied to approved revision; drift detected |
| R4-04 | Implement rollback and compensation execution, reconciliation and runbooks | L | R4-03 | Reversible rollback and compensatable recovery tested and evidenced; irreversible path requires risk acceptance |
| R4-05 | Build approval and execution console | L | R1-21, R1-22, R4-01..R4-04 | Approver sees exact revision, diffs, mutation class, recovery plan and evidence |
| R4-06 | Add execution security, distributed-boundary and failure-mode tests | L | R4-02..R4-05 | Partial failure, timeout, unauthorized apply, audit outage, missing recovery plan, compensation trigger failure, irreversible rollback attempt, dead-letter replay and reconciliation all tested |

### R5 - CAIRN Operate (exit: governed operational loops)

| ID | Story | Size | Depends | Acceptance criteria |
|---|---|---|---|---|
| R5-01 | Implement FinOps graded remediation and policy | L | R1-12, R4-02, R4-04 | Alert/throttle/cap/stop/disable with Class C approval and recovery handling |
| R5-02 | Implement LLMOps gateway and AI control loop | XL | R0-12 | Security/reliability/cost/observability pillars |
| R5-03 | Implement MLOps lifecycle module | XL | R0-13 | Registry, drift, self-healing with bounds |
| R5-04 | Implement MCP gateway and A2A bridge | L | R0-13 | Registry, OAuth, agent cards, bridge tests |
| R5-05 | Implement resilience and sovereignty module | XL | R2-01 | Failover rules, residency sweeps, evidence |
| R5-06 | Implement vertical accelerator packs | XL | R0-02 | Each pack conforms to kernel and contracts |

### 16.1 Critical path

```
R0-01 -> R0-02 -> R0-04 -> R0-06 -> R0-07
                      \-> R0-11 -> R1-17
       R0-08 -> R0-10 -> R1-21 -> R1-22
       R0-13 -> R1-02 -> R1-05 -> R1-06 -> R1-15 -> R1-17 -> R1-18
       R0-14 -> R2-01 -> R2-04 -> R2-05/R2-07
       R2-01 -> R3-03 -> R3-04 -> R3-07
       R1-22 -> R4-01 -> R4-02 -> R4-03 -> R4-04 -> R4-06
```

Do not start R1 provider work before R0-13 (adapter contracts) and R0-04 (canonical model) are stable. Do not start R2 design generation before R2-01 (registry service) and R1-06 (canonical normalization) are stable. Do not start R4 until R1 has proven the gate and the no-mutation boundary.

### 16.2 Re-baselined delivery outlook

The earlier 22-33 week figure assumed code reuse and a 5-7 person team. Both assumptions are withdrawn. The binding constraint is one maintainer (Allan), using agent assistance, on a public open-source repository, with no hard deadline beyond ASAP.

| Milestone | Outlook | Notes |
|---|---|---|
| R0 exit | 8-12 weeks | Public repo, full model, Rust workspace, conformance, architecture acceptance gate |
| Pilot-able R1 | 9-15 months solo; 6-10 months with sustained agent assistance | Read-only assessment, workspace decisions, evidence and gate validation; no customer date committed |
| R4, Class C execution | 24-36 months solo; 15-24 months with assistance | Controlled Class C writes; do not commit until R1 is proven |
| R5 | Undated | Scope intentionally open |

Sixteen stories are XL and at least ten sit on the critical path. Agent assistance reduces implementation effort, not review, security or support capacity. ASAP therefore means optimizing for the earliest credible R1 and adding maintainers when the critical path allows; it is not a date.

---

## 17. Reference use and clean-room policy

### 17.1 How the 43 repositories are used

CAIRN is greenfield (ADR-017). The reference repositories are evidence for how problems were solved, not a source of code. Nothing is lifted, vendored or copied.

| Capability | Reference evidence | What CAIRN takes (design lesson) | CAIRN implementation |
|---|---|---|---|
| Hex/DDD scaffolding | `Meridian`, `punjab`, `barq` | Four-layer separation and explicit ports, enforced in CI | New `kernel/hex` and `contracts`, `import-linter` |
| Provider ports | `Meridian`, `mlops-aws`, `raas` | One contract per provider capability; a fake adapter for tests | New `provider-core` protocols; GCP adapter first |
| MCP kit | `punjab`, `byomcp`, `raas` | One server per bounded context; gateway auth and audit | New `kits/mcp`, `apps/mcp-gateway` |
| Evidence and ledger | `tda-uk-accelerator`, `dpdp`, `feedback` | Audit-before-effect; signed artefacts; offline verification | New `kernel/evidence` |
| Posture | `autoinfra`, `autoinfra_aws`, `clearvue-foundation` | One Finding model; scanner adapters | New `modules/posture` |
| Assessment and 6R | `agent-assess`, `infracc`, `anytoany` | Canonical estate model; explicit coverage and confidence | New `modules/estate` |
| Mapping registry | `cloudshift`, `drawio-gen`, `infracc` | Equivalence semantics; immutable releases | New `modules/mappings` |
| Design and diagrams | `drawio-gen` | One model drives diagram, plan and IaC | New `modules/design` |
| Transformation | `cloudshift_v2` (reference only) | Parse, detect, diff and validate as separate deterministic stages | New `transform-core` in Rust (ADR-015) |
| FinOps | `clearvue-foundation`, `Meridian` | Graded remediation; attribution and unallocated spend | New `modules/finops` |
| Loop kit | `Meridian`, `llmops`, `mlops` | Observe/Decide/Act with policy and evidence | New `kits/loop` |
| Observability | `llmops`, `punjab`, `raas` | OTel plus RED plus per-AI-call cost log | New `kernel/observability` |
| Console | `infracc`, `cockpit` | Assessment-first information architecture | New `apps/console` |

### 17.2 Prohibited reuse

- No source code, tests, schemas, Terraform, prompts, diagrams or configuration copied from the reference repositories.
- No vendoring, no git submodules, and no build-time or run-time dependency on a reference repository.
- No licence obligation is inherited, because no artefact is reused.
- Team members may read the repositories as evidence but must not paste from them.

### 17.3 Clean-room controls

- Every story that cites a reference repository records what was learned, not what was copied, in `docs/specs/reference-register.md`.
- Code review rejects unexplained similarity to a reference repository.
- If a third-party asset is ever considered, its licence is reviewed before use; that is an exception, not a default.
- The pattern catalogue (`CLOUD-ARCHITECTURE-PATTERNS.md`) is the primary reference artefact.

### 17.4 Why greenfield

- The repositories carry unresolved licence, provenance and quality questions; the source analysis already flags empty, frontend-only and POC repositories.
- Their interfaces are shaped by prototype assumptions that conflict with the kernel, tenancy and evidence contracts.
- Clean-room implementation produces one contract set, one test suite and no hidden coupling.
- The cost is schedule, not uncertainty: the build is larger, but the deliverable is legible.

---

## 18. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep after ADR acceptance | Delay | Freeze R1 scope; new scope requires a story and, if it changes a contract, an ADR |
| Full-model scope | R0 and R1 delay | Build the full v0 model before adapters; mark unused entities and version extensions |
| Mapping inaccuracy | Wrong design/TCO | Equivalence semantics, caveats, human review, evidence |
| Provider API coverage gaps | Incomplete assessment | Coverage indicators, file-import fallback, retries |
| Tenant isolation defect | Data exposure | Domain plus RLS plus adversarial tests on every path |
| Evidence service outage | Unverifiable Class C writes | Fail closed; queue only before effect |
| Overbuilding the console | Slow delivery | Assessment-first IA; four archetypes remain separate |
| Adapter multiplication | Schedule expansion | GCP-first; shared contract suite; AWS/Azure follow |
| Transformation risk | Customer impact | Preview-only in R3; sandbox; approval-bound Class C execution only in R4 |
| Premature Class C exposure | Blast radius, security review | No Class C before R4; kernel gate; read-only default credentials; isolated applier; recovery and incident runbooks |
| Open-source support load | Maintainer burnout | Public issue policy, SECURITY.md, no support promise without an engagement |
| Greenfield build cost | Higher effort than a lift/adapt plan | Scope discipline: GCP-only, one jurisdiction pack, assessment first |
| Reuse assumptions in earlier estimates | Schedule optimism | Re-baselined outlook in section 16.2; treat dates as discovery until R1 is proven |
| Reference contamination | IP or licence ambiguity | Clean-room controls in section 17.3; reference register; review checklist |
| ADR review drift | R0 delay | All ADRs accepted 9 November 2026; changes need a superseding ADR |
| Single maintainer | Unrealistic plan | Solo outlook in section 16.2; add maintainers on the critical path; agent assistance for implementation, not review |

---

## 19. Accepted decisions and their implementation impact

| Decision | Outcome | ADR |
|---|---|---|
| Repository shape | Monorepo, public at `solara-associates/cairn` | ADR-001, ADR-018 |
| Target cloud priority | GCP-first behind neutral contracts | ADR-005 |
| Data stores | Cloud SQL PostgreSQL in `europe-west2`; BigQuery for analytics | ADR-007 |
| Mutation boundary | Class A/B/C plus recovery-oriented mutation classes with a formal compensation contract; no Class C before R4; kernel gate for all Class C | ADR-010 |
| Approval binding | Immutable revision rows; approval and execution bind to exact revision, hash, mutation class and recovery strategy | ADR-009 |
| Tenancy | Every entity classified; forced RLS; composite tenant/project keys; global mappings platform-published | ADR-012 |
| Idempotency | Tenant/project/operation/key scope; canonical request hash; replay returns original result; payload mismatch conflicts; record and outbox commit atomically | ADR-009, ADR-010 |
| Product boundary | SaaS-only multi-tenant; mid-market first; no supported customer-deployed edition | ADR-013 |
| AI provider policy | Gemini only behind ModelPort; no customer BYO key | ADR-014 |
| Evidence standard | Canonical signed JSON plus report; unique chain head; audit-before-effect; CAIRN-held keys | ADR-008 |
| Code provenance | Greenfield clean-room; no reuse | ADR-017 |
| Transformation engine | One clean-room Rust engine; Terraform and Python first | ADR-015 |
| Launch jurisdiction | United Kingdom pack | ADR-016 |
| Licence | Apache-2.0 | ADR-018 |
| Mapping approver | Allan Smeyatsky | ADR-004 |
| Timeline and team | Solo maintainer; R0 8-12 weeks; R1 9-15 months; ASAP, no hard date | Section 16.2 |

---

## 20. Definition of done for the first usable release

R0 + R1 + the MVP of R2 is done when:

1. A tenant admin can create a workspace and invite role-scoped users.
2. An authorized user connects one supported provider read-only and/or uploads estate and billing exports.
3. Ingestion records source, scope, parser version, timestamps, status and coverage; incomplete data is not zero.
4. Workloads and resources are normalized with provenance and conflicting observations preserved.
5. Posture findings and a cost baseline are visible with explicit coverage and assumptions.
6. 6R recommendations can be accepted, amended or rejected with reasons.
7. Target services resolve through a versioned registry, with approximate/unavailable/unresolved labelled.
8. An editable diagram and target-design summary generate from the same target model.
9. A human-readable report and a signed evidence package are produced and independently verifiable.
10. Tenant isolation, conformance, security and evidence tamper tests pass in CI.
11. No Class C operation is reachable; Class B mutations are authorized, tenant-scoped, idempotent and audited; assessment and design services remain read-only.
12. The repository is public under Apache-2.0 with a root README, SECURITY.md, CONTRIBUTING.md and no secrets in history.
13. The full execution-gate lifecycle has been demonstrated against a deterministic test adapter for every external mutation class, including recovery preconditions, and the adapter cannot be substituted with a production adapter.
14. No production provider execution adapter, execution credential or Class C endpoint exists.

---

## Appendix A - Package-to-module ownership map

| Module | Packages | Primary app |
|---|---|---|
| Tenancy and projects | `modules/tenancy`, `modules/projects` | api |
| Connections and ingestion | `modules/connections`, `modules/ingestion` | api, worker |
| Canonical estate | `modules/estate`, `contracts/estate` | api, worker |
| Posture | `modules/posture` | worker, api |
| FinOps | `modules/finops` | worker, api |
| Mapping registry | `modules/mappings`, `contracts/mapping` | api, worker |
| Design | `modules/design` | worker, api |
| Planning | `modules/planning` | worker, api |
| Modernize | `modules/transformation`, `transform-core` | worker, cli |
| Approvals | `modules/approvals`, `kernel/execution-gate` | api |
| Execution (R4) | `modules/execution`, `adapters/provider-*` | worker |
| Evidence | `modules/evidence-service`, `kernel/evidence` | api, worker |
| Reporting | `modules/reporting` | worker |
| Console | `apps/console` | console |
| MCP/A2A | `apps/mcp-gateway`, `kits/mcp`, `kits/a2a` | mcp-gateway |

## Appendix B - Backlog summary

| Release | Stories | Focus | Exit |
|---|---|---|---|
| R0 | 20 | Kernel, full model, conformance, tenancy matrix, deployment skeleton | Architecture acceptance gate passes; rules enforced in CI |
| R1 | 22 | Read-only assessment, workspace decisions, evidence, gate validation | Assessment end to end; no customer-environment mutation |
| R2 | 10 | Registry, patterns, target model, diagrams, plan preview | One model drives all design artefacts |
| R3 | 8 | Repository scan, transformation, diff, validation, execution package | Reviewable modernization proposal; no customer apply |
| R4 | 6 | Provider execution adapter, plan/apply/drift, rollback, console | Controlled Class C writes with evidence |
| R5 | 6 | FinOps, LLMOps/MLOps, MCP/A2A, resilience, packs | Operational loops with governed remediation |
| **Total** | **72** | | |

Sizes are greenfield build sizes. The earlier reuse-dependent timeline is withdrawn; see section 16.2. The revision/approval model and deterministic gate harness are in R1; production Class C execution remains in R4 under ADR-010.

## Appendix C - Glossary additions

| Term | Meaning in this specification |
|---|---|
| Canonical estate model | Versioned, provider-neutral representation of resources, workloads, dependencies, findings and costs with provenance |
| Mapping release | Immutable, versioned set of service, region and jurisdiction mappings |
| Plan revision | Immutable snapshot of a migration plan; approvals bind to its hash |
| Evidence package | Signed JSON record of inputs, provenance, versions, decisions and outputs |
| Class A operation | Read-only operation; no persisted change to a customer or project decision |
| Class B operation | CAIRN workspace mutation; requires authorization, tenancy, idempotency and audit, but does not mutate a customer environment |
| Class C operation | Governed customer-environment mutation; requires the kernel execution gate, immutable revision approval, audit-before-effect, evidence and recovery handling |
| Mutation class | Recovery-oriented classification of a command: read-only, internal, reversible external, compensatable external or irreversible external |
| Reversible external mutation | A Class C change with a tested rollback action defined before authorization |
| Compensatable external mutation | A Class C change with no direct undo but a defined compensating action and trigger validated before authorization |
| Irreversible external mutation | A Class C change that cannot be rolled back; requires explicit risk acceptance, blast-radius declaration and preflight where supported |
| Compensation contract | The declared strategy, preconditions, authority requirements, evidence requirements and failure handling for a mutation's recovery; validated against the mutation class before authorization |
| Recovery plan | The immutable artifact, referenced by the approval, that records a mutation's compensation contract |
| Assessment plane | All read-only collection, normalization, assessment and design capability; structurally unable to apply changes |
| Execution plane | Separately credentialed capability that applies approved changes; not provisioned before R4 |
