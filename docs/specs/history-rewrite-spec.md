# History rewrite: what it removes and how it is verified

Unit 827, per `docs/roadmap-r4-r5-oss.md` §3. This document specifies the
rewrite and its verification method. **It does not execute the rewrite.**
Executing it is a destructive, unrebasable operation on a public repository's
history — explicitly reserved for Allan, with his direct participation, same
as `s698-handover.md` already concluded when it first catalogued this exact
need: "This is a decision for Allan, not something this session executed."

This document largely consolidates, rather than repeats, two prior sessions'
already-complete work (`s698-handover.md`, `s699-handover.md`, both
2026-11-15, both Allan-authorized) — their blob-hash inventory is the
authoritative record of what a rewrite removes. See `docs/specs/
oss-launch-decisions.md`'s D0 for why this matters now: the repository has
been public since 2026-11-15, so this is a retroactive cleanup of already-
exposed history, not a pre-launch gate.

## What gets removed

Two categories, both already fully catalogued by exact blob hash in
`s698-handover.md` §7 and its addendum:

1. **Client/employer codenames** in the design-evidence catalogue
   (`CLOUD-ARCHITECTURE-PATTERNS.md`, `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md`,
   `docs/specs/reference-register.md`, and `Cloud_Modernization_Platform_PRD.docx`):
   `gcp-cost-posture-foundation`, `uk-landing-zone-accelerator`, `consent-ledger-compliance-poc`
   (and the bare `uk-landing-zone-accelerator`/`consent-ledger-compliance-poc` aliases used as codename shorthand, not the
   `DPDP` regulation references, which stay — see s698 §3's determination).
2. **"[prior reference engagement]"** (a real company name, a reference-engagement employer),
   confined to `CLOUD-ARCHITECTURE-PATTERNS.md` across 7 unique blob
   versions.

Both categories are already fixed in the current tree (PRs #54, #55, #56,
merged 2026-11-15). What remains is **only** the pre-fix blobs still
reachable through history — every commit from `682f093` (2026-11-09, the
file's own introduction) through `c69bf28`/`f5aec00` (2026-11-15, the fix
merges).

**Exact blob hashes to target** (reproduced from `s698-handover.md` §7 and
its addendum — read that file for the full per-commit table; not
duplicated here beyond this summary to avoid two documents silently
drifting out of sync):

- 4 commits × up to 5 files each for the codename set (`682f093`, `db3ec2f`,
  `590b739`, `67b3f8d`).
- 7 unique blob versions of `CLOUD-ARCHITECTURE-PATTERNS.md` for "[prior reference engagement]"
  (`682f093` through `584161642e23bbe7841fb216e9db4f894ef86f75`).
- Both sets span the same commit range and the same handful of files —
  **one `git filter-repo --replace-text` pass, one combined rules file,
  covers both.** No separate tooling or second pass is needed.

**What this spec adds beyond s698's own inventory**: a scope boundary s698
did not need to state, because it predates unit 825/this run's own naming
discipline. **This rewrite must NOT touch**:
- `docs/specs/reference-register.md`'s clean-room disclosures (including
  unit 727's own "none read" entry) — these are evidence *for* the
  clean-room claim (ADR-017), not something to scrub. The codename rename
  already applied to this file by s698 (renaming the project, not removing
  the disclosure) is the correct pattern; a rewrite must preserve the
  disclosure's existence and content, touching only the removed
  codenames' literal text, never the surrounding evidentiary sentence.
- Any commit's authorship, timestamps, or the overall commit graph shape
  beyond what rewriting the flagged blobs necessarily changes (every
  commit from `682f093` forward gets a new hash as an unavoidable
  consequence of rewriting an ancestor — s698 §7 already states this
  plainly — but nothing should be deliberately reordered, squashed, or
  dropped beyond the targeted text replacement).

## How it would be executed (specification, not an instruction to run)

Exactly as `s698-handover.md` §7 already specifies:

1. `git filter-repo` (not `filter-branch`), against a **fresh mirror
   clone**, never the working checkout.
2. A `--replace-text` rules file mapping each old string to a safe
   replacement for the markdown files; a blob-callback (extract zip, edit
   `word/document.xml`, repack, verify `unzip -t`) for the PRD docx, exactly
   as s698's own fix commits already did in the current tree — the rewrite
   applies the identical transformation retroactively.
3. Force-push every affected branch on the remote — explicitly the one
   case this estate's standing "no force-push" rule is written to allow,
   because it is a deliberate, scheduled, Allan-authorized operation, not
   a casual one.

## How it is verified — the method any session running this must follow

**A `HEAD`-only check is not sufficient and must not be treated as proof.**
The two fix commits already made `git grep` over the current tree return
zero matches; that was true before this spec existed and proves nothing
about history. Verification must cover full history:

1. **Full-history text sweep**, not grep over `HEAD`:
   ```
   git log --all -i --grep="[prior reference engagement]\|gcp-cost-posture-foundation\|uk-landing-zone-accelerator\|consent-ledger-compliance" --oneline
   git log --all -p | grep -i "[prior reference engagement]\|gcp-cost-posture-foundation\|uk-landing-zone-accelerator\|consent-ledger-compliance"
   ```
   Both must return nothing — not "nothing after the fix commit," nothing
   at all, from any commit, on any branch.
2. **Confirm the old blobs are unreachable**, not merely hidden. After a
   `filter-repo` pass, run `git cat-file -e <old-blob-hash>` for every
   hash in s698's inventory, against the rewritten mirror. Each must fail
   ("object does not exist") — a blob that still resolves via `cat-file`
   even if no ref points at it is not actually gone until a `git gc
   --prune=now --aggressive` has run and the reflog has expired; verify
   after that step, not before it.
3. **Fresh-clone sanity check**: clone the rewritten remote fresh (not
   `pull`/`fetch` into an old clone — `s698`'s own warning that old clones
   diverge irreconcilably applies to verification too, not just to
   collaborators). Confirm commit count and tree content are sane (every
   file present, no accidental truncation) and that the fresh clone's
   history sweep (step 1) is clean.
4. **Confirm `docs/specs/reference-register.md`'s disclosures survived
   intact** — diff the rewritten history's final version of that file
   against the pre-rewrite `HEAD` version; the only acceptable diff is
   the literal codename text the rewrite targeted, nothing in the
   surrounding evidentiary prose.
5. **Re-run the full CI suite** against the rewritten `main` — a rewrite
   that silently corrupted a file (a bad regex match, a docx repack
   failure) should fail exactly the same gates every other change does;
   do not special-case this as "just a history operation, no need to
   re-test."

## Timing and sequencing

Per `docs/roadmap-r4-r5-oss.md`, this is sequenced after R5. Per D0's
finding (`docs/specs/oss-launch-decisions.md`), the repository has been
public since 2026-11-15 — this sequencing no longer determines *whether*
the content has been exposed (it already has), only *when* a cleanup
happens. Allan's decision on D1/D2 (proceed, and exact scope) is the actual
gate; this document is ready to be executed against whenever he says go,
not blocked on R5 completing first for any technical reason — the "after
R5" sequencing in the roadmap was a planning convenience, not a dependency
this spec itself requires.

## What this unit did not do

No `git filter-repo` command was run. No mirror clone was created. No
force-push was issued. No branch was rewritten. This document is a
specification and a verification checklist only, consistent with every
other cloud-gated or Allan-gated unit in this run stopping at the
documentation boundary.
