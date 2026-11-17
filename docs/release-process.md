# Release process

Unit 830 of `docs/roadmap-r4-r5-oss.md` §3. There is no tagged release yet
(`git tag -l` returns nothing as of this writing) and no CHANGELOG file —
this document defines the process for the first one and every one after,
consistent with `GOVERNANCE.md`'s current single-maintainer model.

## Versioning scheme

Semantic versioning (`MAJOR.MINOR.PATCH`), applied at the repository level,
not per-package. `packages/*/pyproject.toml` each carry their own
`version = "0.1.0"` today (independent of any repo-level tag) — this
document does not change that; a repo-level release tag and each package's
own version are tracked separately until there is a reason to couple them
(e.g. publishing packages individually to a registry, which CAIRN does not
do today).

- **MAJOR**: a breaking change to a contract described in
  `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` §7-13, or a change requiring an
  existing deployment's data to migrate incompatibly.
- **MINOR**: a new release's worth of functionality (an R-number milestone
  completing, e.g. "R4 complete" or "R5 complete"), backward compatible.
- **PATCH**: a fix with no contract or behavior change beyond correcting a
  defect.

Pre-1.0: CAIRN has shipped no `1.0.0` yet. Tags before that point use
`0.MINOR.PATCH` and may carry breaking changes between minors — normal
for pre-1.0 semver, and consistent with `ADR-018`'s "no open-core gate at
launch" framing not yet implying API/contract stability promises.

## Changelog

Add `CHANGELOG.md` at the repository root, [Keep a Changelog](https://keepachangelog.com/)
format, one entry per tagged release summarizing what shipped in
plain-English terms (not a commit-log dump — the existing `cairn-r*-progress.md`
files already serve as the detailed per-unit record; the changelog is the
reader-facing summary). This document does not create that file — it
specifies that the next tagged release should include it, so the file's
first entry has real content to anchor to rather than being backfilled
empty.

## Release checklist

Before any tag:

1. **Gates green on `main`**, not on a branch — the same CI suite every PR
   already runs (`python`, `rust`, `console`, `terraform` × N, `secrets-scan`,
   `python-deps-scan`, `sbom-sign`, `image-scan` × N per `.github/workflows/ci.yml`).
   A release never ships on top of a known-red `main`.
2. **Conformance clean against the current pending set** — `python -m
   cairn_kernel.conformance` (or `make conformance`) run against `main`,
   confirming the mandatory/pending split in `tools/conformance/rules.yaml`
   matches what the release notes claim (e.g. do not claim "R5 complete"
   if `R-AI-01`/`R-AI-02` were still pending — they are not, as of unit
   814, but a future release's checklist must re-verify this each time,
   not assume it from a past release).
3. **`docs/third-party-licenses.md` current** — see unit 831's own check
   below; re-run before every release, not just once.
4. **README/status tables current** — the roadmap table in `README.md`
   must state the real release boundary truthfully (same discipline as
   every mid-run "bring current" pass this project has already done:
   PR #89 for R2-R4, unit 828 for the current public state).
5. **CHANGELOG.md entry written** for this release, following the format
   above.
6. **Allan tags and signs** (see "Who tags" below) — `git tag -s vX.Y.Z -m
   "..."` (signed, not a bare lightweight tag) and `git push origin
   vX.Y.Z`.
7. **GitHub release created** from the tag, with the changelog entry as
   the release body.

Nothing in this checklist is itself automated by this unit — it is the
process a human (Allan, per "who tags" below) follows, same as every
other Allan-gated step in this estate.

## Who tags — release authority

Per `docs/specs/oss-launch-decisions.md`'s **D4**, this is still an open
decision. Today, by default and absent any other instruction: **Allan
only**. `GOVERNANCE.md`'s single-maintainer model already states the
maintainer "reviews and merges all pull requests, triages issues, and
owns ADR acceptance" — tag/release authority is the same shape of
decision and follows the same person until D4 says otherwise. If Allan
later wants to delegate release authority (e.g. to a second maintainer
once the contributor base grows, per `GOVERNANCE.md`'s own "how this
changes" section), that is a `GOVERNANCE.md` update plus this document's
own revision, not a unilateral change by whoever is delegated.

## Signing

Tags are signed (`git tag -s`), consistent with the clean-room/evidence
discipline this project already applies everywhere else (ADR-008's
signed evidence envelopes, ADR-017's clean-room provenance). A release
tag is itself a claim about what shipped — it gets the same signing
discipline as every other claim this project makes about itself.
