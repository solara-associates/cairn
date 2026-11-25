# ADR-019: Agentic workflows as bounded plan-act-observe loops that only propose

- **Status:** Proposed
- **Date:** 2026-11-24
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** ADR-002, ADR-008, ADR-009, ADR-010, ADR-011, ADR-014, Implementation spec §5, §10, §11

## Context

CAIRN is not agentic today, and no document in this repository claims it is. What exists is the scaffolding for it:

- `cairn_kernel.model` holds `ModelPort`, `ModelGateway` (deny-list, per-tenant rate limit, circuit breaker, schema validation, per-call cost) and the LLMOps cost-control loop (ADR-014, R5-02a/R5-02b).
- `cairn_adapters.model` holds exactly one adapter, `FakeModelAdapter`. There is no real provider adapter, and no module in `cairn_modules` calls a model at all.
- `cairn_kits.loop` and `cairn_kits.a2a` are empty packages — a docstring each.
- `cairn_kits.mcp.McpRegistry` and `apps/mcp-gateway` exist with one bounded-context server registered (`posture`) of the eight ADR-011 names, plus an in-process A2A bridge that derives one agent card per registered server.
- The approval and execution machinery is complete and already enforces propose-then-approve: immutable revisions bound to approvals (ADR-009), operation/mutation classes with a compensation contract and the kernel execution gate (ADR-010), signed hash-chained evidence (ADR-008).

The product owner has decided CAIRN must be genuinely agentic before its public launch. The question this ADR settles is what "agentic" means here, concretely enough that a reviewer can reject an implementation for getting it wrong — and narrowly enough that it cannot become a route around the controls the platform already enforces.

Two estate rules constrain the answer and are not negotiable here. Architectural Rules A1 names ADK as the agent framework default, and A6.framework forbids hand-rolling a reasoning loop ("if a workflow involves more than one LLM call whose input depends on a prior call's output, or any tool selection made by the model, use an agent framework"). A6.port requires that framework to sit behind a port, with no framework type visible to the domain. The brief that prompted this ADR asked for "a bounded plan-act-observe loop in `cairn_kits/loop`"; taken literally that is a hand-rolled loop, and `cairn_kits` may not import `cairn_adapters` at all (`.importlinter`'s `kits-purity` contract), so a framework cannot live there either. This ADR resolves that conflict rather than silently picking one side.

## Decision

### 1. What an agent is

An agent in CAIRN is a **named, versioned, bounded plan-act-observe loop over exactly one project, whose only output is a proposal**. Concretely, an agent is an `AgentSpec` — a value, not a class hierarchy — carrying:

| Field | Meaning |
|---|---|
| `agent_id`, `version` | Stable identity; the version changes when prompts, toolset or output contract change. |
| `prompt_refs` | Prompt identifiers and versions, resolved from versioned prompt files. Never an inline string (A6.prompts). |
| `toolset` | The exact MCP tool names this agent may call. A closed list, not a capability class. |
| `output_schema` | The `StructuredOutputExpectation` its final proposal must satisfy (R-AI-01). |
| `budget` | `RunBudget`: `max_steps`, `max_model_calls`, `max_total_tokens`, `max_cost_micro_usd`, `max_wall_clock_ms`. Every field required; no field defaults to unbounded. |
| `required_role` | The tenant `Role` a principal must hold to start a run of this agent. |

A run of an agent is an `AgentRun` with an ordered, append-only sequence of `AgentStep`s. A step is one of three kinds — `PLAN` (a model call that decides what to do next), `ACT` (one tool call), `OBSERVE` (the recorded result of an `ACT`, including a failure) — and carries the actor, the prompt id and version, the model id and parameters, the tool name and canonicalised arguments, token counts, cost and duration. A run ends in exactly one terminal state: `PROPOSED`, `FAILED`, `BUDGET_EXCEEDED` or `CANCELLED`. There is no `EXECUTED` state, because an agent run cannot execute anything.

What an agent is **not**: a chat session, a long-lived autonomous process, a thing that holds credentials, or a thing with an inbox. An agent run is started by an identified principal, is scoped to one tenant and one project, and is finished or dead within its wall-clock budget.

### 2. Where the loop lives, and what drives it

The loop is split so that both A6 and `kits-purity` hold:

- **`cairn_kits.loop`** holds the loop's *contract and semantics*, framework-free, importing only `cairn_kernel`: `AgentSpec`, `AgentRun`, `AgentStep`, `StepKind`, `AgentRunState`, `RunBudget`, `BudgetLedger`, the `AgentLoopPort` protocol, the `ToolInvokerPort` protocol, the `StepRecorder` protocol, and `DeterministicAgentLoop` — the mandatory deterministic implementation that replays a scripted step sequence for tests, exactly as `FakeModelAdapter` is mandatory for `ModelPort`. A scripted replay is not a reasoning loop: it makes no model-driven branching decision and selects no tool, which is A6.framework's own stated scope exclusion.
- **`cairn_adapters.agent_adk`** holds the production implementation of `AgentLoopPort`, driven by ADK (A1's default; no deviation ADR is needed because the default is what we take). ADK types appear nowhere outside this package — deleting the ADK import must produce compile errors only inside it (A6.port's own test).
- **`cairn_modules.agents`** holds the three launch agents as application services: they construct an `AgentSpec`, invoke `AgentLoopPort`, validate the resulting proposal against the domain contract, persist it, and route anything irreversible into the existing approval machinery. No SDK, no framework type, no SQL.

The composition root (`apps/worker` for queued runs, `apps/api` for synchronous starts) is the only place that binds a real `AgentLoopPort`, a real `ModelPort` and a real `ToolInvokerPort` together.

### 3. How agents call tools

An agent reaches a tool only through `ToolInvokerPort.invoke(tool_name, arguments)`, which the composition root binds to `McpGateway.call_tool` — so every agent tool call goes through the gateway's existing authentication, per-tenant authorisation, rate limiting and audit (ADR-011). An agent never imports an application service, never holds a database handle, and never touches a provider SDK. `cairn_kits` cannot import `cairn_modules` or `cairn_adapters`, so this is structural, not a convention.

Two additions make the tool surface safe to hand to a model:

- **Declared capability.** `BoundedContextServer` gains a per-tool `ToolCapability`: `READ` (returns state, changes nothing) or `PROPOSE` (produces a candidate artefact — a draft, a target model, a diff — that no one has approved and nothing has applied). There is no third value an agent may hold. A tool that performs a Class B or Class C mutation is registered for human and API callers but is **not registrable into an agent toolset**: `AgentSpec` construction raises if any named tool is not `READ` or `PROPOSE`. The failure is at construction, before a run exists.
- **No path to authority.** `cairn_kits.loop` imports neither `cairn_kernel.execution_gate` nor (being in `cairn_kits`) `cairn_modules.approvals`/`cairn_modules.execution`, asserted by the same AST import test `cairn_kernel.model` already uses for R-AI-02, plus an import-linter contract. The loop package cannot reach approval or execution authority even by mistake.

### 4. Budgets, enforced where the calls happen

Budgets are not advisory and are not checked after the fact:

- **Step, model-call and wall-clock budgets** are enforced by the loop: `BudgetLedger` is debited before each step is attempted, and an exhausted ledger terminates the run in `BUDGET_EXCEEDED` rather than raising past the caller.
- **Token and cost budgets** are enforced inside `ModelGateway`, as a new run-scoped policy in its existing pre-call chain (deny-list, rate limit, circuit breaker, then run budget). `ModelRequest` already carries `agent_run_id`; the policy keys on it, and a call belonging to an exhausted run is refused **before** `adapter.generate` is reached — the same fail-closed shape, and the same testable property ("the adapter's call counter stayed at zero past the block point") as the policies already there.

A model call that carries no `agent_run_id` is not an agent call and is unaffected. A model call made inside an agent run with no registered budget is refused: absent budget fails closed, never open.

### 5. Evidence and audit

Every step of every run is recorded twice, through mechanisms that already exist, with no new logging path:

- **Audit** (`cairn_kernel.security.AuditEntry`): one entry per step, carrying actor, action, operation class and the canonicalised payload.
- **Evidence** (`cairn_kernel.evidence.seal_evidence`): one sealed, signed, hash-chained envelope per run, whose `model_calls` carry each call's prompt id and version, model id, parameters, token counts and cost; whose `provenance` carries every tool call and its result reference; whose `policy_decisions` carry every budget, capability and schema decision taken during the run; and whose `outcome` is the run's terminal state. A run that ends `BUDGET_EXCEEDED` or `FAILED` is sealed too — a dead run is evidence, not an absence of it.

A proposal that was never sealed cannot be approved: the approval path reads the run's evidence chain head, so an unrecorded run has nothing for an approver to bind to (ADR-009).

### 6. Agents only propose

This is the rule the rest of the design exists to make true, and it restates ADR-011 and ADR-014 rather than extending them: **no agent path may authorise or perform an irreversible action.** An agent produces a proposal; a human or a policy approves it through the existing approval gate; the existing execution gate performs it under its mutation class and recovery precondition. The agent is not a party to the approval: separation of duties (`check_separation_of_duties`) treats the agent run's starting principal as the proposer, so the same person cannot start a run and approve its output.

### 7. Honesty until it lands

No document in this repository says CAIRN is agentic until the implementation units in `docs/specs/r6-run-sheet.md` have landed and their acceptance tests pass. This ADR is `Proposed`, not `Accepted`; the design documents it refers to describe intended behaviour and say so; and the `CHANGELOG.md` entry for this work records a design, not a capability.

## Consequences

**Positive**

- One structural answer to "can the AI do something irreversible?": no, and three independent mechanisms say so (capability-declared toolsets, an import boundary with a test, and the pre-existing approval/execution gates).
- Budgets are enforced at the two places cost is actually incurred, reusing the gateway's existing fail-closed policy chain rather than adding a parallel one.
- The framework is swappable: ADK sits behind `AgentLoopPort` alongside a deterministic implementation, so the whole test suite runs with no network and no provider.
- Every run is auditable and replayable from its evidence envelope, including runs that failed or ran out of budget.

**Negative**

- Two implementations of `AgentLoopPort` must be kept behaviourally aligned, and a deterministic fake can drift from what ADK actually does. The opt-in live smoke test is the only thing that catches that drift, and it runs rarely.
- Routing ADK's model calls through `ModelGateway` means subclassing an ADK model type in the adapter and tracking its interface across ADK versions — a real maintenance cost, accepted because the alternative is model calls that escape policy, cost accounting and the circuit breaker.
- Per-tool capability declarations are a new thing every MCP server author must get right, and a wrongly-declared `READ` on a mutating tool would be a genuine hole. It is declared next to the tool and reviewed with it, which is the mitigation, not a proof.
- Agents that may only read and propose cannot do the one thing users will ask for first ("just fix it"). That is the intended trade and it will need explaining.

**Neutral**

- Per-tenant model routing, multi-agent delegation and agent-initiated agents are all out of scope and would each need their own ADR.
- The A2A bridge gains agent cards for the three launch agents; whether those are exposed to external hosts remains ADR-011's staging question, not this ADR's.

## Alternatives considered

1. **Hand-roll the loop in `cairn_kits.loop` with no framework**, as the brief literally asked. Fewer dependencies and nothing to track across ADK versions, but it violates A6.framework and A1, and re-implements retry, tool dispatch and step bookkeeping that ADK already has. Rejected; the `kits`/adapter split above delivers what the brief wanted (a bounded loop contract, framework-free, in `cairn_kits.loop`) without the violation.
2. **Let ADK call Gemini directly, with `ModelGateway` only for non-agent calls.** Much less adapter work. Rejected: it puts the majority of CAIRN's model spend outside the deny-list, rate limiter, circuit breaker, cost accounting and the R5-02b cost-control loop — which is exactly the control ADR-014 exists to provide.
3. **Give agents write tools and rely on the execution gate alone to stop them.** The gate is genuinely fail-closed, so this is not obviously unsafe. Rejected because it makes the gate the only line of defence, and a single mis-classified mutation class would then be a direct path from model output to a customer's cloud account.
4. **Defer agents past launch and ship the deterministic platform.** Lowest risk, and everything in R0–R5 stands on its own. Rejected by the product owner: the launch claim is an agentic modernisation platform.

## If rejected

CAIRN launches as a deterministic assessment and modernisation platform with a `ModelPort` nothing calls, and the public claim must be written accordingly. The scaffolding (`ModelGateway`, the MCP registry, the A2A bridge, `cairn_kits.loop`) stays as dead but honest surface, and the first module that needs a model call will make these same decisions ad hoc and worse.
