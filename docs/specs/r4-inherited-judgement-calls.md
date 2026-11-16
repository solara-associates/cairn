# Inherited judgement calls, decided and locked (R4-03 / unit 782)

R4's plan item 782: two judgement calls flagged forward by earlier units
-- 726's (R3-03b) `pattern_version <- parser_version` mapping and 730's
(R3-06) no-validation run sealing `outcome="PASS"` -- restated here as
**accepted, pending Allan's review**, each pinned by one regression test
so no later R4 unit can silently change either behaviour while building
on top of it. This unit changes no production behaviour; it documents
the existing default and locks it with a test. Following the same
non-blocking, flag-and-continue framing `docs/specs/mapping-seed-review.md`
(R2-02) and `docs/specs/transform-golden-corpus-review.md` (R3-03) used
for their own open judgement calls.

## 1. 726's `pattern_version <- parser_version` mapping

**Where:** `packages/modules/src/cairn_modules/transformation/engine.py`,
`build_manifest`, line 261:

```python
pattern_version = raw_output["parser_version"]
```

(the same value is threaded into `_entry_from_raw_change_entry` and
`_parse_failure_entry`'s `pattern_version=pattern_version` keyword args,
lines 266 and 272, and used to build every `ManifestEntry.pattern_version`
in the manifest.)

**Current behaviour, confirmed by reading the code, not assumed:**
ADR-015 asks the manifest to record "detector *and pattern* versions" as
two distinct values. No Rust type in the corpus (721-725) defines a field
literally named `pattern_version` -- there is no third, independent
"pattern" version. 726 reads 722/723's `parser_version` (e.g.
`cairn-hcl-parser/0.1.0` / `cairn-python-parser/0.1.0`, the parse
grammar that produced the AST the detector matched against) and records
that value under the `pattern_version` name ADR-015 uses. This is named
explicitly as a judgement call in `engine.py`'s own module docstring
(lines 27-41) and in `~/solara/lz2026/s726-handover.md` -- it was flagged
forward, not left silent, and is not a defect.

**Accepted, pending Allan's review.** The reasoning above is the most
honest non-invented reading available from the existing corpus; it is
not yet confirmed as Allan's actual intent.

**The exact one-line change, if Allan's intent differs:** if Allan wants
`pattern_version` sourced from something other than `parser_version` (a
genuinely distinct "pattern" version once one exists, or a different
existing field), the one line to change is `engine.py` line 261:

```python
pattern_version = raw_output["parser_version"]
```

replacing `raw_output["parser_version"]` with whatever expression reads
his intended source (and, if that source does not yet exist anywhere in
the corpus, authoring it is a separate, later unit's job -- not a change
this line alone can make up).

**Regression test locking today's behaviour:**
`packages/modules/tests/test_transformation_engine.py::
test_782_pattern_version_is_locked_to_parser_version` -- asserts a built
`ManifestEntry.pattern_version` equals the raw `parser_version` input
value. If a future unit changes `engine.py` line 261's mapping without
updating this test (or this document), this test fails.

## 2. 730's no-validation run sealing `outcome="PASS"`

**Where:** `packages/modules/src/cairn_modules/transformation/evidence.py`,
`_outcome`, lines 180-183:

```python
def _outcome(validation: ValidationRun | None) -> str:
    if validation is None:
        return "PASS"
    return "PASS" if validation.approved else "FAIL"
```

**Current behaviour, confirmed by reading the code, not assumed:** when
`build_transformation_evidence_package` is called with no `validation`
argument (729's validation run is optional -- "if available", per the
evidence module's own docstring, lines 213-227), the sealed
`EvidenceEnvelope.outcome` is `"PASS"`, the same value as an actual
passing validation run. There is no third, distinct `"UNVERIFIED"` (or
similarly-named) outcome anywhere in `cairn_kernel.evidence` or this
module -- a transformation run that was never validated at all is
currently indistinguishable, by `outcome` alone, from one that was
validated and passed. This is flagged as a judgement call in 730's own
handover; the spec (S16's R3-06 row) does not settle it.

**Accepted, pending Allan's review.** Treating "no validation attempted"
the same as "validation passed" is a real, named choice, not a settled
design decision.

**The exact one-line change, if Allan's intent differs:** if Allan wants
a run with no validation attached to seal as unverified rather than
passed, the one line to change is `evidence.py` line 182:

```python
        return "PASS"
```

replacing `"PASS"` with `"UNVERIFIED"` (or whichever literal he prefers)
on that line -- and, since nothing elsewhere currently expects that third
value, it may also require ADR-015/the evidence model to acknowledge the
new value's existence, which is otherwise outside the scope of this
one-line change.

**Regression test locking today's behaviour:**
`packages/modules/tests/test_transformation_evidence.py::
test_782_no_validation_run_seals_outcome_pass` -- builds an evidence
package with no `validation` argument and asserts the sealed envelope's
`outcome` is `"PASS"`. If a future unit changes `evidence.py` line 182's
sealing default without updating this test (or this document), this
test fails.

## What this unit does not do

- **Does not change either default.** Both remain exactly as 726 and 730
  shipped them. Deciding whether to change them is Allan's call, named
  explicitly above, not made here.
- **Does not add a new outcome value, field, or schema change.** No
  `"UNVERIFIED"` literal, no new `ManifestEntry`/`EvidenceOutput` field --
  only the two regression tests named above.
- **Does not touch any other unit's scope.** 726's and 730's modules are
  read and tested against; nothing else in either file, or in any other
  R4 unit's scope, is modified.
