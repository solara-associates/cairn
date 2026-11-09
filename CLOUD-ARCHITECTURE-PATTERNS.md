# Cloud Architecture Patterns

### A pattern catalogue and platform blueprint distilled from the 43 archived repositories in the `asmeyatsky-work` GitHub organization

Prepared: 9 November 2026
Source of truth: `github.com/asmeyatsky-work` (43 repositories, all archived at time of analysis)
Local analysis clone: shallow clones of every repository, README/architecture docs/manifests/IaC inspected

---

## 1. Purpose and how to read this

You asked for two things:

1. A cloud architecture pattern catalogue covering every solution in the archived `asmeyatsky-work` organization.
2. A basis for a new **cloud modernization platform** that reuses the architecture platforms already built in those repositories.

This document delivers both:

- **Part A** maps the 43 solutions into capability clusters.
- **Part B** extracts the reusable architecture patterns, with the repositories that evidence each one.
- **Part C** defines the target blueprint for the new platform and a build sequence.
- **Part D** records coverage, gaps and the decisions you still need to make.

A note on certainty: statements below are derived from each repository's own README, PRD, architecture document and infrastructure files. Where a repository is a stub or a prototype, that is called out explicitly.

---

## 2. Portfolio at a glance

| Metric | Value |
|---|---|
| Repositories analysed | 43 |
| Archived | 43 of 43 |
| Repositories with Dockerfiles | 32 |
| Repositories with Terraform | 16 |
| Repositories with Helm or Kubernetes manifests | 4 |
| Repositories explicitly using MCP | 34 |
| Dominant language | Python, with Rust for hot paths and TypeScript/React for consoles |
| Dominant cloud | Google Cloud, with explicit AWS and Azure ports in the portability-focused repos |
| Dominant architecture style | Clean/Hexagonal + Domain-Driven Design, enforced in CI with `import-linter` |

### Capability clusters

| # | Cluster | Count | Repositories |
|---|---|---|---|
| A | FinOps and cost governance | 5 | `clearvue-foundation`, `Meridian`, `infracc`, `aws_to_gcp_cost`, `cloud-cost-genius-convert` |
| B | Foundation posture, security and compliance | 5 | `autoinfra`, `autoinfra_aws`, `vuln-reduction-platform`, `dpdp-compliance-platform-poc`, `nelc` |
| C | Migration and modernization engines | 9 | `cloudshift`, `cloudshift_v2`, `refactor`, `refactor2`, `newrefactor`, `anytoany`, `agent-assess`, `drawio-gen`, `tda-uk-accelerator` |
| D | MLOps and LLMOps | 3 | `mlops`, `mlops-aws`, `llmops` |
| E | Agentic platforms, MCP/A2A and customer experience | 15 | `cockpit`, `byomcp`, `martech`, `nexus-agentic`, `punjab`, `prism`, `planetpayment`, `sales`, `mmopt2`, `mmopt3`, `atttick`, `feedback`, `aival2`, `leadforge`, `coderev` |
| F | Data and analytics accelerators | 5 | `barq`, `taa`, `temenos_ldm_accelerator`, `fhir-omop`, `msm` |
| G | Resilience and sovereignty | 1 | `raas` |

Sovereignty and compliance also cut across clusters B, C and E (`tda-uk-accelerator`, `nelc`, `dpdp-compliance-platform-poc`, `raas`). They are treated as a cross-cutting pattern in Part B.

---

## 3. Part A: Solution catalogue

Legend for "Pattern signature":
- **Hex/DDD** = clean or hexagonal architecture with a domain-driven core and mechanically enforced layer direction.
- **MCP** = Model Context Protocol servers as the integration and agent boundary.
- **A2A** = agent-to-agent protocol and agent cards.
- **HITL** = human-in-the-loop approval gate or state machine.
- **IaC** = Terraform, Helm, Kubernetes or Cloud Build deployment assets.
- **Evidence** = provenance, audit chain, reconciliation or signed output.

### A. FinOps and cost governance

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `clearvue-foundation` | GCP cost guardrails plus foundation posture review for a large GCP estate. One repo, two workstreams, one unified report. | Hex/DDD, MCP, IaC, Evidence | Cloud Run MCP/SSE service, BigQuery billing export, Budgets, Spend Caps, Org Policy, Pub/Sub, Cloud Monitoring, Prowler, Steampipe, OPA, Gemini advisor, WeasyPrint | FinOps domain model (Budget, SpendThreshold, EscalationTier, KillAction), selective stop and disable-billing adapters, unified cost-plus-posture report |
| `Meridian` | Cross-cloud FinOps agent. Provider-portable cost governance with swappable LLM backends across AWS, Azure and GCP. | Hex/DDD, ports and adapters, MCP, HITL | Cloud Run, ECS/App Runner, Azure Container Apps; BigQuery, AWS CUR/Cost Explorer, Azure Cost Management; Vertex, Bedrock, Azure OpenAI; SQLite/Postgres audit | Canonical cost schema, `CostSourcePort`, `RemediationPort`, `ModelPort`, `AuditSinkPort`, `ObservabilityPort`; one container that serves MCP or web |
| `infracc` | Google Cloud Infrastructure Modernization Accelerator Suite. AWS BOM/CUR import, service mapping, TCO comparison, migration strategy and planning UI. | Config-driven mapping, 6R strategies, agentic frontend | Node/JavaScript backend, static frontend, AWS CUR ingestion, GCP/AWS/Azure pricing | AWS-to-GCP service map, CUR/BOM ingestion, TCO engine, rehost/replatform/refactor/repurchase/retire/retain model |
| `aws_to_gcp_cost` | Placeholder repository. | None | None (contains only `.keep`) | Nothing usable; treat as retired |
| `cloud-cost-genius-convert` | Lovable-generated Vite/React/Tailwind cost comparison UI prototype. | Frontend prototype | Vite, React, shadcn-ui, Tailwind, Lovable hosting | UI shell for cost comparison; no backend logic |

### B. Foundation posture, security and compliance

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `autoinfra` | GFPR, the GCP Foundation Posture Reviewer. Assesses landing zone, IAM, networking, DR and security, then emits a branded report with roadmap and Terraform snippets. | Hex/DDD, evidence, IaC, MCP-ready CLI | Prowler, Steampipe, OPA, Postgres, Gemini, WeasyPrint; Cloud Run job and customer-onboarding Terraform | Posture domain model, control catalogue, roadmap builder, read-only cross-org onboarding pattern |
| `autoinfra_aws` | AFPR, the AWS port of GFPR. Same assessment model, AWS services and Bedrock advisor. | Hex/DDD, cross-account read-only role | Prowler for AWS, Steampipe, OPA, Postgres, Bedrock, WeasyPrint; STS AssumeRole | Provider-parity proof for a multi-cloud posture module |
| `vuln-reduction-platform` | Agentic GCP vulnerability-reduction platform. Turns a noisy Orca estate into reviewed, measured actions. | Hex/DDD, ADK, AI-advisory with deterministic guardrail | Gemini 2.5 Pro/Flash, Orca, Artifact Registry, BigQuery, Cloud Run, Terraform | Guardrail that the model cannot bypass, inventory-to-baseline spine, quantified-reduction eval |
| `dpdp-compliance-platform-poc` | India DPDP compliance platform POC on AWS, engineered for on-prem portability. | Hex/DDD, consent ledger, IaC, Evidence | Rust consent ledger, FastAPI app, k3s/RKE2 on EC2, CloudNativePG, MinIO, Keycloak, Vault, Kafka, Redis, Helm, Terraform | Hash-chained consent ledger, portable open-source stack, Helm charts that re-home to on-prem |
| `nelc` | Sovereign AI operating layer reference implementation for e-learning, bilingual EN/AR. Consumption governance, model registry, grounded retrieval, tool-using agent with approval gate, audit. | Hex/DDD, MCP, HITL, evidence, sovereignty | Cloud Run, model registry, retrieval knowledge base, partner API management, audit | Sovereignty and residency controls, consumption governance, bilingual UX, deploy-config-as-gate (`check:deploy`) |

### C. Migration and modernization engines

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `cloudshift` | Secure, air-gapped AWS/Azure-to-GCP migration. Scans, plans, transforms, validates and audits code and Terraform. | Rust core plus Hex/DDD Python, config-driven patterns, Evidence | Rust core via PyO3, Python CLI/REST/WebSocket, optional local Ollama or Gemini, Cloud Run | 134 service-mapping patterns, detectors, diff and AST validation, air-gapped operation, audit report |
| `cloudshift_v2` | Universal GCP-oriented refactoring with Rust transformation core, CLI, web UI, Cloud Run API, Python bindings, LSP and VS Code extension. | Same as above plus LSP | Rust, PyO3/Maturin, Cloud Run, static UI | LSP and editor integration, pattern catalogue, single binary plus service surfaces |
| `refactor` | Universal Cloud Refactor Agent. Converts AWS/Azure SDK usage to GCP at repository scale. | Hex/DDD, multi-language migration | FastAPI plus frontend, Cloud Run, Cloud Build, Docker | Repository-level migration plan (MAR), language auto-detection, multi-language tests |
| `refactor2` | CMAS, the Cloud Migration Agent Suite. Multi-agent translation of AWS Python/Boto3 and Terraform to GCP, with synthesized validation tests. | Multi-agent translate plus validate | Python agents, Flask dashboard | Separate translation and validation agents, service mapping JSON, test synthesis |
| `newrefactor` | ADK-based refactor and validation agents that use the Toon structured format to cut LLM token usage. | ADK agents, token optimization | FastAPI, Google ADK, Gemini, Toon | Toon encode/decode utilities and prompt optimizer; measurable token savings |
| `anytoany` | Any-to-any migration engine. Collects an estate, reconciles it to one canonical model with provenance, finds design gaps, generates a target design for human review. | Canonical model, provenance, decision/execution plane split, HITL, IaC | Python, CLI, web, Terraform generation, Cloud Run deploy assets | Canonical estate model, provenance retention, destructive-change gate, create-only assessment plane enforced by tests |
| `agent-assess` | Cloud migration assessment for VMware and Hyper-V estates. Ingests RVTools/HVTools CSVs and produces migration reports. | Hex/DDD, assessment pipeline | FastAPI, CSV parsers, PDF generation, Cloud Run, IAP, Cloud Build | RVTools/HVTools ingestion, assessment API, IAP-hosted delivery pattern |
| `drawio-gen` | Multi-cloud architecture diagram compiler. Pattern plus cloud plus parameters in, editable `.drawio` out. | Compiler pipeline, config-driven service map | TypeScript, static bundle on Cloud Run, no backend or database | Pattern DSL, resolver, topology, layout, mxGraph emitter, `approximate`/`unavailable` service-map semantics |
| `tda-uk-accelerator` | UK-sovereign GCP landing zone plus replication of three data planes from an India estate, with signed reconciliation evidence. | IaC, sovereignty, evidence, idempotency | Terraform modules (landing zone, data migration, app tier), Cloud Build plan/apply/drift pipelines, Cloud Run | Landing-zone module, reconciliation object with no thresholdable percentage, audit-before-write guard, idempotency-key enforcement |

### D. MLOps and LLMOps

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `mlops` | Agentic MLOps lifecycle management with a seven-agent swarm on MCP. | Hex/DDD, multi-agent swarm, MCP, HITL | Vertex AI, GKE, Cloud Logging, Billing, Cloud Run; KS/chi-square/KL/PSI drift detection | Swarm coordination patterns, DAG orchestrator, self-healing loop, EU AI Act compliance, model registry |
| `mlops-aws` | AWS port of the MLOps orchestrator. | Same, AWS adapters | SageMaker Training/Endpoints/Batch Transform/Model Packages, S3, ECS Fargate, CloudWatch, Athena, IAM/STS, Bedrock | Explicit cloud adapter mapping table (port to provider service), India DPDP and responsible-AI compliance |
| `llmops` | LLMOps gateway. Observe, Decide, Act control loop governing LLM traffic across security, reliability, cost and observability. | Hex/DDD, control loop, MCP, multi-provider ports | Vertex, Anthropic, OpenAI, Cloud Run, BigQuery, Secret Manager, Terraform, React dashboard | Four-pillar gateway, per-pillar fail-open/fail-closed policy, per-AI-call cost attribution, four MCP control-plane servers |

### E. Agentic platforms, MCP/A2A and customer experience

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `cockpit` | Agentic Cloud Modernization Platform. Unified multi-cloud control plane with an agent hierarchy, natural-language co-pilot and migration factory. | Hex/DDD, HMAS hierarchy, A2A, MCP, multi-tenant | FastAPI plus React, 6 MCP servers, AWS/Azure/GCP adapters, OTLP | L3/L2/L1 agent hierarchy (EPA plus six specialists), agent cards, per-agent IAM, migration factory |
| `byomcp` | Bring-your-own MCP server plus A2A-to-MCP bridge for Gemini Enterprise. | MCP, A2A, OAuth | Cloud Run, StreamableHTTP, OAuth/JWT, OTel | MCP server kit, A2A bridge, OAuth against customer IdP, keyword MCP routing |
| `martech` | EVLOS Agentic AI Communication Platform. Decision agent, customer data mart and IQ layer, cache-augmented generation, voice sentiment, meta-monitor. | Hex/DDD, MCP, A2A, event-driven | FastAPI gateway, BigQuery or in-memory data mart, Vertex, PII redaction, transformation DAG | IQ layer projection pattern, decision-outcome append-only port, CAG, tenant-scoped MCP resources |
| `nexus-agentic` | NEXUS variant of the same platform for Aditya Birla Capital Digital. | Same as `martech` | Same | Same; useful as a second customer instantiation |
| `punjab` | PNB GenAI reference implementation. Nine bounded contexts, nine MCP servers, Rust hot path, full conformance map. | Hex/DDD, MCP per BC, Rust hot path, conformance harness | Rust, Python 3.12, TypeScript, Cloud Run, Cloud Armor, Artifact Registry, OTel, cosign, Kyverno | Conformance-as-code script, one-MCP-per-BC rule, coverage floor, property tests, sandboxed code assistant |
| `prism` | Unified commerce intelligence platform with eight bounded contexts. | Hex/DDD, MCP, event-driven, multi-tenant | FastAPI, Vertex/Gemini/Imagen, BigQuery, Vertex Vector Search, Pub/Sub, Firestore, Memorystore, Apigee, Cloud Run | Bounded-context map for commerce, UCP ingestion, tenant isolation at the domain level |
| `planetpayment` | Agentic commerce chatbot with SCA/3DS2, UCP convertibility and prompt-injection defenses. | ADK, MCP, guardrails, evidence | FastAPI SSE gateway, ADK/Gemini, MCP servers, Firestore/Spanner/KMS/BigQuery, Cloud Run, Terraform | Before/after model guardrails, price grounding, one-turn tool bridge from Pydantic schemas, HMAC webhook, rotating AES-GCM session envelope |
| `sales` | Searce Scout AI sales development agent. Researches accounts, maps pain to offerings, runs multi-channel outreach, builds slide decks. | Hex/DDD, six bounded contexts, MCP | FastAPI, Typer, Vertex, SQLAlchemy async, Salesforce/HubSpot, Gmail, LinkedIn, Google Slides, SEC EDGAR, Apollo | Account intelligence, stakeholder discovery, outreach sequence engine, deck generation |
| `mmopt2` | Cross-vertical portfolio optimizer for home-services bidding and budget intelligence. | Hex/DDD, MCP, DAG, approval FSM, HITL | FastAPI, Google Ads, SA360, Vertex, BigQuery, Firestore, Pub/Sub, Slack, Cloud Scheduler, Terraform | Risk-tiered approval state machine, scenario levers, blended KPI scoring |
| `mmopt3` | Autonomous PPC performance auditor. Detects profit drag and emits course-correction plans. | Hex/DDD, MCP, autonomous loop | BigQuery, Firestore, Vertex Gemini 2.5 Flash, Cloud Run, Cloud Scheduler, Pub/Sub, Secret Manager, Drive, Chat | Anomaly detection and root-cause scoring, MPI value object, plan delivery adapters |
| `atttick` | Staff-Echo voice intelligence and analytics platform for a contact centre. | Hex/DDD, analytics pipeline | FastAPI, Next.js 15/React 19, Gemini, BigQuery, Speech-to-Text, PII masking | Call-driver tagging, deflection analysis, quality scoring, parallel knowledge-plus-pricing-plus-AI workflow |
| `feedback` | LoopBack, a SOW-to-delivery feedback platform with four hard enforcement points. | Hex/DDD, MCP, polyglot persistence, HITL | FastAPI, 4 MCP servers, Postgres, BigQuery, Redis, Vertex, DLP, Salesforce/Zoho/ClickUp/Workspace/Slack | Estimation norms, guardrail policy, closeout and governance gates, analog grounding invariant |
| `aival2` | AI Value Studio. Rapid AI-transformation RoI qualification with deterministic scoring and ADK narrative. | Hex/DDD, ADK, deterministic core | FastAPI, Firestore, ADK, reportlab PDF, Secret Manager, Cloud Run | Financial baseline and AI Opportunity Score, executive business-case export |
| `leadforge` | Automated lead generation accelerator. Discover, enrich and score B2B contacts. | Hex/DDD, MCP | FastAPI, SQLAlchemy async, Postgres, Alembic, MCP | Lead discovery and scoring pipeline skeleton |
| `coderev` | Enhanced Code Review Platform. Ephemeral review environments, in-browser IDE, AI risk analysis and collaborative workflow. | Hex/DDD, ephemeral environments | Python API, domain/application/infrastructure/presentation layers | Review-environment orchestration and AI risk scoring model |

### F. Data and analytics accelerators

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `barq` | Configuration-driven financial reconciliation framework on BigQuery. Matches core-banking against third-party processor transactions with no code change when rules evolve. | Config-driven rules, Hex/DDD, DAG | BigQuery, Cloud Composer/Airflow, Cloud Run or GCE, GCS, Secret Manager, Cloud Monitoring | Config tables for accounts/rules/joins/filters/transformations, dynamic CTE SQL generator, carryover service |
| `taa` | Telco Analytics Accelerator. Turns BSS/OSS configuration into BigQuery DDL, Terraform, Dataflow pipelines, Airflow DAGs and compliance reports for ten jurisdictions. | Config-driven generation, multi-cloud, IaC, evidence | BigQuery, Dataflow, Airflow, Terraform, Helm/Kubernetes, Vertex notebooks, MCP | Jurisdiction rule packs, vendor mappings, artefact-pack generator, cost estimator |
| `temenos_ldm_accelerator` | Generates Logical Data Models from Temenos T24 banking tables and exports to BigQuery. | Hex/DDD, generator | FastAPI backend, React frontend, BigQuery, Terraform/Dataflow output, compliance packs | T24-to-LDM mapping, PII detection, lineage and quality rules, Saudi/UAE compliance |
| `fhir-omop` | FHIR R4 to OMOP CDM v5.4 data accelerator for Saudi healthcare compliance. | Hex/DDD, mapping DSL, multi-tenant | FastAPI, React, PostgreSQL, Docker Compose, JWT/RBAC, audit | Whistle-compatible mapping DSL engine, consent and tenant isolation, NCA ECC/PDPL/NPHIES controls |
| `msm` | Predictive revenue-per-click estimator. Near-real-time scoring plus training, reconciliation and dashboard. | Hex/DDD, polyglot, event-driven | Rust scoring on Cloud Run, Python Vertex AI Pipelines, BigQuery, Pub/Sub, Cloud Run jobs, Terraform, Workload Identity | Rust hot-path service, bounds calibration, prediction-versus-revenue reconciliation, circuit-breaker automation |

### G. Resilience and sovereignty

| Repository | What it does | Pattern signature | Runtime and cloud services | Reusable asset |
|---|---|---|---|---|
| `raas` | Resilience as a Service. Multi-cloud, sovereignty-aware, AI-driven failover, DR drills and evidence. | Hex/DDD, multi-cloud ports, MCP, A2A, HITL, evidence | FastAPI, Click CLI, React console, Firestore, Keycloak, Kubernetes, Terraform, Prometheus, OTel, 6 MCP servers, AWS/Azure/GCP adapters | One sovereignty rule consulted by every surface, workload/incident/failover/DR-drill/SLA/ compliance aggregates, DAG failover orchestration |

---

## 4. Part B: The reusable architecture patterns

These are the patterns that recur across the portfolio. Each is stated as a pattern you can adopt in the new platform, with evidence repos and the contract to standardise.

### P1. Enforced Clean/Hexagonal core with DDD

**Shape**

```
domain/          pure entities, value objects, domain services, events, ports
application/     use cases, commands, queries, DTOs, orchestration
infrastructure/  adapters, repositories, MCP servers, AI providers, config
presentation/    REST, CLI, web console, MCP transport
```

Dependencies point inward only. The domain imports no SDK. Every external dependency sits behind a `Protocol` port.

**Enforcement, not documentation.** The recurring rule in the portfolio is "a rule not in CI is not real":
- Python: `import-linter` contracts (`autoinfra`, `autoinfra_aws`, `mlops`, `mlops-aws`, `llmops`, `Meridian`, `vuln-reduction-platform`, `aival2`, `barq`, `feedback`, `punjab`, `raas`, `deep` set).
- TypeScript: `eslint-plugin-boundaries` (`msm`).
- Rust: Cargo workspace boundaries plus `cargo-deny` (`msm`, `punjab`, `cloudshift`).
- Conformance scripts: `punjab/scripts/conformance.py`, `tda-uk-accelerator` gates.

**Evidence:** almost every repository. The cleanest templates are `Meridian`, `cockpit`, `raas`, `punjab`, `barq`, `mlops`.

**What to standardise:** a shared Python scaffolding package with the four layers, `import-linter` config, frozen dataclasses, ports as `Protocol`, an in-memory adapter for every port, and a CI template. This becomes the "Hex Kit" for the new platform.

---

### P2. Ports and adapters as the cloud-portability seam

**Shape**

Define one canonical domain model and a port per capability. Provide provider adapters behind the same port.

```
Domain port          GCP adapter                 AWS adapter                 Azure adapter
CostSourcePort   ->  BigQuery billing        ->  CUR / Cost Explorer     ->  Cost Management
RemediationPort  ->  budgets / spend caps    ->  budgets / IAM policy     ->  budgets / policy
ModelPort        ->  Vertex / Gemini         ->  Bedrock / Claude         ->  Azure OpenAI
TrainingPort     ->  Vertex AI               ->  SageMaker                ->  Azure ML
DeploymentPort   ->  Cloud Run / GKE         ->  ECS / App Runner         ->  Container Apps
DatasetPort      ->  BigQuery / GCS          ->  S3 / Glue / Athena       ->  ADLS / Synapse
MonitoringPort   ->  Cloud Monitoring        ->  CloudWatch               ->  Azure Monitor
AuditPort        ->  Cloud Logging / BQ      ->  CloudWatch / S3          ->  Azure Monitor
```

**Evidence:**
- `Meridian` is the definitive multi-cloud ports-and-adapters reference (cost, remediation, model, audit, observability).
- `mlops-aws` contains an explicit port-to-service mapping table that is the model for a provider matrix.
- `raas` implements AWS, Azure and GCP adapters behind one control plane.
- `cloudshift` and `refactor` implement provider-to-provider transformation patterns.

**What to standardise:** a `provider-adapter` contract package and a provider conformance test suite. Every adapter must pass the same contract tests, using in-memory fakes in CI.

---

### P3. MCP-native bounded contexts

**Shape**

One MCP server per bounded context. Tools are writes, resources are reads, prompts are reusable workflows. The MCP server validates and delegates; it contains no business logic.

**Rules that recur:**
- One MCP per bounded context (`punjab` has 9, `raas` has 6, `cockpit` has 6, `feedback` has 4, `llmops` has 4).
- Tools equal writes, resources equal reads (`byomcp`, `prism`, `punjab`).
- OAuth against the customer IdP; per-key tool allowlists; per-agent RBAC (`mlops`, `byomcp`).
- StreamableHTTP or SSE transport on Cloud Run (`byomcp`, `mlops`).
- No state in the MCP layer; session state is threaded immutably.

**Evidence:** `punjab`, `raas`, `cockpit`, `byomcp`, `prism`, `planetpayment`, `feedback`, `llmops`, `mlops`, `mlops-aws`, `martech`, `nexus-agentic`, `vuln-reduction-platform`, `mmopt2`, `mmopt3`, `sales`, `barq`, `taa`, `tda-uk-accelerator`.

**What to standardise:** an MCP server kit with transport, OAuth middleware, tool/resource registration, audit hooks, OTel spans, a conformance test, and a generated tool manifest.

---

### P4. A2A interoperability and agent cards

**Shape**

Agents exchange A2A messages (`POST /v1/message:send`). Each agent publishes an agent card. A bridge translates A2A to MCP when the host platform cannot consume MCP directly.

**Evidence:**
- `byomcp/byomcp-a2a-bridge` is the reference bridge: A2A in, keyword routing, StreamableHTTP MCP session, tool call, A2A response out.
- `cockpit` uses A2A agent cards for the L1/L2/L3 hierarchy.
- `martech` and `nexus-agentic` use A2A agent discovery alongside MCP.

**What to standardise:** an A2A gateway module and an agent-card schema so any bounded context can be exposed as a host-platform agent.

---

### P5. Agent hierarchy and orchestration

**Shape**

Three recurring orchestration models:

1. **Hierarchical (HMAS):** L3 executive planning agent orchestrates L2 specialists, which delegate to L1 workers. `cockpit` implements EPA plus six specialists (RSA, FIA, GA, MVA, DOA, PMA).
2. **Swarm and pipeline:** seven specialist agents with five coordination patterns (orchestrator-worker, swarm, hierarchical, mesh, pipeline). `mlops` and `mlops-aws`.
3. **DAG orchestrator:** dependency-aware workflow execution with automatic parallelisation (`asyncio.gather`). Used in `mlops`, `barq`, `raas`, `mmopt2`, `feedback`, `atttick` workflows.

**Rules:** immutable session state, frozen domain models, parallel independent steps, explicit state-transition guards.

**What to standardise:** a shared `orchestrator` package providing a DAG runner, retry with jitter, timeout, circuit breaker and event bus. This is lifted almost unchanged from `mlops`, `barq`, `raas` and `clearvue-foundation`.

---

### P6. AI advisory, deterministic bounds

**Shape**

The LLM is advisory. Deterministic code owns the decision and bounds the action. Model output is schema-validated before it can influence state.

**Evidence:**
- `Meridian`: "the reasoning LLM is advisory ... the deterministic `domain.policy` always bounds the action. AI output is schema-validated before it can influence state."
- `vuln-reduction-platform`: "deterministic engines do the work; LLM agents make the judgment calls; a guardrail the model cannot bypass keeps every irreversible action gated."
- `planetpayment`: `before_model_callback` scrubs PAN/CVV and envelope forgery; `after_model_callback` enforces price grounding; hallucinated prices are rewritten.
- `nelc`: gap detection is deterministic rather than model-driven.

**What to standardise:** a "bounded agent" wrapper that takes a deterministic policy, a Pydantic output schema and a guardrail, and rejects any model output that fails validation.

---

### P7. Human-in-the-loop gates and approval state machines

**Shape**

Irreversible or high-risk actions pass through an explicit gate. Gates are risk-tiered, revision-scoped and fail closed.

**Evidence:**
- `mmopt2`: `PENDING_APPROVAL -> APPROVED -> EXECUTING -> COMPLETE -> ROLLED_BACK`, with risk-tiered roles (`APPROVE_HIGH_RISK` required for high risk).
- `anytoany`: destructive and recreate decisions stop at a gate; approval is scoped to one plan revision and does not carry forward.
- `tda-uk-accelerator`: `AuditGuard` appends before the effect; if the audit chain is unreachable the write is denied.
- `llmops`: risk triggers an asynchronous human gate; fail modes are per pillar.
- `nelc`, `raas`, `feedback`: approval and governance gates.

**What to standardise:** a gate engine with risk tiers, named approvers, plan-revision binding, append-only audit-before-effect, and idempotency keys.

---

### P8. Observe, Decide, Act control loop

**Shape**

A closed loop that observes a signal, applies policy, decides, acts and records evidence. The same loop recurs in FinOps, LLMOps, self-healing MLOps and resilience.

**Evidence:**
- `Meridian`: Observe -> Decide -> Act for cost.
- `llmops`: the same loop across security, reliability, cost and observability.
- `mlops`: self-healing Observe -> Analyze -> Decide -> Act with drift remediation and alerting.
- `clearvue-foundation`: spend evaluation, action decision, daily velocity guard.

**What to standardise:** a generic loop package with pluggable observers, policy, evaluators, actors and evidence sink. This is the single most reusable runtime primitive in the portfolio.

---

### P9. Evidence, provenance and reconciliation

**Shape**

Every claimed outcome is backed by an artefact a reviewer can inspect. Provenance is retained. "Unobserved" is distinct from "zero". Numbers that cannot be trusted are not exposed.

**Evidence:**
- `tda-uk-accelerator`: a reconciliation report deliberately exposes no percentage; severity is ordered `pass < accepted_exception < mismatch < unverified`; an empty result is never evidence.
- `anytoany`: retains the provenance of every fact; two systems of record can disagree and both readings are kept.
- `clearvue-foundation` and `vuln-reduction-platform`: quantified outcomes and measured reduction.
- `dpdp-compliance-platform-poc`: hash-chained consent ledger with a live tamper demo.
- `planetpayment`: `sha256` before/after hashes in every mutating use case.

**What to standardise:** an evidence package (signed JSON report plus human-readable render), a provenance model, and a ledger adapter. This is a differentiator for a modernization platform because clients increasingly ask "prove it".

---

### P10. Configuration-driven rules and generators

**Shape**

Business rules and mapping tables live in configuration, not code, so they can evolve without a release.

**Evidence:**
- `barq`: `recon_accounts`, `recon_rules`, `rule_join_conditions`, `source_filters`, `column_transformations`; dynamic CTE SQL generation.
- `cloudshift` / `cloudshift_v2`: YAML pattern catalogue with 134 service mappings and a pattern engine.
- `drawio-gen`: pattern YAML plus `data/service-map.yaml` with `approximate` and `unavailable` semantics.
- `taa`: jurisdiction packs and vendor mappings.
- `infracc`: AWS-to-GCP service mapping and 6R strategies.

**What to standardise:** a versioned mapping-registry service with validation, region allowlists, and a generator interface. This is the engine behind assessment, planning, code migration and diagrams.

---

### P11. Data and analytics lakehouse

**Shape**

Ingest to BigQuery, process with Dataflow or Airflow/Composer, serve from Cloud Run, model with Vertex, stream through Pub/Sub, keep raw and curated layers.

**Evidence:**
- `msm`: Cloud Run scoring, Vertex AI Pipelines, BigQuery raw and view layers, four Pub/Sub topics, GCS artefacts, Terraform.
- `barq`: BigQuery as the processing engine, Composer scheduling, GCS for SQL, Secret Manager.
- `taa`: BigQuery DDL, Dataflow, Airflow, Terraform generation for ten jurisdictions.
- `temenos_ldm_accelerator`, `fhir-omop`: generate schemas and load into BigQuery/PostgreSQL.
- `prism`, `martech`: BigQuery data mart plus vector search.

**What to standardise:** a data-platform module with ingestion contracts, raw/curated/consumption layers, lineage, PII classification and a schema-generation interface.

---

### P12. FinOps guardrails

**Shape**

Budgets, thresholds, escalation tiers, spend caps, selective stop, disable billing, cost attribution and a kill switch. Actions are graded: alert, throttle, cap, disable.

**Evidence:**
- `clearvue-foundation`: Budget, SpendThreshold, EscalationTier, KillAction; Budgets, Spend Caps, Org Policy, Pub/Sub, Monitoring; SelectiveStop and DisableBilling adapters.
- `Meridian`: `RemediationPort` with graded actions across three clouds.
- `llmops`: budget and velocity guard, routing and cache steering, per-AI-call cost attribution.
- `infracc`: TCO and cost comparison.

**What to standardise:** a FinOps module with a canonical cost schema, graded remediation, velocity guard and provider adapters. `clearvue-foundation` and `Meridian` are complementary: the first is deep on GCP guardrails, the second is broad on portability.

---

### P13. Posture scanning and remediation

**Shape**

Read-only onboarding, multi-engine scanning, deterministic scoring, AI-generated narrative, prioritised roadmap, Terraform snippets.

**Evidence:**
- `autoinfra` (GCP) and `autoinfra_aws` (AWS): Prowler, Steampipe, OPA, Postgres, Gemini/Bedrock, WeasyPrint; customer onboarding creates a read-only role.
- `vuln-reduction-platform`: Orca inventory, baseline, guardrail, measured reduction.
- `clearvue-foundation`: posture lifted from GFPR and unified with cost.

**What to standardise:** a scanner interface (Prowler, Steampipe, OPA, native APIs), a unified Finding model, a control catalogue and a roadmap generator. `clearvue-foundation` already lifts and unifies GFPR findings, so start there.

---

### P14. Sovereignty and residency

**Shape**

Region allowlists, residency sweeps, jurisdiction rule packs, data-fiduciary controls, consent, audit, and a single rule that every surface consults.

**Evidence:**
- `raas`: failover is a compliance event; the sovereignty rule cannot live in one adapter; it is one rule every surface consults.
- `tda-uk-accelerator`: UK-sovereign landing zone in a declared region; residency sweep that raises on empty results.
- `nelc`: residency and sovereignty controls, bilingual EN/AR, deployment-gated region checks.
- `dpdp-compliance-platform-poc`: DPDP consent ledger and on-prem portability.
- `taa`, `temenos_ldm_accelerator`, `fhir-omop`: jurisdiction packs (Saudi PDPL, UAE PDPL, SAMA, India DPDP, GDPR, POPIA, etc.).

**What to standardise:** a policy engine with a region catalogue, jurisdiction packs, a residency-sweep primitive and evidence output. This is a strong commercial differentiator for GCC/MENA, UK and India.

---

### P15. Infrastructure as code and runtime topology

**Shape**

Terraform for foundation and per-environment composition, Cloud Build for plan/apply/drift, Cloud Run for stateless services and jobs, Helm/Kubernetes for portable or on-prem workloads, Workload Identity instead of keys, Secret Manager or External Secrets.

**Evidence:**
- Terraform modules and environments: `tda-uk-accelerator` (landing zone, data migration, app tier; plan/apply/drift pipelines), `clearvue-foundation`, `autoinfra`, `autoinfra_aws`, `msm`, `raas`, `punjab`, `planetpayment`, `llmops`, `mlops-aws`, `feedback`, `mmopt2`, `vuln-reduction-platform`, `dpdp-compliance-platform-poc`, `cloudshift`.
- Helm/Kubernetes: `dpdp-compliance-platform-poc`, `raas`, `taa`, `cloudshift`.
- Portable open-source stack on Kubernetes: CloudNativePG, MinIO, Keycloak, Vault, Kafka, Redis (`dpdp`).
- Single-image, multi-runtime deployment: `Meridian` serves MCP or web and deploys to Cloud Run, ECS/App Runner or Azure Container Apps.

**What to standardise:** a Terraform module library (landing zone, network, IAM, data, runtime, observability, guardrails), environment composition, and a deployment interface with three targets: Cloud Run, GKE, and customer Kubernetes.

---

### P16. Security floor

**Shape**

The same controls recur:
- Pydantic validation at every boundary.
- Append-only audit on every write, with before/after hashes.
- Timeouts and circuit breakers on every external call.
- No secret defaults; Secret Manager or keyring.
- HMAC-verified webhooks.
- PAN/CVV scrubbing plus Luhn check.
- Prompt-injection defence and price/content grounding.
- PII detection and DLP redaction.
- JWT/RBAC and tenant isolation at the domain level.
- Non-root containers, `pip-audit`, CycloneDX SBOM, Trivy, cosign keyless signing, Kyverno verification.
- Sandboxed code execution (gVisor runtime class in `punjab`).

**Evidence:** `planetpayment`, `punjab`, `byomcp`, `dpdp`, `feedback`, `tda`, `raas`, `vuln-reduction-platform`, `clearvue-foundation`.

**What to standardise:** a security baseline package and CI policy set. This is non-negotiable for enterprise and public-sector clients.

---

### P17. Observability

**Shape**

OpenTelemetry traces, RED metrics, structured JSON logs with `correlation_id`, and a per-AI-call log recording prompt hash, token counts, latency and integer-micro-USD cost. Prometheus SLO rules and OTLP collectors where Kubernetes is used.

**Evidence:** `llmops`, `mlops`, `punjab`, `raas`, `tda`, `planetpayment`, `byomcp`, `clearvue-foundation`, `feedback`.

**What to standardise:** an observability package with a shared span schema, RED middleware, AI-call logger and dashboard templates. The per-AI-call cost log is a differentiator.

---

### P18. Testing and conformance gates

**Shape**

Coverage floor (typically 80%), property-based tests (Hypothesis), contract tests for ports and MCP, eval sets for AI quality, architecture conformance scripts, ADRs for every deviation, and provenance records.

**Evidence:**
- `punjab`: 27 import-linter contracts, 47 Hypothesis tests, 89 MCP tests, 6 integration, 3 end-to-end, conformance score.
- `vuln-reduction-platform`: eval sets and a quantified-reduction demo.
- `tda-uk-accelerator`: CI checks idempotency posture and gate evidence.
- Every major repo: ADRs under `docs/adr/`.

**What to standardise:** a conformance harness and an ADR template. The `punjab` conformance map is the best template.

---

### P19. Diagram and architecture synthesis

**Shape**

Pattern plus cloud plus parameters compiles to an editable diagram. The service map declares equivalences, approximations and unavailability; the renderer never invents a shape.

**Evidence:** `drawio-gen`, with a resolver, topology, layout and mxGraph emitter pipeline; static Cloud Run; `verify:icons` and `check:regions` CI gates.

**What to standardise:** a design-synthesis module that consumes the same mapping registry as the migration and assessment engines, so diagrams, plans and Terraform all come from one source of truth.

---

### P20. Migration assessment and 6R planning

**Shape**

Ingest estate data (RVTools, HVTools, AWS CUR, BOM, CSV, APIs), classify workloads, map services, apply 6R strategies (rehost, replatform, refactor, repurchase, retire, retain), compute TCO, and produce a roadmap.

**Evidence:** `agent-assess`, `infracc`, `anytoany`, `cloudshift`, `refactor`, `tda-uk-accelerator`.

**What to standardise:** an assessment pipeline with source adapters, a canonical workload model, a 6R classifier, a TCO engine and a report generator. `anytoany`'s canonical model plus `infracc`'s TCO plus `agent-assess`'s ingestion is a strong combination.

---

### P21. Code transformation compiler

**Shape**

Parse with Tree-sitter or AST, detect provider usage, apply pattern rules, generate a unified diff, validate the result, and emit an audit report. Keep performance-critical parsing and matching in Rust, expose to Python.

**Evidence:** `cloudshift` and `cloudshift_v2` (Rust core plus PyO3, 134 patterns, LSP), `refactor`, `refactor2`, `newrefactor`.

**What to standardise:** one transformation engine rather than four. `cloudshift_v2` is the most complete; `refactor` adds repository-level language detection; `refactor2` adds validation-test synthesis; `newrefactor` adds token-efficient structured prompting.

---

### P22. Multi-tenant SaaS isolation

**Shape**

`TenantId` is a domain-level concept, not a query parameter. Server-side filters enforce tenancy. Per-tenant model routing and per-agent IAM.

**Evidence:** `prism`, `martech`, `nexus-agentic`, `feedback`, `fhir-omop`, `Meridian` (per-tenant model routing).

**What to standardise:** a tenant context package with request-scoped tenant propagation and repository-level isolation tests.

---

### P23. Consent and tamper-evident ledger

**Shape**

An append-only, hash-chained ledger as its own deployable. Writes are isolated from the main application. A tamper demo proves detection.

**Evidence:** `dpdp-compliance-platform-poc` (Rust ledger), `tda-uk-accelerator` (audit chain gates the write), `feedback` (BigQuery append-only audit with separate IAM).

**What to standardise:** a ledger service with an HTTP contract and hash verification. Useful for consent, audit and evidence across the platform.

---

### P24. Reference-architecture conformance harness

**Shape**

A machine-readable map from each architectural rule to the code or CI check that enforces it, plus a script that reports conformance.

**Evidence:** `punjab` (`scripts/conformance.py`, 7/7 rules), `tda-uk-accelerator` (gates), `nelc` (`check:deploy`), `drawio-gen` (`check:regions`).

**What to standardise:** make this the first artefact of the new platform. It prevents the portfolio from drifting apart again.

---

## 5. Part C: Blueprint for the new cloud modernization platform

### 5.1 Design thesis

The portfolio already contains most of the modules a modernization platform needs. The problem is fragmentation: four code transformers, two posture reviewers, two FinOps agents, several MCP kits, and repeated clean-architecture scaffolding. The new platform should be a **composition layer over a shared kernel**, not a rewrite.

Three principles:

1. **One shared kernel, many modules.** Hex Kit, MCP Kit, Evidence Kit, Observability Kit, Security Kit, Mapping Registry.
2. **Deterministic core, AI advisory.** Every AI feature sits behind a policy and a schema, exactly as `Meridian`, `vuln-reduction-platform` and `planetpayment` already do.
3. **Evidence by default.** Every assessment, plan, migration and failover produces a signed, human-readable artefact.

### 5.2 Target module map

| Platform module | Responsibility | Primary source repos | Reuse level |
|---|---|---|---|
| **M0 Shared kernel** | DDD scaffolding, ports, in-memory adapters, config, DI, error model | `Meridian`, `cockpit`, `raas`, `punjab`, `barq` | Lift and standardise |
| **M1 Foundation and posture** | Landing-zone review, IAM, network, DR, security, remediation roadmap | `autoinfra`, `autoinfra_aws`, `clearvue-foundation` | Lift, unify Finding model |
| **M2 Assessment and TCO** | Estate ingestion, canonical model, 6R classification, TCO, roadmap | `agent-assess`, `infracc`, `anytoany` | Compose |
| **M3 Code and IaC modernization** | Scan, plan, transform, validate, audit for AWS/Azure-to-GCP | `cloudshift_v2`, `refactor`, `refactor2`, `newrefactor`, `cloudshift` | Consolidate to one engine |
| **M4 Architecture synthesis** | Pattern plus target cloud to diagram, plan and IaC | `drawio-gen`, `anytoany`, `tda-uk-accelerator` | Compose |
| **M5 Landing zone and IaC** | Terraform module library, environments, plan/apply/drift | `tda-uk-accelerator`, `clearvue-foundation`, `msm`, `raas`, `punjab` | Lift modules |
| **M6 Data platform** | Ingestion, lakehouse, reconciliation, schema generation, lineage | `barq`, `taa`, `temenos_ldm_accelerator`, `fhir-omop`, `msm` | Compose |
| **M7 AI/ML platform** | MLOps, LLMOps gateway, model registry, drift, governance | `mlops`, `mlops-aws`, `llmops` | Lift |
| **M8 Agentic control plane** | MCP registry, A2A gateway, agent hierarchy, co-pilot | `cockpit`, `byomcp`, `punjab`, `raas` | Lift kits |
| **M9 FinOps** | Cost schema, graded remediation, budgets, attribution | `Meridian`, `clearvue-foundation`, `llmops` | Lift |
| **M10 Resilience and sovereignty** | Failover, DR drills, residency, jurisdiction packs | `raas`, `tda-uk-accelerator`, `nelc`, `dpdp` | Lift |
| **M11 Governance and compliance** | Control catalogue, consent ledger, audit, evidence | `dpdp`, `tda`, `nelc`, `feedback`, `vuln-reduction-platform` | Compose |
| **M12 Delivery console** | Portfolio cockpit, migration factory, review and approval UI | `cockpit`, `infracc`, `coderev`, `feedback` | Compose |
| **M13 AI accelerators** | Vertical agents: sales, marketing, contact centre, PPC, RoI | `sales`, `martech`/`nexus-agentic`, `atttick`, `mmopt2`, `mmopt3`, `aival2`, `prism`, `planetpayment` | Optional vertical packs |

### 5.3 Shared kernel (M0) contents

Build these once:

- **Hex Kit:** four layers, `import-linter` config, frozen dataclasses, `Protocol` ports, in-memory adapters, DI container, settings.
- **MCP Kit:** transport (StreamableHTTP/SSE), OAuth middleware, tool/resource/prompt registration, RBAC, audit hooks, OTel spans, conformance tests.
- **A2A Kit:** message schema, agent cards, A2A-to-MCP bridge.
- **Loop Kit:** Observe -> Decide -> Act runtime with pluggable observers, policy, evaluators, actors and evidence sink.
- **Evidence Kit:** signed reports, provenance model, ledger adapter, human-readable renderer.
- **Mapping Registry:** versioned service maps, jurisdiction packs, region catalogues, `approximate`/`unavailable` semantics.
- **Observability Kit:** OTel, RED, structured JSON, per-AI-call cost log, dashboards.
- **Security Kit:** boundary validation, audit, timeouts, circuit breaker, secret resolution, PII/DLP, SBOM and signing policy.
- **Conformance Harness:** rule-to-check map plus CI template.

### 5.4 Canonical reference stack

| Concern | Default | Enforced by |
|---|---|---|
| Language | Python 3.12 for domain and orchestration | `pyproject.toml`, ruff, mypy |
| Hot path | Rust via PyO3 where latency or parsing matters | Cargo workspace, `cargo-deny` |
| UI | React/TypeScript, Vite | ESLint, boundary rules |
| Architecture | Clean/Hexagonal plus DDD | `import-linter`, CI |
| Integration boundary | MCP, with A2A for agent hosts | MCP Kit, conformance tests |
| Runtime | Cloud Run for stateless; GKE or customer Kubernetes for portable workloads | Terraform, Helm |
| Data | BigQuery for analytics; Postgres for OLTP; Firestore for config | Terraform modules |
| Streaming | Pub/Sub; Dataflow or Airflow for batch | Terraform, DAG definitions |
| AI | Vertex/Gemini default; Bedrock and Azure OpenAI behind `ModelPort` | provider contract tests |
| Identity | Workload Identity; OAuth/JWT; Keycloak for portable | Terraform, middleware |
| Secrets | Secret Manager; External Secrets or Sealed Secrets on Kubernetes | CI policy |
| Observability | OpenTelemetry plus RED plus per-AI-call log | SDK middleware |
| Deployment | Cloud Build plan/apply/drift; GitHub Actions for app CI | pipeline templates |
| Evidence | Signed JSON plus rendered report | Evidence Kit |

### 5.5 Cross-cloud service mapping (seed for the Mapping Registry)

Drawn from `cloudshift` (134 patterns), `infracc`, `mlops-aws`, `Meridian` and `taa`.

| Capability | AWS | Azure | GCP |
|---|---|---|---|
| Object storage | S3 | Blob Storage | Cloud Storage |
| NoSQL | DynamoDB | Cosmos DB | Firestore / Bigtable |
| Relational | RDS / Aurora | Azure SQL / PostgreSQL | Cloud SQL / AlloyDB |
| Cache | ElastiCache | Azure Cache for Redis | Memorystore |
| Serverless compute | Lambda | Azure Functions | Cloud Functions / Cloud Run |
| Containers | ECS / EKS / Fargate | AKS / Container Apps | GKE / Cloud Run |
| Messaging | SQS / SNS | Service Bus / Event Grid | Pub/Sub |
| Streaming | Kinesis | Event Hubs | Pub/Sub / Dataflow |
| Batch ETL | Glue / EMR | Data Factory / Databricks | Dataflow / Dataproc |
| Warehouse | Redshift | Synapse | BigQuery |
| Orchestration | Step Functions / MWAA | Data Factory / Logic Apps | Workflows / Composer |
| Secrets | Secrets Manager | Key Vault | Secret Manager |
| Identity | IAM / STS | Entra ID | Cloud IAM / Workload Identity |
| Monitoring | CloudWatch | Azure Monitor | Cloud Monitoring / Logging |
| API management | API Gateway | API Management | Apigee / API Gateway |
| CDN | CloudFront | Front Door / CDN | Cloud CDN |
| DNS | Route 53 | Azure DNS | Cloud DNS |
| ML training | SageMaker | Azure ML | Vertex AI |
| LLM | Bedrock | Azure OpenAI | Vertex AI / Gemini |
| Kubernetes | EKS | AKS | GKE |
| IaC | CloudFormation | ARM / Bicep | Deployment Manager / Terraform |

### 5.6 Recommended build sequence

**Phase 0 - Consolidation (2-3 weeks).**
Create the monorepo or multi-package repo, lift the shared kernel from `Meridian`, `punjab`, `raas` and `barq`, stand up the conformance harness, and freeze the mapping registry schema.

**Phase 1 - Assess and prove (4-6 weeks).**
Ship M1 (posture) and M2 (assessment/TCO) first. These are read-only, low-risk, and immediately demoable. Combine `autoinfra`/`autoinfra_aws` with `agent-assess` and `infracc`. Produce one evidence report that covers posture, cost and migration readiness.

**Phase 2 - Plan and design (4-6 weeks).**
Add M4 (architecture synthesis) and the planning half of M3. Use `drawio-gen` plus `anytoany`'s canonical model so the diagram, the plan and the Terraform come from one source.

**Phase 3 - Modernize (6-10 weeks).**
Consolidate `cloudshift_v2`, `refactor`, `refactor2` and `newrefactor` into one transformation engine. Ship M5 landing-zone modules from `tda-uk-accelerator`.

**Phase 4 - Operate (6-8 weeks).**
Add M7 (MLOps/LLMOps), M8 (agentic control plane), M9 (FinOps) and M10 (resilience). These give the platform a post-migration operating story.

**Phase 5 - Vertical packs (ongoing).**
Package `martech`/`nexus-agentic`, `sales`, `atttick`, `mmopt2`, `mmopt3`, `aival2`, `prism` and `planetpayment` as optional accelerators, each on the shared kernel.

### 5.7 What "all architecture platforms in this repo" means in practice

The portfolio contains four distinct platform archetypes that should remain separate products on one kernel:

1. **Assessment platform:** posture plus cost plus migration readiness (M1, M2, M9).
2. **Modernization platform:** code/IaC transformation plus design plus landing zone (M3, M4, M5).
3. **Agentic operations platform:** MCP/A2A control plane plus MLOps/LLMOps plus FinOps plus resilience (M7, M8, M9, M10).
4. **Vertical accelerator platform:** reusable domain packs (M13) built on the same kernel.

Trying to collapse all four into a single UI too early is the main architectural risk. Keep them as separate deployables that share M0 and the Mapping Registry.

---

## 6. Part D: Coverage, caveats and decisions

### 6.1 Coverage check

All 43 repositories in `asmeyatsky-work` were cloned and inspected. Every repository appears in the catalogue:

- Cluster A: `clearvue-foundation`, `Meridian`, `infracc`, `aws_to_gcp_cost`, `cloud-cost-genius-convert`
- Cluster B: `autoinfra`, `autoinfra_aws`, `vuln-reduction-platform`, `dpdp-compliance-platform-poc`, `nelc`
- Cluster C: `cloudshift`, `cloudshift_v2`, `refactor`, `refactor2`, `newrefactor`, `anytoany`, `agent-assess`, `drawio-gen`, `tda-uk-accelerator`
- Cluster D: `mlops`, `mlops-aws`, `llmops`
- Cluster E: `cockpit`, `byomcp`, `martech`, `nexus-agentic`, `punjab`, `prism`, `planetpayment`, `sales`, `mmopt2`, `mmopt3`, `atttick`, `feedback`, `aival2`, `leadforge`, `coderev`
- Cluster F: `barq`, `taa`, `temenos_ldm_accelerator`, `fhir-omop`, `msm`
- Cluster G: `raas`

### 6.2 Caveats

- `aws_to_gcp_cost` is empty (only a `.keep` file). It is listed for completeness and contributes no pattern.
- `cloud-cost-genius-convert` is a Lovable-generated frontend prototype with no backend logic.
- `leadforge` has no README in the archived tree; its purpose is taken from `pyproject.toml`.
- `newrefactor` has no README; its purpose and architecture are inferred from `main.py`, the `agents/` tree and `TOON_INTEGRATION.md`.
- `infracc` has no root README; its capabilities are taken from `documentation/ARCHITECTURE.md` and `documentation/APPLICATION_CAPABILITIES.md`.
- Several repos are POCs or demos rather than production systems. The catalogue describes what each repo claims and contains, not an independent production audit.
- Counts of "repositories using MCP" and similar are based on documentation mentions and may overstate runtime usage in prototype repos.

### 6.3 Decisions needed from you

1. **Repository shape.** One monorepo with packages per module, or a small number of repos (kernel, assessment, modernization, operations, vertical packs)? The portfolio's current fragmentation suggests a monorepo or at least a shared kernel package.
2. **Target cloud priority.** GCP-first with AWS/Azure parity (the portfolio's bias), or provider-neutral from day one? `Meridian` proves neutrality is feasible; it costs roughly 2-3x the adapter work.
3. **Product boundary.** Is the new platform an internal delivery accelerator for Searce-style engagements, or a commercial multi-tenant SaaS? The answer changes M12 and the security/tenancy scope.
4. **AI provider policy.** Gemini-only for depth, or multi-provider via `ModelPort` from day one? `llmops` and `Meridian` already implement the multi-provider seam.
5. **Evidence standard.** Do clients require signed, verifiable evidence (audit chain, attestation) or is a rendered PDF report sufficient? This determines whether M11 includes the ledger from `dpdp` and the audit-before-write guard from `tda`.
6. **Consolidation appetite.** Are you willing to retire three of the four code transformers (`refactor`, `refactor2`, `newrefactor`) in favour of one engine derived from `cloudshift_v2`? Keeping all four will slow the platform down.
7. **Timeline and team size.** The Phase 0-5 sequence assumes a small platform team; the order is chosen so each phase is independently demoable.

### 6.4 Highest-leverage reuse (if you only do five things)

1. **Lift `Meridian`'s ports-and-adapters model** as the kernel's provider seam.
2. **Lift `punjab`'s conformance harness and MCP-per-BC discipline** as the quality bar.
3. **Lift `tda-uk-accelerator`'s evidence and audit-before-write model** as the trust layer.
4. **Consolidate the transformation engines** into one `cloudshift_v2`-derived pipeline.
5. **Unify `autoinfra` + `autoinfra_aws` + `clearvue-foundation`** into a single posture-and-cost assessment module.

---

## 7. Appendix: Pattern-to-repository index

| Pattern | Primary evidence repositories |
|---|---|
| P1 Clean/Hexagonal + DDD | `Meridian`, `cockpit`, `raas`, `punjab`, `barq`, `mlops`, `llmops` |
| P2 Ports and adapters portability | `Meridian`, `mlops-aws`, `raas`, `cloudshift` |
| P3 MCP-native bounded contexts | `punjab`, `raas`, `cockpit`, `byomcp`, `prism`, `feedback`, `llmops`, `mlops` |
| P4 A2A and agent cards | `byomcp`, `cockpit`, `martech`, `nexus-agentic` |
| P5 Agent hierarchy and DAG orchestration | `cockpit`, `mlops`, `mlops-aws`, `barq`, `raas`, `mmopt2` |
| P6 AI advisory with deterministic bounds | `Meridian`, `vuln-reduction-platform`, `planetpayment`, `nelc` |
| P7 Human-in-the-loop gates | `mmopt2`, `anytoany`, `tda-uk-accelerator`, `llmops`, `raas` |
| P8 Observe/Decide/Act loop | `Meridian`, `llmops`, `mlops`, `clearvue-foundation` |
| P9 Evidence and reconciliation | `tda-uk-accelerator`, `anytoany`, `clearvue-foundation`, `dpdp`, `planetpayment` |
| P10 Configuration-driven rules | `barq`, `cloudshift`, `drawio-gen`, `taa`, `infracc` |
| P11 Data and analytics lakehouse | `msm`, `barq`, `taa`, `temenos_ldm_accelerator`, `fhir-omop` |
| P12 FinOps guardrails | `clearvue-foundation`, `Meridian`, `llmops`, `infracc` |
| P13 Posture scanning and remediation | `autoinfra`, `autoinfra_aws`, `vuln-reduction-platform`, `clearvue-foundation` |
| P14 Sovereignty and residency | `raas`, `tda-uk-accelerator`, `nelc`, `dpdp`, `taa`, `temenos_ldm_accelerator`, `fhir-omop` |
| P15 IaC and runtime topology | `tda-uk-accelerator`, `clearvue-foundation`, `raas`, `punjab`, `dpdp`, `msm` |
| P16 Security floor | `planetpayment`, `punjab`, `byomcp`, `dpdp`, `feedback`, `raas` |
| P17 Observability | `llmops`, `mlops`, `punjab`, `raas`, `planetpayment`, `byomcp` |
| P18 Testing and conformance gates | `punjab`, `vuln-reduction-platform`, `tda-uk-accelerator`, `nelc` |
| P19 Diagram and architecture synthesis | `drawio-gen` |
| P20 Migration assessment and 6R planning | `agent-assess`, `infracc`, `anytoany`, `cloudshift`, `tda-uk-accelerator` |
| P21 Code transformation compiler | `cloudshift`, `cloudshift_v2`, `refactor`, `refactor2`, `newrefactor` |
| P22 Multi-tenant isolation | `prism`, `martech`, `nexus-agentic`, `feedback`, `fhir-omop`, `Meridian` |
| P23 Consent and tamper-evident ledger | `dpdp`, `tda-uk-accelerator`, `feedback` |
| P24 Conformance harness | `punjab`, `tda-uk-accelerator`, `nelc`, `drawio-gen` |
