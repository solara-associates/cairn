# ADR-020: Principal and tenant propagation through the MCP gateway, with VAID and SYNTHERA

- **Status:** Proposed
- **Date:** 2026-11-27
- **Deciders:** Product owner (Allan Smeyatsky) — self-accepted
- **Related:** ADR-002, ADR-009, ADR-010, ADR-011, ADR-012, ADR-019, `docs/specs/r5-integration-boundaries.md`, `~/solara/reports/s910/REPORT-s910.md` (item 3)

## Context

R6-09's own PR, and the Wave-3 report that followed it, named a real gap and stated it plainly rather than working around it: `McpGateway.call_tool` authenticates the caller and checks the tool's required *role* before `McpRegistry`/`BoundedContextServer.handle` ever runs, but it never passes the authenticated `Principal` — in particular the principal's own `tenant_id` — into the handle itself. `ToolHandle`'s signature is `Callable[[str, Mapping[str, object]], object]`: tool name and arguments, nothing else.

Every bounded-context server that needs a tenant check today invents its own way to get one, from the only thing it has — a caller-supplied argument:

- `ingestion_server.py`/`finops_server.py` take a `tenant_id` argument and compare it to the resource's own recorded tenant. This only proves the resource matches *the tenant the caller claims to be calling on behalf of*; nothing ties that claim to who the gateway actually authenticated.
- `tenancy_server.py`/`transformation_server.py` go further: they construct a `TenantContext` from the caller-supplied `tenant_id` with a fixed placeholder `actor_id="mcp-caller"`, then bind it via `cairn_kernel.tenancy.tenant_scope` so the underlying repository's own ambient-context isolation (ADR-012) runs. The isolation check is real, but it is isolating against a context the handler fabricated from an unverified argument, not from the gateway's own authentication.
- `design_server.py`'s two `PROPOSE` tools (`design.generate_target_model`, `planning.generate_roadmap`) take `tenant_id`/`project_id` arguments and pass them straight into the generator with no check against anything.
- `estate_server.py` has no tenant check at all: every tool resolves an assessment run by `assessment_run_id` alone and returns its artifacts to whoever asked, regardless of tenant.

`mappings_server.py`/`posture_server.py` correctly have no tenant check, because what they read (a published mapping release, a control catalogue) is Global under ADR-012's own classification, not Tenant-owned — that is not part of the gap this ADR closes.

Today every store behind these servers is in-memory (R6-15's Postgres adapters for `CheckpointStore`/`TransformationRunRepository` don't exist yet), so ADR-012's RLS defense-in-depth layer is not actually in the request path for MCP traffic yet either. The application-layer check is, right now, the *only* layer — which is exactly why getting it right, rather than trusting a caller-supplied argument, matters now and not just as future-proofing.

ADR-019 compounds the urgency: an agent's every tool call is routed through `ToolInvokerPort`, bound to this same `McpGateway.call_tool`. An agent run is scoped to one tenant and one project (ADR-019 §1), but nothing today stops a bug in an agent's own generated arguments — or a compromised/misbehaving `AgentLoopPort` implementation — from supplying a different `tenant_id` argument than the run's own and having a handler act on it.

Separately, the product owner wants this ADR to settle how an external agent or caller presenting a **VAID** credential fits the same gateway, and what role, if any, **SYNTHERA** plays. `docs/specs/r5-integration-boundaries.md` (unit 825) already named both as *abstract placeholders* for an unrelated Solara project, documented two hypothetical attach points, and `tests/contract/test_no_vaid_synthera_dependency.py` enforces, repo-wide, that neither is actually referenced anywhere outside that one document and its own test. That document's own stated expectation, if either is ever wired in for real, is: "update this document first..., then add the code — not the other way around." This ADR is that update for VAID; it keeps SYNTHERA at the same documented-boundary status it already had, now inside an accepted ADR rather than only a spec note.

## Decision

### 1. Every tool call carries an authenticated principal context

`ToolHandle` changes from `Callable[[str, Mapping[str, object]], object]` to a shape that also carries the gateway's own authenticated `Principal` (`cairn_kernel.security.Principal`: `subject`, `tenant_id`, `roles`) through to the handler, as a required argument — not an optional one, and not smuggled into `arguments`. `McpGateway.call_tool` already produces this `Principal` via `authenticate()` before `authorize()` runs; this ADR's only change to that ordering is that the same already-verified `Principal` is now threaded one layer further, into `McpRegistry.invoke` → `ToolRegistration.invoke` → `BoundedContextServer.handle`.

For an agent run (ADR-019), the principal propagated is the run's own starting principal — the same one separation-of-duties already treats as the proposer — never a principal the agent's own output could name.

### 2. Handlers enforce tenant scope themselves, in addition to row-level security

Every bounded-context server that reads or writes Tenant-owned or Project-owned data (ADR-012's classification) must check the authenticated principal's `tenant_id` against the resource it is about to return or act on, using the propagated `Principal` — never a caller-supplied `tenant_id` argument as the source of truth for that check. Where a server currently takes a `tenant_id` argument for addressing (which tenant's run, which project), it keeps taking it, but that argument becomes informational/defensive: a mismatch between the argument and the principal's own `tenant_id` fails closed with `TenantScopeViolationError` before the call is attempted, catching a caller/agent bug loudly rather than silently trusting the claim.

This is the same "two layers" shape ADR-012 already established for the database (RLS plus the kernel contract around it): the gateway's application-layer check here does not replace RLS once R6-15's Postgres adapters land, it is the layer that exists *before* RLS does, and stays as defense-in-depth after.

Concretely, in this unit:

- `estate_server.py` gains the tenant check it entirely lacked: every tool now confirms the fetched assessment run's `tenant_id` equals the principal's, before returning any artifact.
- `ingestion_server.py`/`finops_server.py` keep their existing resource-tenant check, and additionally require the principal's `tenant_id` to match (both the caller-supplied argument and the resource).
- `tenancy_server.py`/`transformation_server.py` build their `TenantContext` from the principal (`tenant_id`, `actor_id=principal.subject`, `actor_roles=principal.role_values()`), not from the caller-supplied argument and a placeholder actor id.
- `design_server.py`'s two `PROPOSE` tools validate the caller-supplied `tenant_id`/`project_id` against the principal before generating anything.
- `mappings_server.py`/`posture_server.py` are unchanged: Global data, no tenant check, as ADR-012 already says should be the case.

### 3. VAID: an open-source identity-verification library, in CAIRN core

Where `docs/specs/r5-integration-boundaries.md` treated VAID as an unimplemented, illustrative placeholder for "an external agent/workload identity-verification service," this ADR adopts it for real, concretely, as follows:

- An agent or external caller may present a **VAID** instead of (or in addition to) the bearer token `cairn_adapters.auth_oidc.JwtAuthenticator` verifies today.
- The gateway verifies a presented VAID using an **open-source VAID library**, brought into **CAIRN core** (`cairn_kernel`, or a new leaf package at the same layer — not `cairn_adapters`, because verifying a VAID's signature/structure is a kernel-level concern with no provider SDK underneath it, the same reasoning that keeps `ModelGateway`'s policy chain in `cairn_kernel` rather than in an adapter). It is a dependency like any other open-source library this repository already takes (e.g. `pydantic`), not a network call to an external service — the "VAID library" verifies a credential's own cryptographic structure, it does not phone a VAID-operated service to do so.
- Verifying a VAID produces the same `Principal` shape `JwtAuthenticator.verify` already produces, through the same swappable authenticator shape `r5-integration-boundaries.md`'s attach point 1 already described — `McpGateway.authenticate` gains a second authenticator implementation, selected the same way `cairn_adapters.model.selection.resolve_model_adapter` already selects between model adapters, never a parallel auth path.
- **Scope can only shrink.** A VAID may carry a *narrowed* scope — a subset of the tenant/project/role authority its underlying principal actually holds (an agent's own delegated authority, for instance). The gateway derives the principal context *from the VAID*, including that narrowing: the `Principal`/scope `authorize()` and every handler's tenant check (§2) sees is the VAID's narrowed one, never the wider authority behind it. A VAID presented to request a *wider* scope than it carries, or than the authenticator backing it actually grants, is rejected the same way an expired or malformed token is today — fail closed, before `authorize()` runs. No handler, agent, or caller can use a VAID to broaden what §2 already enforces; it can only ever be used to prove a request is authorized for *less*.
- For an agent run specifically: `AgentLoopPort`/`ToolInvokerPort` (ADR-019 §3) may present the run's own VAID — scoped at construction to exactly that run's `required_role`, tenant and project — rather than a raw bearer token, once this ADR is accepted and VAID is implemented. This is not implemented by this ADR (see "Explicitly deferred" below); it is named here because it is the reason VAID and the propagation fix in §1/§2 belong in the same decision: a VAID's narrowed scope is only meaningful if every handler downstream actually enforces the principal/scope it is given, which is precisely what was missing before this ADR.

### 4. SYNTHERA: an optional adapter behind a port, commercial, never required

SYNTHERA's status does not change from what `r5-integration-boundaries.md` already proposed, except that it now has a named, accepted place in the architecture rather than only a spec footnote:

- SYNTHERA is modelled as an **optional adapter behind a port** — call it `PolicySubstratePort` or similar at the design stage that actually implements it — covering policy decisions beyond the gateway's own role/tenant checks (e.g. a budget ceiling, a revocation list) and a tamper-evident record of what was decided and why.
- **CAIRN works fully without it.** Every control this ADR and ADR-019 already describe (role/tenant authorization, `RunBudget`, the evidence envelope, approval/execution gates) is implemented in CAIRN core today or by prior ADRs, with no SYNTHERA dependency. A deployment with no SYNTHERA adapter bound loses nothing CAIRN itself promises; it simply has no optional extra policy/budget/revocation layer bolted on.
- SYNTHERA, unlike VAID, is **commercial and optional**: it is never imported from `cairn_kernel`, never a required dependency of any core flow, and any SYNTHERA-backed adapter lives in `cairn_adapters` (or a separate package entirely) behind its port, exactly as every other optional external integration in this codebase does.
- This ADR does **not** implement a SYNTHERA adapter, the port it would sit behind, or any of its decision logic. It only records that, should one be built, it attaches as an adapter behind a new port, never inside `cairn_kernel`, and never as something a tenant-scope check (§2) or a VAID verification (§3) depends on to function.

### 5. What this unit implements, and what it does not

Per the product owner's explicit instruction, this ADR and its implementation are split:

- **Implemented in this unit, on acceptance of this ADR's propagation decision (§1/§2) alone:** the `Principal` propagation fix — `ToolHandle` carries the principal, every one of the eight bounded-context servers enforcing tenant scope from it, and tests proving a call authenticated for tenant A cannot read tenant B's data even with the (currently nonexistent) RLS layer assumed bypassed.
- **Explicitly deferred, pending the product owner's acceptance of this ADR:** the VAID library integration (§3) and any SYNTHERA adapter (§4). No VAID or SYNTHERA code, dependency, or wiring is added by this unit — `tests/contract/test_no_vaid_synthera_dependency.py`'s negative proof continues to hold exactly as it does today, with this ADR document itself added to that test's documented-exception list (the same treatment `r5-integration-boundaries.md` already has), because this document, like that one, is now a second place required to name them.

## Consequences

**Positive**

- Closes a real, previously-documented gap: tenant scope enforcement no longer depends on an argument the caller supplies about itself; it depends on what the gateway actually authenticated.
- `cairn_kits` gains no new external dependency to do this (`Principal` already lives in `cairn_kernel.security`, already importable from `cairn_kits` under `kits-purity`).
- Sets up ADR-019's agent tool calls to inherit this same fix with no further change at the gateway layer: an agent's `ToolInvokerPort` call, once wired to `McpGateway.call_tool`, is covered automatically.
- Gives VAID a concrete, narrow, core-only integration point (identity verification only, scope-shrinking only) and keeps SYNTHERA genuinely optional — neither can become a backdoor around the tenant checks §2 adds, because §2 does not know or care which authenticator produced the `Principal` it is checking.

**Negative**

- `ToolHandle`'s signature change is breaking for every existing bounded-context server and every test that calls `.handle(...)`/`registry.invoke(...)` directly; this unit's fix PR touches all eight servers and their tests, not just the ones with an existing known gap.
- Two authenticators (OIDC bearer token, VAID) must be kept behaviourally aligned once VAID lands — the same "two implementations of one port" maintenance cost ADR-019 already accepted for `AgentLoopPort`.
- A VAID's scope-narrowing logic is new, security-sensitive code once built; getting "scope can only shrink" wrong would be a real hole, exactly as ADR-019 §3 already says about a wrongly-declared tool capability.

**Neutral**

- Whether VAID verification lives in `cairn_kernel` directly or a new sibling leaf package is a detail for the implementation unit that builds it, not fixed by this ADR beyond "core, not an adapter."
- SYNTHERA's actual port shape, and whether CAIRN ever builds an adapter for it at all, remains open; this ADR commits only to where it would attach if one is ever built.

## Alternatives considered

1. **Leave the gap as a per-server caller-supplied-argument check**, as R6-09/R6-10 did pragmatically for their own units. Rejected: it was already flagged as a real gap in those units' own PRs, and ADR-019's agents make it worse, not better, by adding an automated caller whose arguments are model output.
2. **Fix the propagation gap without an ADR**, as a plain bug fix. Rejected by the product owner's own framing of this unit: the fix changes a port's signature across all eight servers, which is exactly the kind of structural, cross-cutting decision this repository's own process (ADR-011, ADR-019) already treats as ADR-worthy, and bundling the VAID/SYNTHERA decision with it is the product owner's explicit request.
3. **Decide VAID/SYNTHERA's architecture without touching the propagation gap.** Rejected: VAID's "scope can only shrink" guarantee (§3) is meaningless unless every handler actually enforces the scope it's given, which is precisely §1/§2.
4. **Implement VAID and/or SYNTHERA now, in the same unit as the propagation fix.** Rejected by explicit product-owner instruction: this ADR's acceptance gates that work; the propagation fix does not wait for it.

## If rejected

The propagation gap stays open exactly as R6-09's PR described it, and every future bounded-context server repeats the same per-server workaround rather than a single enforced shape. VAID and SYNTHERA remain exactly what `docs/specs/r5-integration-boundaries.md` already says they are today: a documented, unimplemented boundary, with no change to that status.
