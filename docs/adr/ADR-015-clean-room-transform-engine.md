# ADR-015: Build one transformation engine clean-room in Rust

- **Status:** Proposed
- **Date:** 2026-11-09
- **Deciders:** Architecture review (pending)
- **Related:** Implementation spec §17, ADR-006, ADR-017

## Context

The reference portfolio contains four transformation codebases (`cloudshift_v2`, `refactor`, `refactor2`, `newrefactor`). They are evidence that transformation can work, not a code supply: CAIRN is greenfield and no source is reused (ADR-017). Maintaining or resurrecting multiple engines would reproduce divergent behaviour, duplicated fixes and unclear ownership. Building none would remove a core Modernize capability.

## Decision

- Build a single new transformation engine in `transform-core`, in Rust, behind a versioned input/output contract: parse, detect, transform, diff, validate.
- Use the reference engines only to enumerate behaviours and edge cases; capture each as a golden test written for CAIRN, not as copied code or fixtures.
- Record detector and pattern versions, applied/skipped/unsupported outcomes and reasons in the transformation manifest.
- No reference engine is vendored, forked or added as a build dependency.
- One engine only: no per-provider or per-language alternative engines inside CAIRN.

## Consequences

**Positive**

- One engine, one behaviour model, one set of fixes.
- No inherited licence, provenance or prototype-quality debt.
- Rust performance and determinism are retained.
- Manifest and evidence give reviewable output.

**Negative**

- The engine must be built and hardened from scratch, so R3 is later than a lift/adapt plan implied.
- Undocumented edge cases in the reference engines must be rediscovered through testing.
- Sandboxing, limits and determinism need first-class design work.

**Neutral**

- Golden corpora are authored for CAIRN; reference repositories may inform which cases to cover but are not copied.

## Alternatives considered

1. **Lift and adapt the `cloudshift_v2` Rust core.** Fastest on paper, but violates ADR-017 and inherits unresolved provenance and quality risk.
2. **Keep multiple engines and choose per provider.** Doubles maintenance and confuses support.
3. **Defer transformation entirely.** Removes the Modernize product direction.

## If rejected

Expect either implicit code reuse that contradicts the greenfield decision, or multiple engines with inconsistent output and no clear answer to "which transformation produced this diff?".
