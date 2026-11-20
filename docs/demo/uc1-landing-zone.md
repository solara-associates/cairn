# Demo pack: use case 1 -- landing zone deployment

A console walkthrough of CAIRN's R2 design pipeline against the
`landing-zone` pattern (`patterns/landing-zone.yaml`), stopping at the
signed plan review -- no `terraform apply`, no live GCP project.

## What's real and what's simulated -- state this on screen

- **Real, not simulated**: pattern parameterization, target-model
  generation against the published mapping release, the Terraform plan
  *preview* text (real `TerraformHclGenerator`, not a canned string), the
  approval console's exact-revision view (content hash, mutation class,
  recovery plan, evidence-to-be-captured).
- **Simulated / not live on Google Cloud**: nothing in this walkthrough
  runs `terraform apply`, calls a GCP API, or uses a cloud credential --
  by design (ADR-010: no Class C effect against a customer environment
  before R4). The plan preview is real, structured, deterministic text a
  human reads; it is not the output of a real `terraform plan` run
  against a live project. Say this explicitly: "the plan is real and
  signed; applying it against a live project needs a customer's own GCP
  access, which we deliberately haven't asked for yet" (R841 §2's own
  phrasing for this exact use case).
- **The demo estate is synthetic, and reuses two AWS-shaped resources,
  not use case 3's RVTools/HVTools estate** -- found and disclosed while
  building this pack: `mappings/service-map.yaml` (the published mapping
  release) only covers cloud-to-cloud service equivalences (AWS/Azure ->
  GCP). It does not yet cover an on-prem RVTools/HVTools-derived
  resource at all -- driving the landing-zone pattern against use case
  3's own fixture estate produces **100% `GAP`** (correctly reported, not
  a bug, but not a usable landing-zone demo). This pack instead uses two
  small, explicitly-named synthetic AWS resources (an S3 bucket, a
  DynamoDB table) that do resolve, so the audience sees real Terraform
  resource blocks. Say so if asked why this demo's estate differs from
  use case 3's -- it is a real gap in today's mapping catalogue, not a
  concealed one.

## Prerequisites

```
docker compose up --build
```

Sign in with the local `dex` demo identity, same as use case 3.

## Walkthrough

1. **Projects** -- create or reuse a project. Click **Design target
   architecture**.
2. **Choose a pattern** -- select "Sovereign landing zone"
   (`patterns/landing-zone.yaml`'s description: "network, IAM, data,
   runtime and observability modules... a region allowlist and a
   residency sweep that raises on an empty result").
3. **Parameterize** -- fill in the pattern's four required parameters:
   - `allowed_regions`: `europe-west2` (comma-separated field; this is
     the region allowlist the residency sweep enforces -- an empty value
     here is a validation error by design, see `landing-zone.yaml`'s
     `landing-zone-regions-non-empty` rule).
   - `environments`: `dev, prod`.
   - `residency_sweep_on_apply`: checked (true). Say plainly: the
     pattern requires this to be true in any published release; it can
     only be left off in a draft used for local iteration.
   - `network_topology`: `hub_spoke`.
   - Generate. (The journey supports **regenerate** too -- change a
     parameter and regenerate to show the design isn't a one-shot
     artefact; `tests/e2e/design-journey.test.ts` already proves this
     round-trip for real.)
4. **Infrastructure-as-code preview** -- shows the disclaimer text, one
   row per resolved resource ("Planned" / "Gap -- no resource planned"),
   and the full rendered Terraform preview underneath. With the demo
   estate above, both resources show **Planned** (approximate mapping,
   caveat shown). Click **Propose for approval**.
5. **Approval and execution console** -- this is the "signed plan
   review" step:
   - Propose the plan: mutation class `Reversible external mutation`,
     and fill in a recovery plan (strategy `Rollback`, a plan reference,
     preconditions, authority and evidence fields) -- or say plainly that
     leaving every recovery field blank proposes with no recovery plan
     recorded, which the console will not let you approve from here until
     one exists (see the screen's own text: "this mutation cannot be
     approved from this console until one is").
   - The console then shows the **exact revision**: revision id, content
     hash, mutation class, risk tier (e.g. "Tier 1 -- reversible, one
     approver"), and the recovery plan verbatim -- the same content a
     real approver would review before signing off, per R4-05's own
     acceptance text quoted in the screen's source: "Nothing is approved
     from a summary -- the approver sees what will actually run."
   - Post a decision: Comment, Request changes, or Approve. Show the
     approval thread updating live.

Stop here. Do not click anything that would execute -- there is nothing
in this console that does (R4's real execution adapter does not exist
yet), but say so plainly rather than leaving it to the audience's
assumption.

## Plain-language read (demo-readiness gate step 4)

- **Raw UUIDs everywhere** (design id, revision id, resource ids) read as
  noise to a non-engineer. Point at them as "CAIRN's internal reference
  for this exact version," don't read them aloud.
- **"Content hash"** and **"mutation class"** are jargon -- say "a
  fingerprint that proves nobody edited this plan after it was reviewed"
  and "how risky this kind of change is," respectively.
- **Risk tier labels** (`Tier 1 -- reversible, one approver`, etc.) are
  already written in plain language on screen -- good, no fix needed,
  just read them as written.
- **"APPROXIMATE equivalence"** in the rendered Terraform preview is
  accurate but needs a one-line gloss: "this is the closest match, not an
  identical feature-for-feature swap" -- the caveat text under each
  resource already explains why, read it rather than skip past it.
- No "coming soon" / placeholder labels appear in this flow.

## Off-script behaviour (not run live this session)

As with the use-case-3 pack: built and verified from code plus one real,
captured pipeline run in a CAIRN-only session with no browser automation
available. Not yet clicked through in an actual browser this session.
Before presenting:

- **Wrong click**: try proposing a plan with only some recovery-plan
  fields filled in -- `plan-approval.ts` validates this client-side
  ("A recovery plan needs every field filled in, or none at all.");
  confirm the message reads clearly.
- **Back button**: navigate back from the approval console to the IaC
  preview and forward again -- the approval view is fetched fresh, not
  cached, per the screen's `renderPlanApproval`; expected based on code,
  not yet confirmed live.
- **Refresh mid-flow**: a hard refresh loses the in-memory `designId`/
  `planRevisionId` session state and returns to Projects, same as use
  case 3 -- expected, not a bug; the presenter should know to re-select
  the project and pattern.

**Proof the plan preview is real, captured in this session:**

```
uv run python docs/demo/uc1_verify_iac_plan.py
```

```
pattern: landing-zone (Sovereign landing zone)
target model resources:
  res-1: RESOLVED
  res-2: RESOLVED

--- rendered Terraform plan preview (PLAN ONLY -- not applied) ---
# CAIRN IaC plan preview -- PLAN ONLY. Not executed. Not applied. No Terraform binary was invoked and no cloud credential was used to produce this text; nothing here changes any customer environment.
# design_id = uc1-design-1
# pattern_id = landing-zone
# pattern_catalogue_version = 2026.11.1
# mapping_release_version = 2026.11.2
# target_provider = gcp
# gap_count = 0

# source: aws:s3 (resource_id=res-1)
# NOTE: APPROXIMATE equivalence -- not a like-for-like match.
# detail: Consistency, lifecycle transition and access-control semantics differ
resource "cloud-storage" "res-1" {
  # target_provider = "gcp"
  # cairn_resource_id = "res-1"
}

# source: aws:dynamodb (resource_id=res-2)
# NOTE: APPROXIMATE equivalence -- not a like-for-like match.
# detail: Access patterns and secondary indexes require redesign; Bigtable has no native secondary-index equivalent to DynamoDB GSIs/LSIs
resource "bigtable" "res-2" {
  # target_provider = "gcp"
  # cairn_resource_id = "res-2"
}
```

(`design_id`/`revision_id` will differ on every run -- a fresh UUID each
time, same caveat as use case 3's evidence hash.)

**This pack is not "ready for Allan's walkthrough" yet**, for the same
reason as the use-case-3 pack: no screenshots, video, or console-log
capture exist, because that needs a real headed browser run this
CAIRN-only session cannot perform. What's attached: a step-by-step
runbook accurate against the current console source, the
cloud-free/simulated disclosures above (including the mapping-catalogue
gap found while building it), and one real, captured run of the IaC
plan-generation pipeline. Allan clicking through the live walkthrough
himself is still the last step.
