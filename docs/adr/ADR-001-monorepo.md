# ADR-001: Monorepo with independently deployable apps

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §4, ADR-002, ADR-006

## Context

The source portfolio is 43 separate repositories that repeatedly reimplement the same kernel concerns. CAIRN's main integration risk is the shared kernel plus cross-module conformance, both of which require changes that span many packages at once. The platform also ships several independently deployed services (`api`, `worker`, `scheduler`, `mcp-gateway`, `console`, `cli`).

## Decision

Use a single monorepo with:

- A `uv` Python workspace, a `Cargo` Rust workspace and a `pnpm` workspace, all driven from one `Makefile`.
- `packages/` for libraries (kernel, contracts, kits, adapters, modules, transform-core) and `apps/` for deployment entrypoints.
- One CI pipeline with path-filtered jobs; each app still builds and deploys as its own signed image.

Independently deployable does not mean independently versioned: releases are tagged at repository level.

## Consequences

**Positive**

- Kernel and contract changes are atomic across every consumer.
- One toolchain, one dependency graph, one conformance run.
- Cross-module refactors and contract tests are cheap.

**Negative**

- CI must use path filters and caching to stay within budget.
- Repository access is coarser than per-package access.
- All packages share one release tag, so partial releases are not possible.

**Neutral**

- Deployment independence is preserved through per-app images and Terraform targets.

## Alternatives considered

1. **Polyrepo per module.** Strong ownership isolation but reintroduces the fragmentation CAIRN is meant to remove.
2. **Monorepo with one deployable.** Simplest CI but prevents independent scaling and failure isolation.
3. **Monorepo with per-package semantic versioning.** Adds registry and version-negotiation overhead before any external consumers exist.

## If rejected

Expect package registry and versioning overhead, slower kernel evolution, and a realistic drift in conformance between modules.
