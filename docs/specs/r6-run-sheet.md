# R6 run sheet — implementation units, acceptance tests, conformance rules

**Status:** design only. No unit below has started. Target release `v0.6.0`.
**Design:** `docs/specs/r6-agentic-design.md`. **Decision:** `docs/adr/ADR-019-agentic-workflows.md`.
**Operator prerequisites:** `docs/specs/r6-operator-actions.md`.

Each unit is sized for one working session: one branch, one PR, its own acceptance test, green `make test` and `uv run lint-imports` before it merges. The estimate is a session count, where one session is a focused half-day. Units in the same **wave** have no dependency on each other and can be taken in any order; a wave does not start until the previous one is merged.

A unit is not done because the code looks right. It is done when its acceptance command exits zero over a non-empty set of tests (A8.nonempty-test-run — exit 2 and exit 3 are not passes).

---

## Dependency waves at a glance

```
Wave 1  foundations           R6-01 → R6-05        (loop contract, budgets, prompts, capabilities)
Wave 2  providers             R6-06, R6-07         (Vertex adapter, ADK adapter)
Wave 3  tool surface          R6-08 → R6-11        (eight MCP servers)
Wave 4  agents                R6-12 → R6-14        (assessment, design, modernize)
Wave 5  runtime               R6-15, R6-16         (persistence + worker, API routes)
Wave 6  surfaces              R6-17, R6-18         (console, A2A cards)
Wave 7  close-out             R6-19, R6-20         (conformance wiring, live smoke + honesty pass)
```

Total: 20 units, 38 sessions. Wave 7's live smoke test is blocked on the operator actions in `docs/specs/r6-operator-actions.md` and cannot be completed without them.

---

## Wave 1 — foundations

### R6-01 — Prompt registry and the first prompt artefacts
**Est.** 1 session. **Depends on** nothing.
Create `prompts/` with the ten files in the design §9 layout (content can be a first draft; the unit is the mechanism, not the wording). Add `cairn_kits.loop.PromptRegistry`: load by `(prompt_id, version)` from a directory, reject a duplicate id/version, reject a file whose front matter does not declare its own id and version, and expose a startup validation that a given set of references all resolve.
**Acceptance:** `uv run pytest packages/kits/tests/test_prompt_registry.py -q` — asserts load by id and version; a missing reference raises at validation time, not at use time; a prompt file whose declared id disagrees with its path raises; and the A6.prompts check finds no prompt literal above the threshold anywhere in `packages/` or `apps/`.

### R6-02 — The loop contract
**Est.** 2 sessions. **Depends on** R6-01.
`cairn_kits.loop`: `AgentSpec`, `AgentRun`, `AgentStep`, `StepKind`, `AgentRunState`, and the state machine's `validate_transition` in the shape `cairn_modules.approvals` and `cairn_modules.execution` already use. Frozen dataclasses, validation in `__post_init__`, no framework import, `cairn_kernel` only.
**Acceptance:** `uv run pytest packages/kits/tests/test_agent_contract.py -q` — every illegal state transition raises; there is **no** `EXECUTED` state and no field on any type that names an approval or an execution; `AgentSpec` with an empty toolset, an unbounded budget field, or an unresolvable prompt reference raises; steps are append-only (no mutation path).

### R6-03 — Run budgets and the budget ledger
**Est.** 2 sessions. **Depends on** R6-02.
`RunBudget` (five required dimensions, none defaulting to unbounded) and `BudgetLedger` (debit-before-attempt, exhaustion is a terminal outcome not an exception past the caller).
**Acceptance:** `uv run pytest packages/kits/tests/test_run_budget.py -q` — a budget missing any dimension raises; a ledger debited past each of the five limits reports exhaustion for that dimension by name; a run terminating on exhaustion lands in `BUDGET_EXCEEDED` and not `FAILED`; and the negative case a fail-closed control needs (A8.fail-closed-negative): a run with **no** registered budget cannot start.

### R6-04 — `RunBudgetPolicy` in `ModelGateway`
**Est.** 2 sessions. **Depends on** R6-03.
Add the run-scoped token/cost policy to `cairn_kernel.model`, joining the existing pre-call chain after the circuit breaker. Key on `ModelRequest.agent_run_id`. New typed error `RunBudgetExceededError`.
**Acceptance:** `uv run pytest packages/kernel/tests/test_model_run_budget.py -q` — a request on an exhausted run raises **and `FakeModelAdapter.call_count` is unchanged** (the block happened before the adapter, the same property the three existing policies are tested on); a request carrying an `agent_run_id` with no registered budget is refused; a request with no `agent_run_id` is unaffected and every existing `test_model_policy.py` test still passes unchanged; the refusal is logged as an `AiCallRecord` with the run id on it.

### R6-05 — Tool capabilities and the propose-only boundary
**Est.** 2 sessions. **Depends on** R6-02.
`ToolCapability` (`READ`, `PROPOSE`) declared per tool on `BoundedContextServer`; `McpRegistry` carries it through `lookup`. `AgentSpec` construction rejects any tool that is not `READ` or `PROPOSE`, and rejects a `required_role` that does not dominate its toolset's roles. Add the import-linter contract `loop-cannot-execute`.
**Acceptance:** `uv run pytest packages/kits/tests/test_tool_capability.py packages/kits/tests/test_loop_authority_boundary.py -q && uv run lint-imports` — a server registering a tool with no declared capability raises; an `AgentSpec` naming a mutating tool raises at construction; the AST import test (the shape `packages/kernel/tests/test_model_port.py` uses for R-AI-02) proves `cairn_kits.loop` reaches neither `cairn_kernel.execution_gate` nor, transitively, any approval or execution type; `lint-imports` reports all contracts kept.

---

## Wave 2 — providers

### R6-06 — Vertex Gemini `ModelPort` adapter
**Est.** 2 sessions. **Depends on** R6-04. **Blocked for live verification on** operator actions §1–§3.
`cairn_adapters.model.vertex_gemini.VertexGeminiAdapter` per design §2: ADC only, lazy client import, startup-validated non-secret config, residency-checked location, exact model id. Register a real price rate for the model. `FakeModelAdapter` stays the default.
**Acceptance:** `uv run pytest packages/adapters/tests/test_vertex_gemini_adapter.py -q` — request and response translation asserted against an injected stub client (no network); a provider error maps to the typed kernel error the gateway's `except` path expects; safety flags are surfaced, never swallowed; a location outside the residency set raises at construction; **a grep-level assertion that the adapter contains no `api_key`, no `GOOGLE_API_KEY` read and no credential literal** (A7.secrets); and `CAIRN_MODEL_ADAPTER` unset still resolves to the fake.

### R6-07 — ADK agent-loop adapter
**Est.** 3 sessions. **Depends on** R6-05, R6-06.
`cairn_adapters.agent_adk` implementing `AgentLoopPort` per design §7: ADK pinned exactly; an ADK model implementation delegating every call to `ModelGateway.generate` with the run's `agent_run_id`; tools generated only from `spec.toolset`, bodies calling `ToolInvokerPort`; a pre-tool capability re-check; prompts by id; steps through `StepRecorder`. Import-linter contract confining ADK to this package.
**Acceptance:** `uv run pytest packages/adapters/tests/test_agent_adk_adapter.py -q && uv run lint-imports` — **a stub `ModelGateway` records every model call the adapter makes and the count equals the run's model-call count** (no call escaped the gateway); the adapter builds no tool outside `spec.toolset`; a tool whose capability is neither `READ` nor `PROPOSE` is refused at the pre-tool callback even when the spec is forced past construction; no ADK type appears in the adapter's public signatures; `lint-imports` shows no ADK import outside `cairn_adapters.agent_adk`.

Also in this unit: `DeterministicAgentLoop` in `cairn_kits.loop`, so both implementations land together and can be asserted to produce the same `AgentRun` shape.

---

## Wave 3 — tool surface

Each unit follows `posture_server.py`'s shape, and each tool gets a Pydantic argument model (reject unknown keys), a `REQUIRED_ROLES` entry, a capability declaration, and an **instantiate-and-call smoke test** (A8.mcp-smoke).

### R6-08 — `estate` and `mappings` servers
**Est.** 2 sessions. **Depends on** R6-05.
Seven tools per design §4.1.
**Acceptance:** `uv run pytest apps/mcp-gateway/tests/test_estate_server.py apps/mcp-gateway/tests/test_mappings_server.py -q` — each server instantiates and one real tool returns real data through its application service; an unknown tool name raises; an unknown argument key is rejected; a caller below the declared role gets `ForbiddenError` **before** the handle runs; and an `APPROXIMATE` mapping resolution comes back carrying its caveat (R-MAP-01).

### R6-09 — `assessment` and `ingestion` servers
**Est.** 2 sessions. **Depends on** R6-08.
Seven tools per design §4.1. Record the ADR-011 enumeration deviation (assessment as a ninth context) in the PR description and in `docs/specs/r6-agentic-design.md` §4.1 where it is already noted.
**Acceptance:** `uv run pytest apps/mcp-gateway/tests/test_assessment_server.py apps/mcp-gateway/tests/test_ingestion_server.py -q` — as R6-08, plus: a tool reading another tenant's run raises, under the app role, not the owner role (R-TENANT-01).

### R6-10 — `finops` and `tenancy` servers
**Est.** 1 session. **Depends on** R6-08.
Five tools per design §4.1, all `READ`.
**Acceptance:** `uv run pytest apps/mcp-gateway/tests/test_finops_server.py apps/mcp-gateway/tests/test_tenancy_server.py -q` — as R6-08, plus: the `tenancy` server exposes **no** tool that creates a tenant, grants a membership or changes a setting (asserted on the registered tool list, not by inspection); `tenancy.list_project_members` requires `TENANT_ADMIN`.

### R6-11 — `design`, `planning` and `transformation` servers
**Est.** 2 sessions. **Depends on** R6-08.
Nine tools per design §4.1, including the four `PROPOSE` tools.
**Acceptance:** `uv run pytest apps/mcp-gateway/tests/test_design_server.py apps/mcp-gateway/tests/test_transformation_server.py -q` — as R6-08, plus: each `PROPOSE` tool is declared `PROPOSE` and produces a candidate artefact with no approval state set; `transformation.run` invokes the existing `TransformationPort` and writes **nothing** outside CAIRN's own store (asserted on a fake source tree that is byte-identical before and after); the registered tool list contains no apply, publish, approve or execute tool.

---

## Wave 4 — agents

Each agent unit delivers the application service, its `AgentSpec`, its output schema, its domain-contract validation, and its approval routing. Every test runs against `DeterministicAgentLoop` and `FakeModelAdapter`.

### R6-12 — Assessment agent
**Est.** 2 sessions. **Depends on** R6-07, R6-09, R6-10.
`cairn_modules.agents.assessment_explainer` per design §3.1.
**Acceptance:** `uv run pytest packages/modules/tests/test_assessment_agent.py -q` — the five validation rules each have a failing fixture that is rejected and **not persisted**, and the headline one has its own test: *a narrative whose disposition differs from the stored `DispositionDecision` fails the run and persists nothing*; an uncited explanation is rejected; a narrative describing an approximate figure as exact is rejected; the draft is marked model-drafted; publishing it into an evidence package without a human approval raises.

### R6-13 — Design agent
**Est.** 2 sessions. **Depends on** R6-07, R6-11.
`cairn_modules.agents.design_proposer` per design §3.2.
**Acceptance:** `uv run pytest packages/modules/tests/test_design_agent.py -q` — a proposal naming a pattern outside the declared catalogue version is rejected; a workload with an accepted disposition missing from every wave is rejected, as is one in two waves; **wave numbers contradicting `generate_roadmap`'s topological order are rejected**; the three version fields are carried and equal the ones used (R-VER-01); the resulting candidate plan revision is an immutable row the agent's own principal cannot approve (`check_separation_of_duties` raises).

### R6-14 — Modernize agent
**Est.** 2 sessions. **Depends on** R6-07, R6-11.
`cairn_modules.agents.modernize_proposer` per design §3.3.
**Acceptance:** `uv run pytest packages/modules/tests/test_modernize_agent.py -q` — **an explanation set whose `manifest_hash` does not match the stored manifest is rejected**; a manifest entry with no explanation is rejected, and an explanation with no entry likewise; an `outcome` disagreeing with the engine's `ManifestOutcome` is rejected; an invented `engine_reason` is rejected; a dropped mapping caveat is rejected; explanations land on the existing review thread as model-drafted and a blocked thread stays blocked.

---

## Wave 5 — runtime

### R6-15 — Agent run persistence and the worker runner
**Est.** 3 sessions. **Depends on** R6-12, R6-13, R6-14. **Needs a migration review — see operator actions §5.**
`agent_run` and `agent_step` tables per design §10, with forced RLS and the required policies; in-memory implementations for tests; `StepRecorder` writing audit entries per step and sealing one evidence envelope per run; `apps/worker` executing queued runs.
**Acceptance:** `uv run pytest tests/integration/test_migrations.py packages/modules/tests/test_agent_run_repository.py apps/worker/tests/test_agent_runner.py -q` — the migration test's existing RLS assertions cover both new tables under the app role (R-TENANT-02); a write-restart-read round trip returns every step in order (A8.persistence-roundtrip); `agent_step` has no update path; a run's sealed evidence carries, for every model call, the prompt id and version, the model id, the parameters and the tool calls, and verifies against the chain head; a run terminating `FAILED` or `BUDGET_EXCEEDED` is sealed too; tampering with one step's recorded hash is detected (R-EVID-01).

### R6-16 — Agent API routes
**Est.** 2 sessions. **Depends on** R6-15.
The five routes in design §8.1, following the existing `routes_*.py` conventions.
**Acceptance:** `uv run pytest apps/api/tests/test_routes_agents.py -q` — every route requires an authenticated principal and a required actor, none defaulted (A7.actor); starting a run below the agent's `required_role` returns 403; a budget override that **raises** any dimension is rejected; a repeated start with the same idempotency key creates one run (A5.11, R-IDEM-01); every error branch's status code has a test asserting that code (A8.error-branch-status); **there is no approve or reject route on an agent run** (asserted on the router's route list); the proposal response carries the existing approval endpoint for its artefact type.

---

## Wave 6 — surfaces

### R6-17 — Console: start, watch, decide
**Est.** 3 sessions. **Depends on** R6-16.
The three screens in design §8.2, in the existing vanilla-TS screen/router pattern.
**Acceptance:** `pnpm --filter console test` plus the existing Playwright e2e suite — a run can be started, its steps appear as they arrive, each of the five budget dimensions renders as "used / limit", a `BUDGET_EXCEEDED` run names the budget that stopped it in plain words, every proposal screen carries the model-drafted-and-unapproved banner above the content, an approximate figure renders labelled and never as exact (R-MAP-01), and Approve/Reject navigate to the existing approval surface carrying the revision id rather than posting an approval of their own.

### R6-18 — A2A agent cards for the three agents
**Est.** 1 session. **Depends on** R6-16.
Extend `apps/mcp-gateway/a2a_bridge.py` per design §6: three launch-agent cards with skills, schema names, budgets, required role, `propose_only: true` and `approval_endpoint`; the seven new servers' per-server cards come free through `agent_cards_for_registry`.
**Acceptance:** `uv run pytest apps/mcp-gateway/tests/test_a2a_bridge.py -q` — every published card carries `propose_only: true` and a resolvable `approval_endpoint`; **no published skill's name or declared capability is a mutation, an approval or an execution** (asserted over every card the bridge publishes, not a sample); an A2A task naming an unpublished skill is refused; the existing per-server card tests still pass unchanged.

---

## Wave 7 — close-out

### R6-19 — Conformance rules and the honesty pass
**Est.** 1 session. **Depends on** R6-18.
Add the ten R6 rules below to `tools/conformance/rules.yaml` with their real check commands and evidence paths; confirm R-CONF-01 (every mandatory rule maps to a check) still passes; move ADR-019 from `Proposed` to `Accepted` only on Allan's word; add the ADR to `docs/adr/README.md`'s decision log; write the `CHANGELOG.md` entry for `0.6.0` describing what actually landed and what has never run against a real provider.
**Acceptance:** `uv run python -m cairn_kernel.conformance -q` exits zero over a non-empty rule set, with all ten new rules reporting a real result; and a grep over `*.md` finds no claim that CAIRN is agentic that is not true of the merged code.

### R6-20 — Live Vertex smoke test
**Est.** 1 session. **Depends on** R6-19 and **on every operator action in `docs/specs/r6-operator-actions.md` being complete** — this unit cannot be done without them.
`tests/integration/test_vertex_gemini_live.py`, marked `live_model`, deselected by default, skipped unless `CAIRN_LIVE_MODEL_SMOKE=1` and the three Vertex settings are present. One call, tiny fixed prompt, two-field schema.
**Acceptance:** `uv run pytest -q` (default) collects a non-empty suite and **does not** select the live test; `CAIRN_LIVE_MODEL_SMOKE=1 uv run pytest -m live_model -q` makes exactly one real Vertex call and asserts a schema-valid response with non-zero token counts and a non-zero computed cost. Run by hand before the release, never in CI.

---

## Conformance rules for R6

Ten new rules for `tools/conformance/rules.yaml`, in the format the file already uses (`id`, `title`, `owner`, `mandatory`, `check`, `evidence`). Each one is mechanically checkable, because R-CONF-01 requires every mandatory rule to map to a check and an unmechanised rule does not belong in this list.

| Id | Title | Owner | Proved by |
|---|---|---|---|
| **R-AGENT-01** | Agent step, model-call and wall-clock budgets are enforced before each step, and exhaustion terminates the run | ai | R6-03 |
| **R-AGENT-02** | Token and cost budgets are enforced inside `ModelGateway` before the adapter is reached; a run with no registered budget is refused | ai | R6-04 |
| **R-AGENT-03** | An agent toolset contains only `READ` or `PROPOSE` tools; a mutating tool is rejected at `AgentSpec` construction and again before invocation | ai | R6-05, R6-07 |
| **R-AGENT-04** | `cairn_kits.loop` can reach no approval or execution authority (AST import test and an import-linter contract) | ai | R6-05 |
| **R-AGENT-05** | No model call in an agent run bypasses `ModelGateway` | ai | R6-07 |
| **R-AGENT-06** | The agent framework appears nowhere outside `cairn_adapters.agent_adk` (A6.port) | platform | R6-07 |
| **R-AGENT-07** | Every prompt is a versioned file referenced by id; no prompt literal reaches a model call (A6.prompts) | ai | R6-01 |
| **R-AGENT-08** | Every agent proposal is validated against its domain contract before persistence; an invalid proposal is never persisted and never displayed | ai | R6-12, R6-13, R6-14 |
| **R-AGENT-09** | Every agent step is recorded in audit and in the run's sealed evidence with prompt id and version, model id, parameters and tool calls; a tampered step is detected | evidence | R6-15 |
| **R-AGENT-10** | Every MCP server has an instantiate-and-call smoke test, and every registered tool declares a capability and a required role (A8.mcp-smoke) | platform | R6-08 → R6-11 |

Existing rules that R6 extends rather than duplicates, and which must still pass unchanged: **R-AI-01** (model output schema-validated), **R-AI-02** (model cannot approve/execute), **R-MAP-01** (approximate never rendered as exact), **R-REV-01** (approvals bind to immutable revisions and exact hashes), **R-GATE-01** and **R-MUT-01/02** (the execution gate and mutation classes), **R-TENANT-01/02/03**, **R-EVID-01**, **R-VER-01**, **R-ARCH-01/02**, **R-SEC-02** (SBOM and signature, now covering ADK and the Vertex client).

### Architectural Rules gates this work must satisfy

Part A gates in scope, named so a reviewer can check them one by one rather than inferring: **A1** (ADK as the framework default; Python for agentic orchestration), **A5.10** (durable state declared — R6-15), **A5.11** (idempotency declared on the start route — R6-16), **A5.12** (no fire-and-forget: queued runs are supervised by the worker — R6-15), **A5.13** (startup-validated config for the Vertex and prompt settings — R6-01, R6-06), **A6.framework** (loop uses a framework — R6-07), **A6.port** (framework behind a port — R6-07), **A6.prompts** (versioned prompt files — R6-01), **A7.secrets** (no key anywhere — R6-06), **A7.input-validation** (Pydantic argument models on every MCP tool — R6-08 → R6-11), **A7.actor** (required actor on every route and every step — R6-02, R6-16), **A7.audit-event** (audit per step — R6-15), **A7.supply-chain** (ADK and Vertex client pinned, SBOM, signature — R6-06, R6-07), **A8.mcp-smoke** (R6-08 → R6-11), **A8.fail-closed-negative** (negative tests on the budget and capability guards — R6-03, R6-05), **A8.persistence-roundtrip** (R6-15), **A8.error-branch-status** (R6-16), **A8.nonempty-test-run** (every acceptance command above), **A9.irreversible-confirm** (unchanged: the existing execution gate, which no agent can reach).

Part B targets are not claimed here, on track or otherwise.

---

## Open questions for Allan

1. **ADR-019 is `Proposed`.** It moves to `Accepted` on your word, not on a merge. Nothing in Wave 1 should start before that.
2. **Budgets in §3 are initial numbers, not measurements.** They were chosen to bound a run, not from observed token use, and the first real runs will move them. Worth setting a cost ceiling you are comfortable with per run before R6-03 fixes the defaults.
3. **Assessment as a ninth bounded context** is a deviation from ADR-011's enumeration of eight. The alternative is folding assessment's four read tools into the `estate` server, which would put two application services behind one bounded-context server. Recommendation: the ninth server; your call.
4. **R6-20 is blocked on the operator actions** and is the only thing that proves the ADK adapter against a real provider. Until it has run, the honest claim is "agentic against deterministic adapters", not "agentic".
5. **`CHANGELOG.md`'s `0.5.0` entry** says R5 shipped "MCP/A2A surfaces" as part of a complete release, while one bounded-context server of eight exists. That reads as more than is there. R6-19 is the natural place to correct it, but it is your wording to approve.
