# ADR-011: MCP per bounded context, with an A2A bridge for agent hosts

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §10, §11, ADR-002

## Context

Agent hosts and IDEs increasingly expect MCP, while multi-agent systems expect A2A. The portfolio has 34 repositories with some MCP surface, mostly ad hoc. A single mega-server would couple every tool to every domain and contradict the module boundaries.

## Decision

- One MCP server per bounded context (tenancy, ingestion, estate, posture, finops, mappings, design, transformation), exposed through an `mcp-gateway` registry.
- MCP tools call application services, never raw SQL or provider SDKs directly.
- The gateway handles auth, per-tenant authorization, rate limits and audit.
- An A2A bridge publishes agent cards and translates A2A tasks to the same application services.
- No AI or agent path may authorise an irreversible action; it can only propose, which a human or policy must approve.

## Consequences

**Positive**

- Tool surfaces follow domain boundaries and can evolve independently.
- One audited entry point for agent traffic.
- Interoperability with both MCP and A2A hosts.

**Negative**

- More servers to deploy and register.
- Two protocols and their version churn.
- Gateway is a critical path for agent features.

**Neutral**

- MCP/A2A is internal from R0 but only exposed to customers in R5.

## Alternatives considered

1. **One mega-MCP server.** Simpler deployment, but couples domains and creates a huge authorization surface.
2. **REST-only with an MCP shim.** Fewer moving parts, but loses native tool semantics and per-context auth.
3. **A2A only.** Narrows host compatibility.

## If rejected

Expect ad-hoc integrations per host and no consistent authorization or audit story for agents.
