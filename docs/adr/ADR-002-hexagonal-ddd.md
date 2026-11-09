# ADR-002: Clean/Hexagonal architecture with DDD, enforced by import-linter

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §4.2-§4.3, ADR-001

## Context

The portfolio shows that unenforced boundaries decay quickly: domain logic drifts into handlers, cloud SDKs leak into business rules, and modules import each other's infrastructure. CAIRN cannot afford that because one kernel and one canonical model must serve several products.

## Decision

Adopt Clean/Hexagonal architecture with DDD per bounded context:

- Each module separates `domain`, `application`, `infrastructure` and `presentation`.
- All external effects go through ports declared by the domain or application layer and implemented by adapters.
- Shared DTOs live in `contracts/`, not in modules.
- `.importlinter` contracts enforce the dependency rules and run in CI. A deliberate violation must fail the build.

Forbidden imports include adapters, apps, FastAPI, SQLAlchemy, `google.cloud`, `boto3` and `azure` from domain code, and other modules' infrastructure from any module.

## Consequences

**Positive**

- Domain logic is testable without cloud or database.
- Adapters are replaceable per provider.
- Boundary violations are caught by tooling rather than review.

**Negative**

- More packages and boilerplate than a framework-first layout.
- Learning curve for contributors coming from the source repos.
- Contract maintenance when legitimate cross-module flows appear.

**Neutral**

- Module-to-module communication is via `contracts/` DTOs or events, never direct infrastructure imports.

## Alternatives considered

1. **Framework-first (FastAPI/SQLAlchemy throughout).** Faster for a prototype; reproduces the maintenance problems in the source portfolio.
2. **Vertical slices without enforced layers.** Pragmatic but does not prevent SDK leakage.
3. **Architecture by convention only.** Has already failed across 43 repositories.

## If rejected

Boundaries drift, the kernel fragments again, and conformance checks lose meaning.
