# Good first issues

Unit 829 (`docs/roadmap-r4-r5-oss.md` §3). These are real, already-documented
gaps in this repository -- not invented for this list -- chosen because they
are small, well-scoped, and safe for an external contributor with no cloud
access, no security context, and no standing in this project to pick up
without a maintainer's judgement call first. None of them touch the kernel
execution gate, the evidence/signing path, or tenancy/RLS machinery; those
need a maintainer, per this document's own scope.

No GitHub issue has been opened for any of these yet. This file is the
candidate list; turning an entry into an actual issue (and labelling it
`good first issue`) is a maintainer action.

## 1. Extend the Azure -> GCP mapping seed

**Where:** `mappings/service-map.yaml`, reviewed in
`docs/specs/mapping-seed-review.md`.

**The gap, in the review doc's own words:** the AWS -> GCP pair reaches
ADR-004's top-40-per-pair floor (42 entries), but Azure -> GCP has only 9 --
"a partial seed, flagged honestly rather than padded." The review doc names
this explicitly as "not a full top-40 seed for the Azure -> GCP pair" and an
"honest gap, not silently implied."

**The task:** research and propose additional Azure -> GCP service
equivalences, each grounded in vendor documentation (per the existing
entries' own evidence discipline -- see the review doc's "vendor
documentation ... never" sourcing rule), following the same schema and
`equivalence`/`caveat`/`UNRESOLVED`-labelling conventions the existing 51
entries already use.

**Why it's safe:** pure data/research content behind the existing mapping
schema. No code path changes. Allan is ADR-004's named sole approver for
publishing a mapping release, so a contributor's PR proposes candidate
content for maintainer review -- it does not publish anything itself.

## 2. Add a golden-corpus scenario exercising the mapping resolver

**Where:** `tests/golden/transform/`, documented in
`docs/specs/transform-golden-corpus-review.md`'s "What this corpus
deliberately does not cover" section.

**The gap, in the review doc's own words:** "no rule in the corpus exercises
'a detection whose safe rewrite needs R2-01's mapping resolver' ... and this
unit does not close that gap either; a new rule would need authoring first,
which is new rule-authoring work, not a golden-corpus unit's job."

**The task:** author one new, small detector rule (following the existing
two rules' pattern in the Rust detector core) whose safe rewrite consults
R2-01's mapping resolver, add a golden repository exercising it under
`tests/golden/transform/`, and extend the coverage table in the review doc.

**Why it's safe:** additive -- a new rule and a new golden fixture, not a
change to any existing rule, the parser, or the manifest schema. Entirely
within the clean-room, CAIRN-authored corpus; no reference-repository code
is touched.

## 3. Add a performance/scale corpus repository

**Where:** `tests/golden/transform/`, same review doc, same "deliberately
does not cover" section.

**The gap, in the review doc's own words:** "A performance/scale corpus.
Every repository here is a handful of small files, chosen to exercise one
scenario clearly, not a stress test of the pipeline at pilot-repository
scale."

**The task:** add one golden repository sized closer to a real pilot
repository (many files, mostly clean, a handful of the two existing rule
violations scattered through it) and a determinism/timing-sanity test
alongside the existing per-repository determinism tests, so the pipeline's
behaviour at scale has at least one concrete fixture.

**Why it's safe:** purely additive test fixture work against the existing,
already-merged pipeline. No production code path is required to change for
the corpus to exist (only to pass, if it currently doesn't -- which is
itself useful signal for a maintainer, not something a contributor needs to
fix as part of the same PR).

## Explicitly excluded, and why

Several other real, documented gaps in this repository were considered and
rejected for this list:

- **R4's two inherited judgement calls** (`docs/specs/r4-inherited-judgement-calls.md`)
  -- both are explicitly "accepted, pending Allan's review." Changing either
  default is Allan's decision to make first, not a contributor's to implement
  ahead of that decision.
- **The reference-register provenance list** (`docs/specs/reference-register.md`,
  item 5 of `docs/acceptance/r0-20-review.md`'s open review items) -- flagged
  as something "Allan should personally sanity-check" because several listed
  repository names may read as prior-employer or client codenames. Not a
  task for an outside contributor to touch.
- **Support-access residency, the irreversible-rollback proof (unit 794), and
  anything in `packages/modules/src/cairn_modules/risk_policy/`** -- all
  cloud-adjacent, security-sensitive, or part of the execution
  gate/evidence/tenancy machinery this document's own scope excludes.
- **R2's console demo walkthrough** (`docs/acceptance/r0-20-review.md` item
  11) -- per this estate's own demo-readiness policy, only Allan's own
  browser walkthrough can pass that gate; it is not a contribution task.
