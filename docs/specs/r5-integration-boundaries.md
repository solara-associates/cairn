# R5 integration boundaries: VAID and SYNTHERA (documented, not implemented)

Unit 825, R5 integration boundaries. Dependencies: 818 (`McpRegistry`/
`McpGateway`, `packages/kits/src/cairn_kits/mcp/registry.py` and
`apps/mcp-gateway/src/cairn_mcp_gateway/gateway.py`) and 819 (`A2ABridge`,
`apps/mcp-gateway/src/cairn_mcp_gateway/a2a_bridge.py`), both already merged.
No new dependency is added by this unit.

## Status: documented boundary only, no implementation

**Nothing in this repository talks to VAID or SYNTHERA today.** There is no
import, no package dependency, no network host reference, no adapter, no
client, and no configuration naming either one, anywhere in the codebase.
`tests/contract/test_no_vaid_synthera_dependency.py` is a negative proof of
exactly that claim, re-checked on every CI run. This document exists solely
to record *where* such an integration could attach in the future, through
contracts that already exist for an unrelated reason (ADR-011's MCP/A2A
gateway), should Solara ever decide to build one. Building it is explicitly
out of scope for this unit and is not implied or scheduled by writing this
document.

If an integration with either system is ever actually wired in, the
expectation is: update this document first (naming the real attach point and
what changed), then add the code — not the other way around. The negative
proof test above is written to fail the moment any such wiring lands
undocumented, by design (see "How the negative proof stays honest" below).

## What VAID and SYNTHERA are, for this document's purposes

These two names belong to a separate, unrelated Solara project and are used
here purely as **abstract placeholders** for two *kinds* of external system
that any agent platform eventually needs to consider integrating with:

- **VAID-like**: an external agent/workload **identity-verification**
  service — something that would attest "this calling agent is who it
  claims to be," analogous to how `cairn_adapters.auth_oidc` already
  verifies a human/service bearer token for CAIRN's own principals.
- **SYNTHERA-like**: an external **agent substrate/host** — a system that
  runs other agents and would want to call into CAIRN's bounded contexts,
  or have CAIRN call into it, as a peer.

No code, credentials, wire formats, or other specifics of the real VAID or
SYNTHERA projects were consulted, referenced, or are needed to write this
document. The two attach points below are derived entirely from CAIRN's own
818/819 contracts, which were already designed to be generic across *any*
external MCP client or A2A peer — these two names are simply illustrative
of the category "some future external agent-identity service" and "some
future external agent substrate," nothing more.

## Attach point 1: VAID-like identity verification, as an MCP client gate

818's `McpGateway` (`apps/mcp-gateway/src/cairn_mcp_gateway/gateway.py`)
already separates "verify who is calling" from "resolve/invoke the tool":

```
principal = self.authenticate(token)      # JwtAuthenticator.verify
self.authorize(principal, tool_name)      # required_roles check
return self.registry.invoke(tool_name, arguments)
```

A VAID-like identity-verification service could attach **only** at the
`authenticate` step, as an alternative or additional `JwtAuthenticator`-shaped
verifier: something that, given a bearer credential, returns a `Principal`
(`cairn_kernel.security.Principal`) or raises `UnauthenticatedError`. This
requires no new port — `McpGateway.authenticate` already takes a token and
returns a `Principal` through exactly the swappable shape
`cairn_adapters.auth_oidc.JwtAuthenticator` fills today. A VAID-like verifier
would be a second implementation of that same shape, selected the same way
any other authenticator adapter is selected, with zero change to
`McpGateway.call_tool`'s ordering guarantee (authenticate, then authorize,
then — and only then — resolve/invoke).

It would **not** attach anywhere else: not inside `McpRegistry` (which never
sees credentials, by design — see registry.py's own docstring), not inside
a `BoundedContextServer`'s `ToolHandle` (which only ever sees `tool_name` and
`arguments`, never a token), and not inside `A2ABridge` directly (which
delegates all auth to the same `McpGateway.call_tool`).

## Attach point 2: SYNTHERA-like external agent substrate, as an A2A peer

819's `A2ABridge` (`apps/mcp-gateway/src/cairn_mcp_gateway/a2a_bridge.py`)
already publishes `AgentCard`s for every registered `BoundedContextServer`
and translates `A2AMessage`/`A2AResult` to and from an MCP tool call. A
SYNTHERA-like external agent substrate could attach in either direction
through this exact shape, with no new port invented:

- **Inbound** (SYNTHERA calling into CAIRN): an external caller presents a
  bearer token and an `A2AMessage {skill, input}` naming one of the
  `AgentCard`s `A2ABridge.agent_cards()` already publishes. `A2ABridge.send_task`
  already accepts exactly `(agent_id, skill, token, input)` — a real external
  caller is just a transport in front of that same call, authenticated the
  same way any MCP caller is (attach point 1, reused, not duplicated).
- **Outbound** (CAIRN calling into SYNTHERA): CAIRN would register a
  `BoundedContextServer` whose `ToolHandle` is, instead of an in-process
  callable, a thin adapter that serializes to `A2AMessage` over a real wire
  transport and deserializes the response back to an `A2AResult` — i.e. a new
  `ToolHandle` *implementation*, not a new `ToolHandle` *type*. `McpRegistry`
  and `McpGateway` would be entirely unaware the handle crosses a network
  boundary, exactly as the registry's own docstring already anticipates
  ("a later unit can swap the handle for a real transport without changing
  this registry's shape").

As the bridge module's own docstring already states, today's `AgentCard`,
`A2AMessage`, and `A2AResult` deliberately stop short of A2A's real wire
protocol (JSON-RPC over HTTP/SSE, signed cards, task lifecycle states, push
notifications). A real SYNTHERA-like peer integration would need to replace
this module's wire encoding — not its shape — per that same docstring's own
note. That work is unscoped and unscheduled by this document.

## What this document is not

- Not a design for an actual VAID or SYNTHERA integration — no endpoints,
  schemas, credentials, SLAs, or rollout plan are specified, because none
  are known or needed.
- Not a dependency, even an optional one — no package, import, or
  configuration anywhere in this repository names either system (see the
  negative proof below).
- Not a commitment that this integration will ever be built. It records an
  attach point that already exists as a side effect of 818/819's own
  generic design, nothing more.

## How the negative proof stays honest

`tests/contract/test_no_vaid_synthera_dependency.py` scans the entire
repository — every `*.py` file's `ast`-parsed import statements, every
`pyproject.toml`'s dependency lists, and a plain case-insensitive text scan
over the whole tree (catching a stray network host string, config key, or
comment, which an import/dependency scan alone would miss) — for the
substrings `vaid` and `synthera`, case-insensitively, excluding only this
specification document (which must name them) and the test file itself
(whose own source necessarily contains the strings it looks for). The test
was verified by temporarily adding a fake `import vaid_client` reference
elsewhere in the tree, confirming the test fails, then removing it and
confirming the test passes again — see the unit's PR description for that
verification.
