# Transformation golden corpus review (R3-03)

Spec row R3-03 ("Rust transformation engine: parse, detect, transform;
Python manifest and port" -- acceptance criteria spanning the full
parse->detect->transform pipeline). ADR-015: "Use the reference engines
only to enumerate behaviours and edge cases; capture each as a golden
test written for CAIRN, not as copied code or fixtures" and "record
detector and pattern versions, applied/skipped/unsupported outcomes and
reasons in the transformation manifest." This is the unit (727, the
final of three completing R3-03) where the full end-to-end corpus,
across the whole pipeline, was built and reviewed against those two
sentences.

## What this is

`tests/golden/transform/` now carries a real, CAIRN-authored corpus of
small synthetic Terraform/HCL and Python repositories, each run through
the *real* pipeline end to end: 721's fake source-fetch adapter ->
722/723's parsers -> 724's detector -> 725's patcher, chained by 726's
compiled `cairn-transform-cli` binary and read by 726's
`TransformationManifest` -- never the fake transformation adapter,
because the fake exists to stand in for the real pipeline in *other*
units' tests, and standing in for it here would only prove this
corpus's own assumptions, not the pipeline.

No new provider pair, rule, or language was invented for this unit.
Every scenario in the corpus exercises one of 724's two existing
detector rules (`tf-s3-bucket-inline-acl-deprecated`,
`py-import-imp-deprecated`) or one of 722-725's four prior units' own
deliberate-break cases, restated end to end rather than re-litigated.

## Coverage summary

10 golden repositories, 20 tests in `tests/golden/transform/
test_golden_corpus.py` (plus the 4 new unit tests in
`packages/modules/tests/test_transformation_engine.py` for the fix
described below, and 2 new Rust tests in
`packages/transform-core/cli/src/main.rs` for the same fix at the layer
it originates).

| Scenario | Repository | Expected outcome |
|---|---|---|
| Clean Terraform, nothing to flag | `terraform_clean` | empty manifest |
| Clean Python, nothing to flag | `python_clean` | empty manifest |
| ACL deprecation, happy path | `terraform_acl_deprecated` | `APPLIED` |
| `imp` deprecation, happy path | `python_imp_deprecated` | `APPLIED` |
| 722's deliberate break (unterminated block) | `terraform_unterminated_block` | `UNSUPPORTED` (synthesized -- see below) |
| 723's deliberate break (f-string) | `python_fstring_unsupported` | `UNSUPPORTED` (synthesized -- see below) |
| 724's deliberate break (ACL inside `dynamic` block) | `terraform_acl_dynamic_skip` | `SKIPPED` |
| 724's deliberate break (relative `from . import imp`) | `python_relative_imp_skip` | `SKIPPED` |
| 725's deliberate break (runtime-interpolated ACL value) | `terraform_acl_interpolated_unsupported` | `UNSUPPORTED` |
| Realistic multi-file pilot repository (Terraform infra + Python app + an out-of-scope file) | `mixed_pilot_scope` | two `APPLIED` entries, the out-of-scope file absent from the manifest entirely |

Every repository above also has a determinism test: fetched and
transformed twice, the resulting `TransformationManifest` is asserted
equal both times.

## A real gap this unit's end-to-end pass found, and fixed

Running the full pipeline end to end -- not just each stage in
isolation, which is what 722-726 individually tested -- surfaced a real
problem, not a hypothetical one: for 722's deliberate-break case
(an unterminated HCL block, `ParseOutput::Error`) and 723's
(an f-string, `ParseOutput::Unsupported`), 724's detector correctly
produces an empty `DetectionSet` (its own documented "no AST, no
detections" behaviour), so 725's patcher produces a `ChangeSet` with
zero entries. Before this unit, that file's line in the final manifest
was **indistinguishable from a file that parsed perfectly and simply
had nothing to flag** -- the parse failure was swallowed by the time it
reached the manifest, which is exactly the failure mode ADR-015's
"applied/skipped/unsupported outcomes and reasons" sentence exists to
prevent.

The fix, scoped to exactly this gap:

- `packages/transform-core/cli/src/main.rs` -- `CliOutput` gained one
  new field, `parse_status` (`{"status": "PARSED"|"UNSUPPORTED"|"ERROR",
  "reason": string|null}`), carrying the parse stage's own outcome
  forward, which no type before this unit surfaced anywhere a
  Python-side manifest could read it.
- `packages/modules/src/cairn_modules/transformation/engine.py` --
  `build_manifest` now synthesizes one explicit `ManifestEntry`
  (`rule_id = "cairn-transform-core/parse-incomplete"`, `outcome =
  UNSUPPORTED`, the parse stage's own reason) for a file whose
  `change_set` is empty *because parsing never produced an AST to
  detect against* -- read defensively (`raw_output.get("parse_status",
  ...)`), so the pre-existing hand-written fixtures in
  `test_transform_core_contract.py` (which predate this field and never
  set it) keep passing unmodified, read as the implicit `"PARSED"`
  status they always represented.

This is the rediscovery ADR-015's own "Negative" consequence names:
*"Undocumented edge cases in the reference engines ... must be
rediscovered through testing."* 724's `SkippedCandidate`/725's
`ChangeOutcome::Unsupported` paths were already explicit end to end
without any fix -- this unit's corpus confirms that chain works, it
does not touch it. Only the pure parse-stage failure path needed
closing, and now does.

## What this corpus deliberately does not cover

- **Java and .NET.** Out of scope for R3 entirely (ADR-015: "R3 scope is
  Terraform/HCL and Python source. Java and .NET are out of scope until
  a new ADR"). No fixture, rule, or test anywhere in this corpus
  references either.
- **Any rule beyond 724's existing two.** This unit authors no new
  detector rule. 725's handover flagged a real, separate gap -- no rule
  in the corpus exercises "a detection whose safe rewrite needs R2-01's
  mapping resolver" -- and this unit does not close that gap either; a
  new rule would need authoring first, which is new rule-authoring work,
  not a golden-corpus unit's job.
- **Persistence of a transformation run beyond what 726 already
  shipped.** This unit's tests read `TransformationManifest` objects
  returned in-process from `SubprocessTransformationPort.transform`;
  they do not add new coverage of `transformation_run` (migration 0008)
  beyond 726's own tests, which already cover it.
- **The Rust HCL/Python expression-grammar gaps 722/723 already named
  out of scope** (binary/unary operators, `for` expressions, control
  flow, comprehensions, etc.) -- those are parser-scope decisions from
  two prior units, not something a golden-corpus unit revisits.
- **A performance/scale corpus.** Every repository here is a handful of
  small files, chosen to exercise one scenario clearly, not a stress
  test of the pipeline at pilot-repository scale.

## Clean-room boundary

No reference repository (`cloudshift_v2`, `refactor`, `refactor2`,
`newrefactor`) was read, opened, or referenced while building this
corpus. `docs/specs/reference-register.md` carries this unit's own entry
confirming that explicitly, rather than leaving it ambiguous or silently
relying on the pre-existing R3-02/R3-03 entry from an earlier unit. Every
scenario in the table above was already a named, documented behaviour in
721-726's own handovers (`~/solara/lz2026/s721-handover.md` through
`s726-handover.md`) before this unit started; this unit's own
contribution was restating each as an end-to-end test and closing the
one gap described above.

## An explicit invitation for Allan

This review is **non-blocking** -- the corpus, the fix, and this unit's
tests all stand on their own regardless of when or whether anyone reads
this document. That said: Allan Smeyatsky's sanity-check of whether the
ten scenarios enumerated in the coverage table above are *the right
ones* for the pilot -- not just "do these specific cases pass", but "is
this the set of pilot-scope transformation behaviours worth having a
golden test for at all" -- would be genuinely useful, the same way his
review of the R2-02 mapping seed (`docs/specs/mapping-seed-review.md`)
was invited without blocking anything on it. No publish-gated or
approval-gated action is waiting on this.
