# Changelog

All notable changes to this project are documented here, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

This project follows the pre-1.0 versioning scheme in `docs/release-process.md`: `0.MINOR.PATCH`, where MINOR tracks a completed R-number milestone and breaking changes may occur between minors.

## [0.5.0] - 2026-11-24

First tagged release. Everything in it has been built and tested against deterministic fake adapters and one synthetic cloud estate. **No code in this repository has ever executed a write against a real cloud account.** Do not point this at a production environment.

### Added

- **Kernel (R0)** -- domain model, provider ports, signed hash-chained evidence envelopes, append-only audit ledger, multi-tenant Postgres with forced row-level security, conformance suite.
- **Assess (R1)** -- estate ingestion, posture checks against a control catalogue, cost/TCO baselines, 6R classification, signed evidence packages.
- **Design (R2)** -- target architecture generation, equivalence mappings, migration plans, pattern library, diagram and plan export.
- **Modernize (R3)** -- clean-room transformation engine for Terraform and Python, with unified-diff review, a Rust patcher and static validation.
- **Govern (R4, partial)** -- risk-tier policy engine, `ProviderExecutionPort` contract, GCP adapter skeleton, Terraform plan orchestration, rollback/compensation engine and approval console. All fake-adapter tested; the real-cloud proofs have not started.
- **Operate (R5)** -- FinOps, LLMOps, MLOps, resilience and sovereignty operate loops, MCP/A2A surfaces, and a first vertical accelerator pack. Complete, but built and tested only against fake/deterministic adapters and one synthetic cloud estate -- no real-cloud operate action has executed anywhere in this codebase.
- `make build` now runs as part of `make test`, so a single documented command sequence (`make bootstrap`, `make build`, `make test`) produces a green run from a clean clone.
- README gains a "Development" section with the exact local build/test commands, and states plainly that the `docker compose` quickstart needs no database.

### Fixed

- The console's nginx configuration (both the built image's default and the local quickstart's dev overlay) did not proxy any `/v1/*` API route to the API container -- every API call from the console silently received the console's own `index.html` instead of JSON, breaking every screen beyond sign-in. Both configs now proxy `/v1/` to the API, consistent with the existing `/healthz`/`/readyz` proxying.
- The local quickstart's OIDC flow never requested the `groups` scope, so dex never populated a `groups` claim and the API-side `CAIRN_OIDC_ROLES_CLAIM=groups` mapping found nothing -- every authenticated request resolved to zero roles and every RBAC-gated route returned `Forbidden`. The console's requested scope now includes `groups`.
- The bundled local demo identity held only `VIEWER`+`ENGINEER`, which cannot create a project (`TENANT_ADMIN`-only per the role model) -- leaving the quickstart's own "explore the read-only assessment screens" promise unreachable, since nothing seeds an initial project. The demo identity now also carries `TENANT_ADMIN`; this is a local, single-developer convenience only, not a real deployment's security posture.

### Removed

- `docs/specs/history-rewrite-spec.md`, superseded by `docs/specs/oss-launch-decisions.md`'s D0 (resolved 2026-11-20): the history rewrite it specified was determined unnecessary, and the document's own blob-hash inventory was no longer reachable in this repository's history.

### Hygiene

- Replaced the real GCP project identifier `solara-cairn-dev`/`-exec` with a neutral `<gcp-project-id>` placeholder in `docs/r4-acceptance.md`, `docs/specs/oss-launch-decisions.md` and a source comment in `cairn_modules.sovereignty.residency_sweep`.
- Renamed a prior-work codename and its description to neutral names across the architecture catalogue, the technical spec, a pattern definition, a contract test fixture and a mapping-registry test.
- Replaced two placeholder/sample email addresses (`REPLACE_ME@solara.associates` in a Terraform example, `alice@gmail.com` in a scanner test fixture) with `example.com` addresses.
- Removed remaining prior-work banking content that the previous pass had renamed rather than removed, in full, from `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md`, `CLOUD-ARCHITECTURE-PATTERNS.md`, `docs/specs/reference-register.md`, the `analytics` design pattern (deleted entirely, including its test fixture) and the `data-platform` pattern's evidence citation (pattern kept).

### Known limitations

- No governed customer-environment write exists anywhere in this codebase. R4's production adapter is deliberately unreachable through the execution gate (spec §5.4).
- R4's real-cloud proofs require a GCP project, IAM bindings and plan approvals that do not yet exist.
- `R-COV-01` (per-package coverage floor) is a pending conformance rule under an exception expiring 2027-03-31; there is no enforced coverage gate today.
- One console end-to-end test (design-journey regenerate) is quarantined for flakiness rather than fixed.
- The `docker compose` quickstart runs no database and is a local development convenience only -- it is not a deployment topology, and its data does not persist across restarts.
- No hosted service. No support or warranty promise without a separate engagement.
