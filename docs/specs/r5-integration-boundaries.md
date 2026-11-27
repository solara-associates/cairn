# R5 integration boundaries: VAID and SYNTHERA

Unit 825, R5 integration boundaries. Dependencies: 818 (`McpRegistry`/
`McpGateway`, `packages/kits/src/cairn_kits/mcp/registry.py` and
`apps/mcp-gateway/src/cairn_mcp_gateway/gateway.py`) and 819 (`A2ABridge`,
`apps/mcp-gateway/src/cairn_mcp_gateway/a2a_bridge.py`), both already merged.
No new dependency is added by this unit.

## Status: superseded for VAID by ADR-020 §3; unchanged for SYNTHERA

> **Updated 2026-11-27 (unit 915).** This document originally said that
> nothing in this repository talked to *either* system. That is now true of
> only one of them. **ADR-020 §3, accepted 2026-11-27, adopted VAID for
> real**, through the very attach point this document described below —
> which is also what this document's own rule asked for: update it first,
> then add the code. This section is that update.

**VAID: implemented, in core.** A caller may present a VAID at
`McpGateway.authenticate` — exactly attach point 1 below, used as written and
not extended. `cairn_kernel.vaid` verifies it offline against a pinned trust
anchor using the published open-source `vaid-mint` library, and derives the
`Principal` and narrowed scope it carries. It is **off by default**
(`CAIRN_VAID_ENABLED`), and callers presenting a bearer token are unaffected.
Two things that attach point 1 did not anticipate, and which the ADR and the
implementing module both record rather than leave implicit:

- A VAID is not only an identity, it carries an **attenuating scope** — so
  verification also checks that authority narrows at every hop of a
  delegation chain, and that a VAID presented alongside a bearer token does
  not claim more than that token grants. Scope can only ever shrink.
- Request-level **proof of possession** is *not* done at this seam, because
  `McpGateway.call_tool` is an in-process call with no HTTP request to bind
  a signature to. A VAID verified here is genuine, current and attenuated; it
  is not on its own proof the presenter holds the key.

**SYNTHERA: still a documented boundary, now with a port.** Nothing in this
repository imports, depends on, configures or names it. ADR-020 §4 kept it
exactly where this document put it — optional, commercial, behind a port —
and unit 915 built *the port only*: `cairn_kernel.governance`, with a no-op
default adapter, so CAIRN runs fully with nothing bound. **No client, SDK,
commercial code or decision logic for it exists anywhere here.** Note this
means the port, rather than attach point 2 below, is where a policy/budget/
revocation integration would now attach; attach point 2 remains the A2A
*peer* story, which is a different question and is unchanged.

`tests/contract/test_integration_boundaries.py` is the proof of all of the
above, re-checked on every CI run, and it asserts each half differently
because the two halves now differ: VAID is asserted **present and confined
to core**, and SYNTHERA is asserted **absent, with the port it would attach
behind present and holding nothing but its own no-op default**. See "How the
proof stays honest" below.

The original rule still stands for everything not yet wired: if an
integration is actually built, update this document first — naming the real
attach point and what changed — then add the code, not the other way around.

## What VAID and SYNTHERA are, for this document's purposes

These two names belong to a separate, unrelated Solara project. This
document was written treating both as purely **abstract placeholders** for
two *kinds* of external system that any agent platform eventually needs to
consider integrating with. That still describes SYNTHERA's status here;
**VAID is no longer a placeholder** — ADR-020 §3 adopted the real,
published, open-source thing, and the paragraph below should be read as the
history of how the attach point was arrived at rather than as a current
description of VAID's status:

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

> **This attach point is now in use.** ADR-020 §3 implemented it as
> described — a second verifier of the same credential-in/`Principal`-out
> shape, selected at `McpGateway.authenticate`, with no new port and no
> change to `call_tool`'s ordering guarantee. What follows is the original
> text, which turned out to need no correction.

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
- Not a dependency, even an optional one — **for SYNTHERA**. No package,
  import or configuration anywhere in this repository names it (see the
  proof below). This is no longer true of VAID: `vaid-mint` is a pinned
  dependency of `packages/kernel`, per ADR-020 §3.
- Not a commitment that a *SYNTHERA* integration will ever be built. ADR-020
  §4 records only where one would attach — behind
  `cairn_kernel.governance` — if it ever is.

## How the proof stays honest

`tests/contract/test_integration_boundaries.py` asserts three groups of
claims, because after ADR-020 the two systems' statuses differ.

**SYNTHERA is absent**, by the original three independent scans over the
repository: every `*.py` file's `ast`-parsed import statements, every
`pyproject.toml`/`Cargo.toml`'s dependency text, and a case-insensitive text
scan over every file git tracks (catching a stray network host string,
config key, or comment, which an import/dependency scan alone would miss).
Four paths are excluded, each required to name it: this document, ADR-020,
the ADR index whose decision-log row carries ADR-020's title, and the test
file itself.

**VAID is present and confined to core**: only `cairn_kernel` imports the
library in the shipped import graph, only `packages/kernel/pyproject.toml`
declares it, that declaration carries an upper version bound, and
`cairn_kernel` really does import it — the last so that the confinement
check cannot pass by VAID having quietly disappeared.

**SYNTHERA could only attach behind the port**: the port exists with the four
concerns ADR-020 §4 names; the only implementations of its shape anywhere in
the shipped tree are the port itself and the kernel's no-op default, detected
*structurally* (any class defining all four methods counts, named or not), so
an adapter could not land under another name unnoticed; the port's own module
imports nothing but `cairn_kernel` and the standard library, so there is no
import a vendor could hide in; and no `cairn_kernel` flow imports the port,
which is what "CAIRN works fully without it" means structurally.

Each negative scan was verified by temporarily adding, to a scratch module in
this tree, a fake `import synthera_client`, a fake dependency string in
`packages/adapters/pyproject.toml`, a fake `import vaid_mint` outside the
kernel, and a class implementing all four port methods — confirming that each
applicable check fails, then removing them and confirming all of them pass
again. That run is recorded in unit 915's PR description.
