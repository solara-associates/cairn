# ADR-006: Python 3.12 for domain and application, Rust only for the transformation hot path

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §4.1, §17, ADR-001

## Context

The source portfolio is dominated by Python 3.12 for platform and service logic, with Rust used where deterministic parsing and transformation performance matter. CAIRN must reuse that strength without turning every module into a polyglot project.

## Decision

- Python 3.12 for domain, application, API, workers, adapters and tooling.
- Rust in `transform-core` only: parsing, detection, diff generation and validation of source code.
- The boundary is a narrow FFI or CLI contract with versioned inputs and outputs; no Python module logic moves into Rust.
- Any proposal to introduce another language requires a new ADR.

## Consequences

**Positive**

- Leverages the strongest existing skills and code in the portfolio.
- Deterministic transformation is fast and isolated from the Python runtime.
- Clear performance boundary for the one genuinely compute-heavy component.

**Negative**

- Two toolchains in CI and local setup.
- The FFI/CLI boundary needs its own contract tests.
- Contributors need some Rust familiarity for transformation work.

**Neutral**

- Python remains the default; Rust is justified per component, not per module.

## Alternatives considered

1. **All Python.** Simpler toolchain, but transformation performance and parsing robustness suffer.
2. **All Rust or all Go.** Consistent performance story but a rewrite of reusable Python assets and a hiring mismatch.
3. **TypeScript services.** Fits the console but not the domain and data workloads.

## If rejected

Choose either rewrite cost across the portfolio or a performance and reliability risk in the transformation engine.
