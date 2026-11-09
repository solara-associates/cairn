# ADR-004: One mapping registry with immutable releases

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky); named mapping release approver
- **Related:** Implementation spec §7, ADR-003, ADR-016

## Context

Service, region and jurisdiction mappings are the difference between an honest recommendation and a fabricated one. Across the portfolio these mappings are hard-coded, mutable, or asserted without caveats. Design artefacts must be reproducible months later.

## Decision

Provide a single mapping registry service with:

- Versioned releases covering service equivalence, region availability and jurisdiction rules.
- An explicit equivalence enum: `EQUIVALENT`, `APPROXIMATE`, `UNAVAILABLE`, `UNRESOLVED`.
- A caveat and rationale field for every non-equivalent mapping.
- Human review before publication; published releases are immutable.
- The named approver is Allan Smeyatsky, the product owner, until delegated.
- Initial seed coverage is the top 40 services per pilot pair; gaps are labelled `UNRESOLVED`.
- Every design artefact records the mapping release id and version.

The resolver is the only way modules obtain a mapping. Hard-coded service maps in modules are forbidden.

## Consequences

**Positive**

- Reproducible designs and TCO calculations.
- Approximate or missing mappings are visible rather than silent.
- One place to correct a mapping for all products.

**Negative**

- A correction requires a new release rather than a row update.
- Publishing has review latency.
- Seed coverage is bounded initially and will show many `UNRESOLVED` entries.

**Neutral**

- Jurisdiction packs reuse the same release and immutability machinery (ADR-016).

## Alternatives considered

1. **Mutable mapping table.** Cheap hotfixes, but breaks reproducibility and audit.
2. **Hard-coded maps per module.** Fastest, but divergent and unauditable.
3. **Resolution at render time from a spreadsheet.** Human-editable but not versioned or testable.

## If rejected

Approximate mappings become invisible, and design or cost outputs imply certainty CAIRN does not have.
