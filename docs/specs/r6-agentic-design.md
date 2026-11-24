# R6 agentic release — design

**Status:** design only. Nothing described here is implemented. Target release `v0.6.0`.
**Decided by:** ADR-019 (agentic workflows), ADR-011 (MCP per bounded context, A2A bridge), ADR-014 (Gemini-only behind `ModelPort`), ADR-009/ADR-010 (approval binding, gated writes), ADR-008 (evidence).
**Run sheet and acceptance tests:** `docs/specs/r6-run-sheet.md`.
**Operator prerequisites:** `docs/specs/r6-operator-actions.md`.

This document is the design. It describes behaviour that does not exist yet, in the present tense where that reads better, and every section states what is already in the repository and what R6 adds.

---

## 0. Assumptions

These are the readings this design commits to. Each one is a place a reviewer can disagree before any code is written.

1. **"Agentic" means the three launch agents in §3, not a chat assistant.** There is no conversational surface in R6, no free-text "ask CAIRN anything", and no agent that spans projects.
2. **ADK is the framework.** Architectural Rules A1 names it as the default; this design takes the default, so no deviation ADR is needed. ADK is pinned to an exact version and lives only in `cairn_adapters.agent_adk`.
3. **Gemini on Vertex AI, application default credentials, no API keys.** ADR-014 fixes the provider; §2 fixes the authentication. There is no bring-your-own-key path and no key in code, config or environment defaults.
4. **A `PROPOSE` tool is not a mutation.** Generating a target model, a roadmap or a transformation diff writes CAIRN's own rows (a candidate revision, a run record) and touches no customer resource. Those are Class A/B operations against CAIRN's own store, already audited, and they are what an agent is allowed to cause. Anything reaching a customer's cloud account stays Class C and stays behind the execution gate.
5. **Tenancy's MCP server is read-only.** ADR-011 lists `tenancy` as a bounded context, but creating a tenant or granting a membership is a privileged platform mutation with no agent use case. Its server exposes reads only, and no agent toolset includes it (§4.1).
6. **Run state is Postgres, under the same forced RLS as every other tenant-owned table** (ADR-007, ADR-012). Agent runs and steps are durable because an approver has to be able to read a run's steps hours after it finished (A5.10).
7. **The deterministic loop is the default everywhere except the one opt-in live smoke test.** `make test` from a clean clone makes no network call and needs no GCP project, as it does today.

---

## 1. Component map

What exists today, and what R6 adds. Nothing in the "exists" column changes shape; R6 adds to it.

| Layer | Exists today | R6 adds |
|---|---|---|
| `cairn_kernel.model` | `ModelPort`, `ModelRequest` (already carries `agent_run_id`), `ModelResponse`, `ModelGateway` with deny-list / rate limit / circuit breaker / schema validation / per-call cost, `CostControlLoop` | `RunBudgetPolicy` in the gateway's pre-call chain (§5) |
| `cairn_kits.loop` | empty | the agent contract: `AgentSpec`, `AgentRun`, `AgentStep`, `RunBudget`, `BudgetLedger`, `AgentLoopPort`, `ToolInvokerPort`, `StepRecorder`, `DeterministicAgentLoop`, `PromptRegistry` |
| `cairn_kits.mcp` | `McpRegistry`, `BoundedContextServer`, duplicate-tool guard | `ToolCapability` on each registered tool, and the toolset guard that rejects a non-`READ`/`PROPOSE` tool |
| `cairn_kits.a2a` | empty | nothing — the bridge stays in `apps/mcp-gateway` where it already is (§6) |
| `cairn_adapters.model` | `FakeModelAdapter` only | `VertexGeminiAdapter` (§2) |
| `cairn_adapters` | — | `agent_adk`: ADK's implementation of `AgentLoopPort` (§7) |
| `cairn_modules` | assessment, planning (6R + roadmap), design, transformation, approvals, execution, estate, finops, mappings, ingestion, tenancy | `agents`: the three launch agents as application services (§3) |
| `apps/mcp-gateway` | `McpGateway` (OIDC auth + per-tool role), `posture` server, A2A bridge with per-server agent cards | seven bounded-context servers (§4), three agent cards (§6) |
| `apps/worker` | assessment run advancement | agent run execution off the queue |
| `apps/api` | assessment / design / transformation / approval-console routes | five agent routes (§8.1) |
| `apps/console` | 20 screens, hash router, `api.ts` bearer client | three screens (§8.2) |
| `prompts/` | does not exist | versioned prompt files (§9) |

### 1.1 Layering, and why the loop is split

`.importlinter`'s `kits-purity` contract forbids `cairn_kits` from importing `cairn_modules` or `cairn_adapters`. That is the constraint that shapes everything below, and it is a feature here:

```
apps/worker, apps/api            composition root: binds the real adapters
  │  ├── cairn_adapters.agent_adk   AgentLoopPort  (ADK; framework confined here)
  │  ├── cairn_adapters.model       ModelPort      (Vertex Gemini, or the fake)
  │  └── cairn_mcp_gateway          ToolInvokerPort (McpGateway.call_tool)
  ▼
cairn_modules.agents             the three agents: spec, contract validation, proposal persistence
  ▼
cairn_kits.loop                  the loop contract + the deterministic loop. Imports cairn_kernel only.
  ▼
cairn_kernel                     ModelGateway, evidence, audit, tenancy, classification
```

An agent therefore reaches a tool only through a port bound above it, and the package holding the loop cannot name an application service, a repository, a provider SDK, or the approval and execution gates. ADR-019 §3 is the statement; this is the mechanism.

---

## 2. The Gemini adapter

`cairn_adapters.model.vertex_gemini.VertexGeminiAdapter`, implementing `ModelPort.generate` and nothing else — the port has exactly one method, which is the point (ADR-014).

**Authentication.** Application default credentials, resolved by the Google client library itself. The adapter constructs its client with no credential argument, exactly as `cairn_adapters.evidence_kms` already does for KMS:

```python
def _default_client():            # lazy, so importing the adapter needs no GCP
    from google import genai      # pinned exact version
    return genai.Client(vertexai=True, project=..., location=...)
```

In Cloud Run the credential is the service's attached service account; on a developer machine it is `gcloud auth application-default login`. There is **no API key path**: no `api_key` parameter, no `GOOGLE_API_KEY` read, no key in code, config, environment defaults or Secret Manager. Nothing in R6 needs a secret value at all (`docs/specs/r6-operator-actions.md` §4 says so explicitly, and lists only names where a name is needed).

**Configuration.** Three values, read at startup and validated there (A5.13), all non-secret: `CAIRN_VERTEX_PROJECT`, `CAIRN_VERTEX_LOCATION` (`europe-west2`, consistent with ADR-007's residency choice — the adapter rejects a location outside the configured residency set rather than defaulting), `CAIRN_GEMINI_MODEL` (an exact model id, no alias, because the model id goes into evidence and an alias makes it unreproducible).

**Which adapter is wired.** `CAIRN_MODEL_ADAPTER` selects, and its **default is `fake`**. A deployment opts in to the real provider; a test, a clean clone and `make test` never do. Selecting `vertex` with any of the three values above missing fails at startup, not at first call.

**What the adapter does and does not do.**

- Translates `ModelRequest` → a Vertex generate call: prompt, `response_mime_type=application/json` with the request's `StructuredOutputExpectation.schema` as the response schema, `max_output_tokens` from `SafetyParameters`, and the request's `disallowed_categories` mapped to the provider's safety settings.
- Translates the response → `ModelResponse`: parsed JSON into `output`, `provider="vertex"`, `model` = the exact resolved model id (not the configured string, if the provider resolves it further), real `input_tokens`/`output_tokens` from usage metadata, measured `latency_ms`, and `SafetyMetadata` from the provider's safety verdicts — `flagged=True` whenever the provider blocked or flagged, never swallowed.
- Does **not** validate the response against the schema (that is `ModelGateway`'s job, and doing it in both places would let the adapter mask a `SCHEMA_INVALID` outcome the gateway must log), does not retry (the gateway's circuit breaker owns failure policy), does not log (the gateway owns `AiCallRecord`), and does not cache.
- Raises a typed kernel error for a provider failure, so the gateway's `except` path records `outcome="ERROR"` and trips the breaker.

**Pricing.** `default_price_table()` today prices only the fake's `("fake", "fake-model-v1")` pair, and `ModelPriceTable.rate_for` fails closed on an unregistered pair while `ModelGateway` catches that and logs `cost_micro_usd=0`. R6 registers a real rate for `("vertex", <model id>)` in the production composition root, so agent runs carry real cost and the R5-02b cost-control loop has something true to act on. An unpriced model is a conformance finding (§R-AGENT-10 in the run sheet), not a silent zero.

**Tests.** `FakeModelAdapter` stays the default and stays mandatory. The Vertex adapter's own unit tests inject a stub client object and assert the two translations and the error mapping — no network. Exactly one test touches a real provider:

- `tests/integration/test_vertex_gemini_live.py`, marked `@pytest.mark.live_model`, deselected by default in `pyproject.toml`'s `addopts`, and skipped unless `CAIRN_LIVE_MODEL_SMOKE=1` **and** the three Vertex settings are present. It makes one call with a tiny fixed prompt and a two-field schema, and asserts a schema-valid response with non-zero token counts. It is run by hand before a release, never in CI, and it is the only thing that catches ADK/provider drift.

---

## 3. The three launch agents

All three share one shape: read facts through MCP tools, reason over them, emit one structured proposal, validate that proposal against the domain contract, persist it as a candidate, and stop. None of them can approve or execute (ADR-019 §6). Where a proposal needs a decision, it enters machinery that already exists.

Common to all three:

- **Required actor.** A run is started by an authenticated `Principal`; `actor` is required on every step, never inferred (A7.actor). The starting principal is recorded as the proposer, so `check_separation_of_duties` blocks that same person from approving the output.
- **Required role dominates the toolset.** An agent's `required_role` must be at least the highest role any tool in its toolset requires, validated when the `AgentSpec` is constructed. Without that rule a run could start and then fail at step 30 on a `ForbiddenError` from the gateway — authorisation must be settled before a run spends anything. The assessment agent reads the control catalogue (`posture.get_control` already requires `AUDITOR`), so its `required_role` is `AUDITOR`; the design agent's is `ARCHITECT` and the modernize agent's is `ENGINEER`, from their `PROPOSE` tools. A judgement call on top of that: starting any agent run requires at least `ENGINEER`, because a run spends real model budget and `VIEWER` is a read-only role.
- **Tenant and project scope.** Both are fixed at run start, carried on every `ModelRequest` and every tool call, and enforced by the gateway's per-tenant authorisation and by RLS on the run tables.
- **Terminal states.** `PROPOSED`, `FAILED`, `BUDGET_EXCEEDED`, `CANCELLED`. Never `EXECUTED`.
- **Failure shape.** Domain-contract validation failing is not a retry: the run ends `FAILED` with the validation error recorded in the run's evidence. A proposal that fails validation is never persisted and never shown as a draft, because a half-valid proposal in front of an approver is worse than no proposal.

### 3.1 Assessment agent

**Purpose.** Explain a finished assessment in a reviewer's language: why each workload got the 6R disposition it got, what looks wrong in the data, and a draft summary a human will edit.

| | |
|---|---|
| `agent_id` | `assessment-explainer` |
| Inputs | `tenant_id`, `project_id`, `assessment_run_id` |
| Tools (all `READ`) | `assessment.get_run`, `assessment.get_results`, `assessment.coverage_report`, `assessment.get_decision`, `estate.list_workloads`, `estate.get_workload`, `mappings.resolve`, `posture.get_control`, `finops.get_baseline`, `finops.get_tco` |
| Output | `AssessmentNarrative` |
| Budget (initial) | 40 steps, 20 model calls, 300k tokens, 2,000,000 µUSD, 10 min |

`AssessmentNarrative`:

```
{ "run_id", "model_version", "mapping_version",
  "dispositions": [ { "workload_id", "disposition", "explanation",
                      "fact_refs": [...], "confidence_stated" } ],
  "anomalies":    [ { "kind", "subject_ref", "statement", "fact_refs": [...] } ],
  "summary_draft": "..." }
```

**Domain-contract validation** — all of these, every one a hard fail:

1. Every `workload_id` in `dispositions` exists in the run's results; no extras, no omissions.
2. Every `disposition` **equals the stored `DispositionDecision.disposition` exactly**. The agent explains a decision the deterministic 6R classifier already made; it does not re-decide, and a mismatch means the model invented a disposition. This is the single most important check on this agent.
3. Every `explanation` and every `anomaly` cites at least one `fact_ref` that resolves to a real fact in the run (an estate fact, a posture finding, a cost line). An uncited claim is rejected.
4. `confidence_stated` matches the stored `DispositionDecision.confidence` band; and the text may not describe an approximate or unavailable figure as exact (R-MAP-01). A `Confidence` band and a mapping `Equivalence`/`caveat` are reproduced, never paraphrased into certainty.
5. `model_version` and `mapping_version` equal the run's own, so the narrative cannot silently describe a different release's results (R-VER-01).

**Approval point.** The narrative is persisted as a **draft** attached to the assessment run and is marked as model-drafted wherever it is displayed. Including it in a signed evidence package requires a human accept through the existing approval console (`POST /v1/assessment-runs/{run_id}/narrative/approval`, built on the same `ApprovalRecord`/revision binding as every other approval). Nothing is published on the agent's authority. The individual 6R decisions keep their own existing accept/reject/amend path (`review_decision`) and the agent does not touch it.

### 3.2 Design agent

**Purpose.** Propose a target pattern and migration waves from the estate model and the accepted dispositions, with reasons an architect can argue with.

| | |
|---|---|
| `agent_id` | `design-proposer` |
| Inputs | `tenant_id`, `project_id`, `plan_id`, estate model version, pattern catalogue version, mapping release version |
| Tools | `estate.list_workloads`, `estate.get_dependencies` (`READ`), `design.list_patterns`, `design.get_pattern` (`READ`), `mappings.resolve` (`READ`), `assessment.get_results` (`READ`), `design.generate_target_model` (`PROPOSE`), `planning.generate_roadmap` (`PROPOSE`) |
| Output | `DesignProposal` |
| Budget (initial) | 60 steps, 30 model calls, 400k tokens, 3,000,000 µUSD, 15 min |

The two `PROPOSE` tools are the existing deterministic generators (`generate_target_model`, `generate_roadmap`). The agent chooses the pattern and the parameters and states why; the generators do the generating. The model does not write a target model by hand — it selects inputs for code that already produces a validated one. That split is deliberate: it keeps the artefact deterministic and keeps the model's contribution reviewable as a judgement rather than as output nobody can diff against anything.

`DesignProposal`:

```
{ "plan_id", "pattern_id", "pattern_catalogue_version",
  "mapping_release_version", "estate_model_version",
  "target_provider", "parameters": {...},
  "pattern_rationale": "...",
  "rejected_patterns": [ { "pattern_id", "reason" } ],
  "waves": [ { "wave_number", "workload_ids": [...], "rationale",
               "constraints_cited": [...] } ],
  "risks": [ { "statement", "fact_refs": [...] } ] }
```

**Domain-contract validation:**

1. `pattern_id` exists in the pattern catalogue **at the declared version**; `rejected_patterns` names only patterns in that catalogue.
2. `parameters` satisfy the pattern's own parameter contract — delegated to the existing `generate_target_model` resolution, which already rejects a bad parameter set. The agent's proposal is rejected if the generator rejects it.
3. Every workload with an **accepted** disposition appears in exactly one wave; no workload with a rejected or pending disposition appears at all.
4. Wave ordering respects the dependency edges the roadmap generator computes. A proposal whose wave numbers contradict `generate_roadmap`'s own topological result is rejected — the agent may propose constraints, not violate dependencies.
5. Every wave `rationale` cites at least one real constraint or dependency; every `risks` entry cites a fact ref.
6. The three version fields are carried and are the ones actually used (R-VER-01: diagram, plan and IaC share model, mapping and pattern versions).

**Approval point.** The proposal becomes a **candidate plan revision** — an immutable revision row like any other (ADR-009) — and enters the existing plan approval flow (`GET/POST /v1/plans/{revision_id}/approval`, approval comments, separation of duties). Diagram, IaC and report export remain unchanged and run from the approved revision. The agent cannot approve its own revision and is not a party to the approval.

### 3.3 Modernize agent

**Purpose.** Propose a transformation plan, run the existing Rust engine through its existing service, and explain every diff hunk so a reviewer can accept or reject it on the merits.

| | |
|---|---|
| `agent_id` | `modernize-proposer` |
| Inputs | `tenant_id`, `project_id`, approved plan revision id, source snapshot ref |
| Tools | `transformation.list_source_files`, `transformation.get_run`, `transformation.get_diff`, `transformation.get_manifest` (`READ`), `mappings.resolve` (`READ`), `transformation.run` (`PROPOSE`), `transformation.validate` (`PROPOSE`) |
| Output | `TransformationPlanProposal` |
| Budget (initial) | 80 steps, 40 model calls, 600k tokens, 5,000,000 µUSD, 20 min |

`transformation.run` invokes the existing `TransformationPort` (the clean-room Rust engine, ADR-015) through the existing transformation service. It produces a manifest and a unified diff in CAIRN's own store. It writes nothing to a customer repository, and applying a diff anywhere is a separate Class C operation behind the execution gate — the agent has no tool for it.

`TransformationPlanProposal`:

```
{ "plan_revision_id", "run_id", "manifest_hash",
  "scope": { "file_paths": [...], "excluded": [ { "path", "reason" } ] },
  "explanations": [ { "entry_id", "file_path", "hunk_ref", "outcome",
                      "mapping_version", "equivalence", "caveat",
                      "explanation", "reviewer_attention": bool } ],
  "unsupported": [ { "entry_id", "engine_reason", "suggested_manual_step" } ],
  "validation_summary": { ... } }
```

**Domain-contract validation:**

1. `manifest_hash` equals the hash of the manifest actually stored for `run_id`. The agent may not explain a diff that is not the one on record — this is the check that stops a plausible explanation attaching to the wrong artefact.
2. Exactly one `explanations` entry per manifest entry: no entry unexplained, no explanation without an entry.
3. `outcome` for each entry equals the engine's own `ManifestOutcome` (applied / skipped / unsupported). The agent reports the engine's verdict; it does not grade it.
4. `unsupported[].engine_reason` is the reason **the engine gave**, reproduced, not an invented one. An `engine_reason` not matching the manifest's recorded reason is a hard fail.
5. `equivalence` and `caveat` are copied verbatim from the mapping release for that resolution; a caveat may not be dropped, and an `APPROXIMATE` equivalence may not be described as exact (R-MAP-01).
6. `validation_summary` is the existing static-validation result for the run, not a model summary of it.

**Approval point.** The proposal and its explanations are attached to the existing transformation review thread (`POST /v1/transformations/{run_id}/review-comments`), posted as model-drafted and clearly attributed. The thread's existing blocking-comment semantics are unchanged: a blocked thread stays blocked. Applying anything to a customer repository or cloud account remains Class C behind the execution gate, with its compensation contract, and the agent has no path to it.

---

## 4. MCP servers for the remaining contexts

ADR-011 names eight bounded contexts; `posture` exists. R6 adds the other seven behind the same `McpRegistry` and the same `McpGateway` (OIDC authentication, per-tool role, audit), with no new transport and no second gateway.

Each tool below is declared with: an owning bounded context, a `ToolCapability` (`READ` or `PROPOSE`), the minimum tenant `Role` required, and the application service it calls. **No tool calls SQL or a provider SDK** (ADR-011); each handle calls the module's application service, exactly as `posture_server.py` does today.

### 4.1 Tool inventory

| Context | Tool | Cap | Min role | Calls |
|---|---|---|---|---|
| `tenancy` | `tenancy.get_project` | READ | VIEWER | projects service |
| | `tenancy.list_project_members` | READ | TENANT_ADMIN | projects service |
| `ingestion` | `ingestion.get_run` | READ | VIEWER | ingestion run service |
| | `ingestion.list_runs` | READ | VIEWER | ingestion run service |
| | `ingestion.get_coverage` | READ | VIEWER | ingestion run service |
| `estate` | `estate.list_workloads` | READ | VIEWER | estate workloads |
| | `estate.get_workload` | READ | VIEWER | estate workloads |
| | `estate.list_resources` | READ | VIEWER | estate normalize |
| | `estate.get_dependencies` | READ | VIEWER | estate workloads |
| `finops` | `finops.get_baseline` | READ | VIEWER | finops baseline |
| | `finops.get_tco` | READ | VIEWER | finops tco |
| | `finops.list_price_releases` | READ | VIEWER | finops pricing |
| `mappings` | `mappings.resolve` | READ | VIEWER | mappings resolver |
| | `mappings.get_release` | READ | VIEWER | mappings registry |
| | `mappings.list_releases` | READ | VIEWER | mappings registry |
| `design` | `design.list_patterns` | READ | VIEWER | pattern catalogue |
| | `design.get_pattern` | READ | VIEWER | pattern catalogue |
| | `design.get_target_model` | READ | VIEWER | design target model |
| | `design.generate_target_model` | PROPOSE | ARCHITECT | design target model |
| | `planning.generate_roadmap` | PROPOSE | ARCHITECT | planning roadmap |
| `transformation` | `transformation.list_source_files` | READ | VIEWER | transformation source |
| | `transformation.get_run` | READ | VIEWER | transformation runs |
| | `transformation.get_manifest` | READ | VIEWER | transformation runs |
| | `transformation.get_diff` | READ | VIEWER | transformation diff |
| | `transformation.run` | PROPOSE | ENGINEER | transformation engine service |
| | `transformation.validate` | PROPOSE | ENGINEER | transformation validation |

Assessment's tools (`assessment.get_run`, `assessment.get_results`, `assessment.coverage_report`, `assessment.get_decision`, all `READ`/VIEWER) are registered on the `ingestion`-adjacent **assessment** context, which ADR-011's list does not name separately; it is added as a ninth server rather than folded into `estate`, because its application service is `cairn_modules.assessment` and ADR-011's rule is one server per bounded context, not one per name in a four-year-old list. This is a deviation from ADR-011's enumeration and is recorded as such in the run sheet.

### 4.2 What is deliberately absent

No tool mutates a customer resource. No tool approves anything. No tool publishes a mapping release, creates a tenant, grants a membership, applies a diff, or runs a Terraform apply — those paths exist for human and API callers and are not registered as MCP tools at all in R6. A tool that is not registered cannot be mis-declared.

### 4.3 Per-server requirements

Each of the eight new servers needs, in the same unit that adds it:

- A `BoundedContextServer` whose `handle` dispatches by tool name and raises for an unknown one (the `posture_server.py` shape).
- Input validation at the boundary, schema-based, reject-by-default (A7.input-validation): every tool's arguments are a Pydantic model, and an unknown key is an error.
- An entry in `REQUIRED_ROLES`.
- A capability declaration (`READ`/`PROPOSE`).
- **A smoke test that instantiates the server and calls one real tool** (A8.mcp-smoke). Import success proves nothing.

---

## 5. Budget enforcement

Two halves, each where the resource is actually spent.

**In the loop (`cairn_kits.loop.BudgetLedger`).** Steps, model calls and wall clock. The ledger is debited *before* a step is attempted. An exhausted ledger terminates the run in `BUDGET_EXCEEDED`, seals the run's evidence, and returns — it does not raise past the caller, because a budget stop is a normal outcome, not an error.

**In `ModelGateway` (`RunBudgetPolicy`).** Tokens and cost, which only the gateway can see. `ModelRequest.agent_run_id` already exists; the policy keys on it and joins the gateway's existing pre-call chain:

```
deny-list → rate limit → circuit breaker → run budget → adapter.generate
```

The policy holds, per `agent_run_id`, the run's `max_total_tokens` and `max_cost_micro_usd` and the running totals the gateway already computes for its `AiCallRecord`. A call belonging to an exhausted run raises `RunBudgetExceededError` **before** `adapter.generate` is reached — the same fail-closed shape as the three policies already there, and the same test property: the adapter's call counter stays at zero past the block point.

Two fail-closed rules:

- A request **with** an `agent_run_id` for which no budget is registered is **refused**. Absent budget never means unlimited.
- A request **without** an `agent_run_id` is not an agent call and is unaffected — every non-agent caller of `ModelGateway` keeps its current behaviour.

Budgets interact with the existing R5-02b `CostControlLoop` rather than replacing it: the loop still watches tenant-wide spend and can `THROTTLE`/`STOP` by exhausting the rate limiter or forcing the breaker open. Per-run budgets bound one run; the cost-control loop bounds a tenant. Both are enforced, and a run can be stopped by either.

---

## 6. What the A2A bridge publishes

The bridge in `apps/mcp-gateway/a2a_bridge.py` today derives one `AgentCard` per registered MCP server and translates A2A tasks to MCP calls. R6 keeps that and adds cards for the three launch agents.

An agent card for a launch agent carries: `name` (`agent_id`), `version`, a one-line description, one **skill** per agent capability (`explain_assessment`, `propose_design`, `propose_transformation`), the input and output schema names, the declared budgets, the required role, and two fields that are the point of publishing at all:

- `propose_only: true` — stated on the card, not implied.
- `approval_endpoint` — where a proposal this agent produced goes for a human decision.

A skill that executes, applies, approves or mutates is **never published**, because no such skill exists (§4.2). An A2A task that names one resolves to no skill and is refused by the bridge's existing lookup.

The seven new MCP servers each gain a per-server card automatically, through the existing `agent_cards_for_registry` — no new code, and a card's skills are that server's declared tools with their capabilities.

Staging is unchanged: ADR-011 made MCP/A2A internal until R5 and customer-exposed thereafter. R6 does not change who may reach the gateway; it changes what is behind it.

---

## 7. The ADK adapter

`cairn_adapters.agent_adk`, the only place an ADK type appears. It implements `AgentLoopPort.run(spec, inputs, context) -> AgentRun`.

| Concern | How |
|---|---|
| Reasoning loop | ADK's agent runner drives plan → tool call → observation. CAIRN does not re-implement it (A6.framework). |
| Model calls | An ADK model implementation that **delegates every call to `ModelGateway.generate`**, passing the run's `agent_run_id`. No ADK code path reaches a provider SDK, so no agent model call escapes the deny-list, rate limiter, breaker, schema validation, cost accounting or run budget. This is the adapter's single most important property and has its own conformance rule. |
| Tools | Each name in `spec.toolset` becomes one ADK tool whose body calls `ToolInvokerPort.invoke(name, arguments)`. The adapter builds no tool that is not in the spec's closed list. |
| Capability guard | A pre-tool callback re-checks the invoked tool's declared capability and refuses anything not `READ`/`PROPOSE`. Redundant with the construction-time check in `AgentSpec` — deliberately, because this is the last gate before a tool actually runs. |
| Prompts | Resolved by id and version from `PromptRegistry`; the adapter passes no literal prompt (A6.prompts). |
| Steps | Each plan, tool call and observation is translated to an `AgentStep` and handed to `StepRecorder`. ADK's own session/event objects do not leave this package. |
| Budgets | The adapter debits `BudgetLedger` before each step and stops the run on exhaustion; the token/cost half is enforced by the gateway beneath it. |
| Framework confinement | Deleting the ADK import must produce compile errors only inside `cairn_adapters.agent_adk` (A6.port's own test), enforced by an import-linter contract. |
| Version | Pinned exactly in `packages/adapters/pyproject.toml`, with the SBOM and signature requirements R-SEC-02 already applies. |

`DeterministicAgentLoop` in `cairn_kits.loop` is the other implementation: it replays a scripted sequence of steps, debits the same ledger, records through the same `StepRecorder`, and produces an `AgentRun` indistinguishable in shape from ADK's. Every agent test, every API test and every console test runs against it. It makes no branching decision and selects no tool, which is why it is not a hand-rolled reasoning loop.

---

## 8. Console and API

The minimum to start a run, watch it, and decide on its proposal. Nothing more — no agent builder, no prompt editor, no run comparison.

### 8.1 API routes

Five, following the existing `routes_*.py` conventions (`APIRouter`, `Depends(get_principal)`, a required actor from the principal, typed Pydantic request bodies):

| Route | Purpose |
|---|---|
| `POST /v1/projects/{project_id}/agent-runs` | Start a run. Body: `agent_id`, inputs, optional budget override (only downward — an override may lower a budget, never raise it). Checks the agent's `required_role`. Enqueues; returns `202` with the run id. Idempotency: a client-supplied key, declared idempotent (A5.11). |
| `GET /v1/agent-runs/{run_id}` | Run header: agent id and version, state, actor, budgets and consumption, timestamps, terminal reason. |
| `GET /v1/agent-runs/{run_id}/steps` | Ordered steps: index, kind, tool name, prompt id and version, model id, tokens, cost, duration, outcome. Supports `?after=` for polling. |
| `GET /v1/agent-runs/{run_id}/proposal` | The validated proposal, plus the id of the artefact it became (draft narrative, candidate plan revision, review thread). |
| `POST /v1/agent-runs/{run_id}:cancel` | Cancel a running run. Terminal state `CANCELLED`, evidence sealed. |

There is deliberately **no** approve or reject route here. Approval happens on the existing endpoints for the artefact — the assessment narrative approval, the plan revision approval, the transformation review thread — so there is one approval path per artefact type and not a second one that happens to be reachable through an agent. The proposal response carries the approval endpoint the console should send the user to.

### 8.2 Console screens

Three, in the existing vanilla-TS pattern (`apps/console/src/screens/*.ts`, hash router, `api.ts` bearer client):

**`agent-start.ts`** — pick an agent (three cards, each stating what it reads, what it proposes, and *that it cannot change anything*), pick the project and the run/plan it works from, show the budget it will run under, and start. One button.

**`agent-run.ts`** — the step list, polled on `GET .../steps?after=`. One row per step: index, kind (`PLAN`/`ACT`/`OBSERVE`), tool name, tokens, cost, duration, outcome. A header with state, budget consumption as "used / limit" for each of the five budget dimensions, and the model id and prompt versions in use. A terminal run says which terminal state and why — and a `BUDGET_EXCEEDED` run says which budget, in plain words, because "it stopped" with no reason is the thing a user will ask about first. Cancel is here.

**`agent-proposal.ts`** — the proposal, rendered per agent type: the assessment narrative with each disposition's explanation beside the stored disposition; the design proposal with pattern rationale, rejected alternatives and the wave table; the transformation proposal with each diff hunk next to its explanation, equivalence and caveat. Every screen states, above the content, that this is a model-drafted proposal that has been validated against the domain contract and approved by nobody. Approve and Reject link to the existing approval surface for that artefact, carrying the revision id — the console does not invent an approval of its own.

Consistent with the existing screens, every value shown is the stored one; an approximate or unavailable figure is labelled as such (R-MAP-01) and never rendered as exact.

---

## 9. Prompts as versioned artefacts

There is no `prompts/` directory in the repository today and no prompt text anywhere, because nothing calls a model. R6 creates the first one, and A6.prompts governs it: a prompt is a file with an identifier and a version, diffable in review, referenced by id at the call site. A string literal above the length threshold passed to a model call fails CI.

```
prompts/
  assessment-explainer/
    system.v1.md
    explain-disposition.v1.md
    detect-anomalies.v1.md
    draft-summary.v1.md
  design-proposer/
    system.v1.md
    select-pattern.v1.md
    assign-waves.v1.md
  modernize-proposer/
    system.v1.md
    scope-transformation.v1.md
    explain-diff.v1.md
```

`cairn_kits.loop.PromptRegistry` loads them, keyed `(prompt_id, version)`, and validates at startup that every prompt an `AgentSpec` references exists (A5.13). A missing prompt fails the process, not the first run. The resolved id and version go into every `AgentStep` and into the run's evidence `model_calls`, so a proposal can be traced to the exact prompt text that produced it — and bumping a prompt bumps the agent's version, because the same inputs under a different prompt are not the same agent.

Each system prompt states the propose-only constraint in the model's own instructions as well. That is defence in depth and not a control: the controls are the closed toolset, the capability guard and the approval gate.

---

## 10. Persistence

Two new tenant-owned tables, under the same forced RLS, required policies and app-role adversarial tests as every other tenant-owned table (ADR-012, R-TENANT-02), with a migration reviewed like any other:

- `agent_run` — run id, tenant, project, agent id and version, actor, state, inputs hash, budgets, consumption, terminal reason, evidence chain head, timestamps.
- `agent_step` — run id, index, kind, tool name, prompt id and version, model id, parameters hash, argument hash, token counts, cost, duration, outcome. Append-only; no update path.

Durable state is declared, not assumed (A5.10): an approver reads a run's steps long after the worker that produced them is gone, so in-memory is not an option. The in-memory implementations stay for tests, as everywhere else in this codebase.

---

## 11. What this design does not do

Stated so that nobody has to infer it:

- No agent writes to a customer's cloud account or repository, in any mode, under any approval. That path is Class C behind the execution gate and has no agent tool.
- No agent approves anything, including its own output, and no agent is a party to an approval.
- No conversational or free-text surface; no "ask CAIRN anything".
- No multi-agent delegation, no agent starting another agent, no agent hierarchy. One run, one agent.
- No customer bring-your-own-key, no second model provider (ADR-014 stands).
- No per-tenant model selection or per-tenant prompt overrides.
- No cross-project or cross-tenant agent run.
- No autonomous or scheduled agent runs in R6: a run is started by an identified human.

Each of those would need its own ADR, and several would need ADR-019 amended.
