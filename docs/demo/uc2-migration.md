# Demo pack: use case 2 -- migration

A console walkthrough of CAIRN's R3 clean-room transformation pipeline:
`transform-run -> transform-diff -> transform-validate -> transform-review
-> transform-evidence`, driven against one golden fixture repository, the
same one `tests/golden/transform/test_golden_corpus.py` and the console's
own `tests/e2e/transform-journey.test.ts` already prove end to end.

## What's real and what's simulated -- state this on screen

- **Real, not simulated**: the transformation engine (real, compiled
  `cairn-transform-cli` -- real HCL parsing, real deprecation detection,
  real patch), the unified diff, static validation (real, compiled
  `cairn-transform-validator-cli`), the review/comment thread, and the
  signed evidence package.
- **Simulated / not live on Google Cloud, and no apply step exists at
  all today -- say this plainly**: "Scan and produce preview"
  (`transform-run.ts`'s own button label) is the entire "run" in this
  journey. There is no step anywhere in this console, or in CAIRN today,
  that applies a transformation to a live customer environment: R4's
  real-execution adapter (`cairn_adapters.provider_execution`) does not
  exist yet (README's own R4 status row, confirmed by this session's own
  grep: no `google.cloud`/`boto3`/`azure.` import anywhere in the
  adapters tree). So "run" here means **transform, diff, and validate a
  proposed change** -- never execute one. Say so explicitly if the
  audience asks whether anything was "applied": nothing was, nothing
  could be, from this console, today.
- **The "connected source" is a small, in-memory fixture, not a live
  Git clone**: `FakeRepositorySource` registers the fixture content in
  memory; no network call, no real `git clone`. The console's own Git
  repository field accepts a real `file://` URL too (see
  `tests/e2e/transform-journey.test.ts`, which drives a real local `git
  init` repo through a real `GitSourceAdapter`) -- either is honest to
  demo; this pack uses the simpler in-memory fixture path.

## Prerequisites

```
cargo build --release -p cairn-transform-cli -p cairn-transform-validator
docker compose up --build
```

Sign in with the local `dex` demo identity, same as the other two packs.

## Walkthrough

1. **Projects** -- create or reuse a project. Click **Review a
   transformation**.
2. **Trigger a transformation** -- Source: `Git repository`. Repository
   URL: a `file://` path to a small local checkout containing
   `tests/golden/transform/repos/terraform_acl_deprecated/main.tf`'s
   content (an `aws_s3_bucket` resource with a deprecated inline `acl`
   attribute). Ref: `main`. Click **Scan and produce preview**.
3. **Inspect the diff and manifest** -- one entry, `main.tf`, rule
   `tf-s3-bucket-inline-acl-deprecated`, outcome **Applied**. The
   rendered unified diff underneath shows the real two-edit patch: the
   deprecated `acl` attribute deleted, a replacement
   `aws_s3_bucket_acl` resource inserted.
4. **Run validation** -- click **Run validation**: one check,
   `static-reparse`, **passes** (the patched file re-parses cleanly).
   "Approved: yes", and the **Proceed** button becomes enabled -- say
   plainly that a failing check would visibly block this button, not
   just show a warning; this run's own check happens to pass.
5. **View the evidence record reference** -- Package, outcome `PASS`,
   "none -- first package for this project" for a first run on this
   project.
6. **Leave a review comment** -- post a `Request changes` comment (e.g.
   "please double-check the replacement resource name"), watch the
   thread show **Blocked**; then post an `Approve` comment, watch it
   switch to **Approved**. Both comments remain visible in the thread.

Stop here -- do not imply anything beyond this was executed.

## Plain-language read (demo-readiness gate step 4)

- **"Applied" as an outcome label** could read as "this was applied to
  your cloud" -- it is not; it means the *file edit* was applied to the
  in-memory proposed change. Say "the patch was applied to the proposed
  file, not to anything live" the first time this word appears on
  screen.
- **Rule ids** like `tf-s3-bucket-inline-acl-deprecated` are precise but
  jargon-dense -- say "this flags a deprecated setting on an S3 bucket
  and proposes the modern replacement Terraform's own AWS provider
  recommends," not the raw id. This particular fixture is a same-provider
  modernization (the AWS Terraform provider deprecated the inline `acl`
  attribute in favour of a separate resource) -- it is not a cross-cloud
  migration; say so if asked, since this pack's other two cross-cloud
  mapping rules (named in the golden corpus) aren't the one exercised
  here.
- **The unified diff text** is real but terse (raw Terraform HCL) --
  narrate it in English before reading it: "the old single-attribute ACL
  setting is replaced by its own resource block, which is the pattern
  Terraform's AWS provider itself now expects."
- No "coming soon" / placeholder labels appear in this flow.

## Off-script behaviour (not run live this session)

Same disclosure as the other two packs: built and verified from code
plus one real, captured pipeline run, in a CAIRN-only session with no
browser automation available. Not yet clicked through live.

- **Wrong click**: try clicking **Run validation** again after it has
  already passed -- `transform-validate.ts` re-runs the check each
  click; confirm the screen re-renders the same `PASS` result rather
  than erroring on a second call. Expected based on code, not yet
  confirmed live.
- **Back button**: navigate back from review to the diff screen and
  forward again -- the review thread's comments persist server-side
  (`add_review_comment` appends to the run's own thread), so returning to
  review should show the same comments, not a reset thread. Expected
  based on code.
- **Refresh mid-flow**: a hard refresh loses the in-memory
  `transformRunId` session state and returns to Projects, same pattern as
  the other two packs -- the presenter should re-select the project and
  re-trigger the transformation, not treat it as broken.

**Proof the pipeline is real, captured in this session (the real compiled
Rust binaries, not fakes, for both transformation and validation):**

```
uv run python docs/demo/uc2_verify_transform_pipeline.py
```

```
fixture: terraform_acl_deprecated (1 file(s))
manifest entries:
  main.tf: tf-s3-bucket-inline-acl-deprecated -> APPLIED (2 edit(s))
validation: approved=True
  main.tf:static-reparse: PASS
evidence package sealed: uc2-demo-pkg-1 (outcome=PASS)
offline verification: PASS
```

**This pack is not "ready for Allan's walkthrough" yet**, for the same
reason as the other two: no screenshots, video, or console-log capture
exist, because that needs a real headed browser run this CAIRN-only
session cannot perform. What's attached: a step-by-step runbook accurate
against the current console source, the cloud-free/no-apply-step-exists
disclosure above, and one real, captured run of the full
transform-validate-evidence pipeline through the compiled binaries.
Allan clicking through the live walkthrough himself is still the last
step.
