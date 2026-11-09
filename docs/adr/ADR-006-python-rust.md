# ADR-006: Python 3.12 for domain and application, Rust for transformation and measured hot paths

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §4.1, §17, ADR-001

## Context

The reference portfolio is dominated by Python 3.12 for platform and service logic, with Rust used where deterministic parsing and transformation performance matter. CAIRN is greenfield (ADR-017), so the choice rests on team skills and component fit, not on reusing portfolio code. It should still avoid turning every module into a polyglot project.

## Decision

- Python 3.12 for domain, application, API, workers, adapters and tooling.
- Rust in `transform-core`: parsing, detection, diff generation and validation of source code. Rust may also be used for other measured hot paths, but not as a default.
- The Rust workspace and first crates are established in R0, not deferred to R3.
- The boundary is a narrow FFI or CLI contract with versioned inputs and outputs; no Python module logic moves into Rust.
- Any proposal to introduce another language requires a new ADR.

## Consequences

**Positive**

- Leverages the strongest existing team skills while keeping new code in one language by default.
- Deterministic transformation is fast and isolated from the Python runtime.
- Clear performance boundary for the one genuinely compute-heavy component.

**Negative**

- Two toolchains in CI and local setup from R0.
- The FFI/CLI boundary needs its own contract tests.
- The team must carry Rust capability immediately; this is accepted, not deferred.

**Neutral**

- Python remains the default; Rust is justified per component, not per module.

## Alternatives considered

1. **All Python.** Simpler toolchain, but transformation performance and parsing robustness suffer.
2. **All Rust or all Go.** Consistent performance story but a poor match for team skills and slower delivery.
3. **TypeScript services.** Fits the console but not the domain and data workloads.

## If rejected

Choose either rewrite cost across the portfolio or a performance and reliability risk in the transformation engine.
