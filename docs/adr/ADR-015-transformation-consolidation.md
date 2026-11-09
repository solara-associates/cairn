# ADR-015: Consolidate transformation on the cloudshift_v2 Rust core

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §17, ADR-006

## Context

The portfolio contains three related transformation codebases (`refactor`, `refactor2`, `newrefactor`) plus the Rust core in `cloudshift_v2`. Maintaining competing engines produces divergent behaviour, duplicated bug fixes and unclear ownership.

## Decision

- Adopt the `cloudshift_v2` Rust core as the single transformation engine.
- Wrap it in `transform-core` with a versioned input/output contract: parse, detect, transform, diff, validate.
- Record detector and pattern versions, applied/skipped/unsupported outcomes and reasons in the transformation manifest.
- Do not add features to `refactor`, `refactor2` or `newrefactor`; migrate any unique behaviour into the chosen core and capture it as a golden test.
- Retire the other engines from the CAIRN build.

## Consequences

**Positive**

- One engine, one behaviour model, one set of fixes.
- Rust performance and determinism are retained.
- Manifest and evidence give reviewable output.

**Negative**

- Porting unique behaviour from the other engines takes deliberate effort.
- Risk of losing undocumented edge-case handling.
- The chosen core must be hardened for sandboxing and limits.

**Neutral**

- Golden corpora from the retired engines are the migration safety net.

## Alternatives considered

1. **Keep two engines and choose per provider.** Doubles maintenance and confuses support.
2. **Build a new engine from scratch.** Discards proven code and delays R3.
3. **Wrap all three behind one interface.** Hides divergence rather than removing it.

## If rejected

Expect duplicate engines, inconsistent output and an ambiguous answer to "which transformation produced this diff?".
