# Open-source launch decisions (D0-D4)

Unit 826, per `docs/roadmap-r4-r5-oss.md` §3/§4. This document records
decisions Allan needs to make before the open-source readiness plan
(units 827-831) proceeds. It captures the decisions as open questions with
their context — it does not resolve any of them. No decision below is
assumed; each stays unresolved until Allan answers it here or in a
follow-up ADR.

## D0 — Does the repository's current public state match intent?

**Resolved 2026-11-20, by Allan.** The "[prior reference engagement]"
string this decision hinged on is a placeholder only — it is not, and
never was, a real organisation name. It appears identically, brackets
included, in every commit back to its introduction (`dc08fc8`) and was
never a disclosure of an actual client or employer. Verified in CAIRN
runner session s841: `git log --all --follow -p -- CLOUD-ARCHITECTURE-PATTERNS.md`
shows the literal bracketed text at every occurrence, with no earlier,
less-redacted form anywhere in history.

**Decision: no history rewrite needed.** Since no real organisation is
named anywhere in the public history, the premise for D1/D2 (removing a
real reference-engagement name from history) does not apply. Allan has
also dropped the conditional codename-hygiene unit (genericising the
internal-codename boundary doc named in §4's codename sweep) that was held
pending this decision.

**The conflict (original framing, kept for context).** This task's own framing states "CAIRN is open-sourced
only after R5, with a one-time history rewrite first." But two things
already on `main` say otherwise:

- `docs/adr/ADR-018-open-source.md` (accepted 2026-11-09): "The source is
  public at `github.com/solara-associates/cairn` under the Apache License
  2.0," with no R5 gate mentioned.
- `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` §16.2 describes R0 itself as
  having shipped on "a public open-source repository."
- A live check during the R4/R5 planning session (803) confirmed the
  repository's actual GitHub visibility is **public today**
  (`gh repo view solara-associates/cairn` reports `PUBLIC`), and its commit
  history already contains a reference-engagement name ("[prior reference engagement]") in
  commits before PR #56 removed it from `HEAD` — visible today to anyone
  who runs `git log -p` against the public history, not just the current
  tree.

**The question for Allan.** Is the repository's current public visibility
and existing history intentional (matching ADR-018 and the spec), or does
something need to change — making the repository private again, for
instance — before the "open-source only after R5" framing can be true?

**Why this matters before 827 proceeds.** If the repository has been
public all along, a "one-time history rewrite before open-sourcing" has
already missed its window — the content a rewrite would remove has been
visible since whenever the repository was first made public. If that is
the case, 827's rewrite becomes a cleanup of an already-exposed history
rather than a pre-launch step, and Allan may want to treat the exposure
itself as a separate matter (credential/secret rotation check, disclosure
assessment) independent of whether a rewrite happens at all.

**Finding, added during unit 826 (session 803)**: this was not an accident.
Git history shows a deliberate, authorized publication effort on
2026-11-15: commit `692eacd` ("Prepare repository for open-source
publication") added the community/governance scaffolding (`CODE_OF_CONDUCT.md`,
`GOVERNANCE.md`, `NOTICE`, issue/PR templates, `docs/third-party-licenses.md`),
rewrote `README.md` for an outside reader, and removed internal-only
references found during a publication audit — followed, the same day, by
two explicitly Allan-authorized sessions (`s698-handover.md`, `s699-handover.md`,
both headed "Authorisation: Allan, this session") that searched the
tracked tree for client/employer codenames and the reference-engagement
name "[prior reference engagement]," fixed what they found in the current tree, and reported
history could not be cleaned the same way without a disruptive rewrite —
explicitly deferring that rewrite decision to Allan rather than making it
themselves. s698's own handover already states plainly: "best done once,
right before making the repo public" — language that only makes sense if
going public was imminent or recent at the time of writing, not years off.

**Revised reading**: D0 is very likely already answered — the repository's
public state matches a real decision Allan authorized on 2026-11-15, not
an oversight. What is NOT yet resolved is whether the history rewrite
those two sessions flagged (and explicitly left to Allan) has since
happened. §"Git history" below shows it has not — the pre-fix blobs both
sessions catalogued are still reachable today. This task's framing
("open-sourced only after R5, with a one-time history rewrite first")
appears to predate or be unaware of the 2026-11-15 publication — not
necessarily wrong about Allan's eventual intent for a rewrite, but wrong
about the repository still being private today.

**Still not decided here**: whether Allan wants the repository reverted to
private pending a rewrite, given the rewrite never happened and the
content it would remove has been exposed since 2026-11-15; or whether he
considers that window already closed (a rewrite only prevents a *new*
clone from seeing the content, not retroactively un-exposes it) and wants
to proceed differently. See D1/D2 below, now answerable with the exact
blob inventory s698/s699 already produced.

## D1 — Proceed with the history rewrite at all?

**Resolved 2026-11-20, by Allan, as a consequence of D0: no.** D0 found
the content a rewrite would have removed is a placeholder, not a real
organisation name, so there is nothing left for 827's specified rewrite to
remove. 827 remains unexecuted and is not scheduled.

## D2 — Exact scope of what a rewrite removes

**Moot as of D1's resolution (2026-11-20): D1 is no, so there is no
rewrite to scope.** Kept below for the record only.

If D1 is yes, exactly what gets removed. Candidates per 827's own spec:

- Every "[prior reference engagement]" mention across all commits (not just `HEAD`, where PR #56
  already removed it from the current tree).
- Any other reference-engagement or internal-codename text not already
  disclosed in `docs/specs/reference-register.md`.
- Any path or filename naming an internal-only system.

**The risk this decision has to weigh**: over-removal can destroy
legitimate audit history. `docs/specs/reference-register.md`'s own "none
read" disclosures (e.g. unit 727's entry, which states plainly that four
reference repositories were available but none was opened) are evidence
*for* the clean-room claim, not something to scrub — a rewrite that removes
commit history mentioning reference repositories indiscriminately could
accidentally destroy the paper trail ADR-017's clean-room policy depends
on. Allan's decision should name which categories of historical mention
are removed and which are preserved as evidence.

**Not decided here.**

## D3 — Public-launch date and venue

828's README/SECURITY/status refresh is written "for a public-launch
announcement" — a different pass from the routine "bring current" updates
R2/R3/R4 already did mid-run. That refresh should state the launch has
happened only once it actually has.

**The question for Allan**: what is the actual public-launch date and
venue the refreshed docs should name? (Given D0's finding that the
repository is already technically public, this may need reframing as "the
date Allan wants to treat as the public announcement," distinct from "the
date the repository became visible.")

**Not decided here.**

## D4 — Release/tag authority beyond Allan alone

830's release process needs to state who, if anyone besides Allan, ever
gets tag/release authority. Today this is a solo-maintainer question with
no delegate — `GOVERNANCE.md` and `CONTRIBUTING.md` do not currently name
a release process at all.

**The question for Allan**: is release/tag authority Allan-only
indefinitely, or does he want to name a delegate or a process for adding
one later?

**Not decided here.**

## Carried forward from `docs/roadmap-r4-r5-oss.md` §4, unchanged

- §2.1's project choice (`<gcp-project-id>-exec` vs. extending
  `<gcp-project-id>`) for R4's cloud-gated units.
- Every IAM binding in that document's §1 restated setup commands.
- Plan approvals for units 786, 789, 791, 794.

None of the above is resolved by this document; it is R4's own open
decision set, listed here only so every outstanding Allan decision across
R4/R5/OSS lives in one place once this document and the roadmap are read
together.
