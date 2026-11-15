# Mapping registry seed review (R2-02)

Spec row R2-02: "Seed service map for pilot provider pairs | L | R2-01 |
Top 40 services per pair; approximate/unavailable labelled." Spec section
7.4's seed-dataset table: "Service map | ... | Top 40 services per
provider pair used in pilot." ADR-004: "Initial seed coverage is the top
40 services per pilot pair; gaps are labelled `UNRESOLVED`."

## What this is

`mappings/service-map.yaml` now carries the real candidate content for
the pilot service-map seed, replacing R0-14's six-entry illustrative
placeholder. The pilot provider pairs targeted are the ones already
assumed elsewhere in this repo (`docs/pilot/`, spec section 7.2's own
illustrative examples, and the file's own pre-existing entries): **AWS ->
GCP** (primary pair, reaches the ADR-004 top-40 floor) and **Azure ->
GCP** (secondary pair, a partial seed — see "What this is not" below).

No new provider pair was invented for this story.

## Candidate release

- **Version:** `2026.11.2`
- **Status (real, per 700/R2-01's workflow):** `IN_REVIEW`
- **Proposed by:** this session, as a stand-in pilot architect actor,
  against a `FakeMappingRepository` in
  `packages/modules/tests/test_mapping_seed_review.py` — proving the real
  content moves cleanly through the real `MappingService.propose` /
  `MappingRepository.propose` code path to `IN_REVIEW` and stops there.
  No Postgres row for this version exists anywhere; nothing here is
  claimed to be running against a live, persistent registry.
- **Allan's review and publish decision is outstanding.**

## Coverage summary

51 entries total.

| Equivalence | Count |
|---|---|
| `EXACT` | 2 |
| `APPROXIMATE` | 46 |
| `UNAVAILABLE` | 1 |
| `UNSUPPORTED` (see naming note below) | 2 |

By pilot pair:

| Pair | Entries | Top-40 floor met? |
|---|---|---|
| AWS -> GCP | 42 | Yes |
| Azure -> GCP | 9 | **No — partial seed, flagged honestly rather than padded** |

## What this is not

- **Not a full top-40 seed for the Azure -> GCP pair.** ADR-004 asks for
  "the top 40 services per pilot pair" (plural). Reaching a genuine,
  evidence-grounded top 40 for a second pair in the same session as the
  first would have meant either inventing confident judgements this
  session could not actually ground in public documentation, or
  mechanically padding the file with low-value/duplicate entries just to
  hit a number — both of which this story's own instruction ("entries
  with no honest equivalence judgement are UNRESOLVED, not guessed")
  rules out. The Azure pair's 9 entries are real, evidence-grounded
  judgements; the remaining ~31 are an honest gap, not silently implied
  to exist. Closing it is follow-up work, not claimed here.
- **Not published.** The real candidate content above is `IN_REVIEW`
  only. No `PLATFORM_OPERATOR`-gated publish action was invoked for it —
  that decision is Allan Smeyatsky's alone, per ADR-004's named-approver
  requirement, and is explicitly out of scope for this session.
- **Not a change to 700/R2-01's schema, API shapes, or workflow
  mechanism.** This story replaces `mappings/service-map.yaml`'s
  *content* only.

## A naming note: `UNRESOLVED` vs the shipped `Equivalence` enum

ADR-004's decision text names the equivalence enum as `EQUIVALENT,
APPROXIMATE, UNAVAILABLE, UNRESOLVED`. The enum R2-01 actually shipped
(`cairn_contracts.estate.model.Equivalence`) is `EXACT, APPROXIMATE,
UNAVAILABLE, UNSUPPORTED` — no `UNRESOLVED` member exists, and `EXACT`
rather than `EQUIVALENT` is the real name for a clean match. This
predates this session (R2-01/700 shipped and merged it as PR #57) and is
not something this story's brief authorized changing, since the brief is
explicit that this story "replaces [the seed file's] content, not its
schema."

This session resolved the mismatch by treating `UNSUPPORTED` as the real
schema's stand-in for ADR-004's "gaps are labelled `UNRESOLVED`" concept
— a judgement this registry version cannot confidently make yet, as
distinct from `UNAVAILABLE`'s different, already-settled meaning ("the
judgement has been made: no equivalent exists," e.g. the
`s3-object-lock-to-gcs-retention` entry's legal-hold semantics). The two
`UNSUPPORTED` entries in this seed (`aws-outposts-to-unresolved`,
`azure-arc-to-unresolved`) carry no `target_service` at all, precisely so
nothing is guessed.

One adjacent finding, not fixed here because it is outside this story's
scope and does not affect this seed's `IN_REVIEW`-only content:
`cairn_modules.mappings.resolver.resolve_mapping` (R2-01) special-cases
only `Equivalence.UNAVAILABLE` for its fail-closed "never substitute"
behaviour; an `UNSUPPORTED` entry with no `target_service` would resolve
without raising if a published release's resolver path were ever queried
against it. This never happens for this story's own content, since it is
never published, but is worth a future story's attention before any
`UNSUPPORTED` entry is ever part of a published release.

## Clean-room evidence

Every `evidence` string in the real candidate entries names only public
vendor documentation (AWS/Azure/GCP's own product documentation) — never
a reference-portfolio repository, per ADR-017. This is enforced by
`packages/modules/tests/test_mapping_registry.py::test_seed_no_evidence_string_names_a_reference_portfolio_repository`,
checked against every repository named in
`docs/specs/reference-register.md` and the spec's section 17 source
analysis. The previously-committed illustrative file's `"CAIRN service
map seed; ..."` evidence prefix (itself already clear of any
reference-repository name) is also removed in this rewrite, in favour of
citing only the vendor documentation directly.
