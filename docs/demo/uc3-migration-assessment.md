# Demo pack: use case 3 -- migration assessment

A ~10-minute walkthrough of CAIRN's assessment pipeline (R1), using the
console against the same golden fixtures the automated test suite already
proves the pipeline against (`tests/e2e/test_r5_synthetic_estate_demo.py`,
`packages/modules/tests/test_evidence_service.py`).

## What's real and what's simulated -- state this on screen

- **Real, not simulated**: file ingestion and normalization, posture
  assessment against the control catalogue, cost/TCO calculation, 6R
  disposition proposals, the signed evidence package and its offline
  verification. All of it runs the actual `cairn_modules` pipeline, not a
  mock.
- **Simulated / not live on Google Cloud**: there is no live connection to
  a customer's GCP project anywhere in this walkthrough. The estate comes
  from uploaded CSV exports (the "Connect a provider" form on the Connect
  screen exists in the UI, but `cairn_adapters.provider_gcp` behind it is
  an explicit fake -- see README and `docs/specs/r5-integration-boundaries.md`
  for why -- so skip that form in the demo and go straight to file upload).
  The billing figures behind the cost baseline are a seeded demo fixture,
  not a real customer's bill.
- **Evidence signing**: the quick-start `docker compose up` stack signs
  evidence with `_LocalEvidenceSigner` (`apps/api/src/cairn_api/app.py`) --
  a random key generated in-process at startup, never exported by any
  route, gone on restart. It is **not** the real GCP KMS-backed signer
  (`cairn_adapters.evidence_kms`), which only activates when `CAIRN_KMS_*`
  env vars are set -- out of scope for this cloud-free demo. Say this
  plainly if asked "is that signature real": the signing mechanism and
  code path are real and production-shaped; the specific key used in this
  demo is ephemeral and local, by design, because no cloud KMS key is
  configured. See "Verifying the evidence package" below for what this
  means for the offline-verification step.

## Prerequisites

```
docker compose up --build
```

Open `http://localhost:3000`, sign in with the bundled local `dex` demo
identity (no password prompt -- see `docs/identity.md`). This is a
development convenience, not how a real deployment authenticates; say so
if asked.

## Walkthrough

1. **Projects** -- create a new project (e.g. "Migration Assessment Demo").
   Click **Assess (connect/ingest)** on the new project's row.
2. **Connect a provider, or upload an estate file** -- skip "Connect a
   provider" (fake-adapter only, see above). Under "Upload a file":
   - Format: `rvtools`, paste the contents of
     `tests/fixtures/ingestion/golden.rvtools.csv` (two VMware VMs:
     `web-01` powered on, `db-01` powered off, both on `ClusterA`).
   - Click **Add file**, then repeat with Format `hvtools` and
     `tests/fixtures/ingestion/golden.hvtools.csv` (two Hyper-V VMs:
     `app-01` running, `app-02` off).
   - Start the run from this screen once both files are queued.
3. **Assessment results** -- shows Posture ("evaluated"), Cost baseline and
   TCO (seeded demo figures, in minor currency units -- see the
   plain-language note below), and one row per derived workload with a
   proposed 6R disposition (REHOST/REPLATFORM/etc.), a confidence score,
   and a rationale. Click **Accept** on at least one decision to show the
   review step working, not just display.
4. **View report** -- the rendered assessment report text.
5. **Export signed evidence package** -- click through from the report.
   The evidence screen shows the package id, payload hash, signer key id
   and algorithm, and the chain link ("none -- first package for this
   project" for a first run). This is the live, real `build_evidence_package`
   call the API makes -- not a canned screen.

## Plain-language read (demo-readiness gate step 4)

Read each screen as a non-engineer would before presenting it:

- **"minor currency units"** on the results screen (e.g. cost baseline
  shown as an integer like `250000 GBP minor units`) reads as jargon and
  as a confusingly large number. Say plainly: "that's pence, so GBP2,500" --
  or fix the display before presenting (not done in this pack; flagged
  here as a presenter-must-explain item, since changing money formatting
  is out of this unit's cloud-free, narrowly-scoped change).
- **Internal lab hostnames** in the fixture data (`esxi-01.corp.local`,
  `hv-01.corp.local`) are placeholder lab names baked into the golden test
  fixture, not a real customer's infrastructure -- say so if asked, don't
  let it read as a real environment being shown.
- **Disposition confidence as a bare decimal** (e.g. `0.8`) -- say "80%
  confidence" out loud rather than reading the raw number.
- No "coming soon" / "not yet" labels appear anywhere in this flow --
  everything shown is live, working functionality.
- The evidence screen's payload hash and signer key id are long opaque
  strings -- don't read them aloud character by character; just point at
  them as "this is the tamper-evident signature, verified below."

## Verifying the evidence package, offline

The console's evidence screen shows the package summary, but it does not
give you a button to independently re-verify the signature in a second,
separate process -- and as noted above, the quick-start stack's signing
key is process-local and was never designed to be exported. To show the
actual verification mechanism working, for real, run:

```
uv run python docs/demo/uc3_verify_evidence_offline.py
```

This drives the exact same `cairn_modules.assessment` pipeline (not a
stub) against the same two golden fixtures used in the walkthrough above,
seals a real evidence package with `cairn_kernel.evidence`, and verifies
it with a **second, independent verifier object that never touches the
signer** -- the actual offline-verification contract
`packages/modules/tests/test_evidence_service.py` already proves. Captured
output from a real run in this session:

```
assessment run completed: 3 workload(s) derived
evidence package sealed: uc3-demo-pkg-1
  payload hash:  ef67248cacfd1fac4d387c7c78ae7e226722eff78f8bc135978071fa9b4459ee
  signed with:   fake-evidence-key-1 (FAKE_HMAC_SHA256)
  previous hash: none -- first package for this project
offline verification: PASS
  report excerpt: '# Assessment report -- run uc3-demo-run-1'
```

(The payload hash will differ on every run you make -- 6R disposition
decisions get a fresh random id each run, so the signed payload is never
byte-identical twice. `offline verification: PASS` is the part that
should always reproduce.)

Say plainly to the audience: this proves the verification *logic* for
real, using the same code every evidence package in CAIRN goes through.
It uses a demo-scoped key pair (`FakeEvidenceSigner`/`FakeEvidenceVerifier`),
not the quick-start API's own ephemeral local key or a production GCP KMS
key -- cross-process verification of a package the running API actually
signed needs the real KMS-backed signer, which is cloud-blocked (R4,
units 785+) and not part of this cloud-free demo.

## Off-script behaviour (not run live this session)

This pack was built and verified from code and a real pipeline run in a
CAIRN-only session with **no browser automation available** -- the
walkthrough above has not been clicked through in an actual browser by
this session. Before presenting, Allan (or another presenter) should
click through it once live and additionally try the three likely
detours, per the demo-readiness gate:

- **Wrong click**: from the results screen, click **Reject** on a
  decision instead of Accept, and confirm the required-reason validation
  (`showError` fires if the reason field is empty) reads clearly rather
  than as a raw error.
- **Back button**: browser-back from the evidence screen to results,
  forward again -- confirm the evidence screen re-fetches rather than
  showing a stale or blank state (it calls `buildEvidencePackage` fresh on
  every render, per `evidence.ts`, so a second evidence package with a new
  `payload_hash` and a populated `previous_hash` is the expected, correct
  behaviour, not a bug -- say this if asked why the hash changed).
  Expected based on code, not yet confirmed live.
- **Refresh mid-flow**: a hard refresh on the results or evidence screen
  loses in-memory router/session state (`state.ts` is not persisted across
  a reload) and returns to Projects. Expected based on code; the
  presenter should know to re-select the project and continue from
  Connect, not treat it as broken.

**This pack is not "ready for Allan's walkthrough" yet in the sense of the
demo-readiness gate** -- no screenshots, video, or console-log capture
exist yet, because that gate requires a real headed browser run, which
this CAIRN-only automated session cannot perform (no browser automation
permitted). What is attached here is: a step-by-step runbook accurate
against the current console source, the cloud-free/simulated disclosures
above, and one real, captured, passing run of the offline evidence
verification. Allan clicking through the live walkthrough himself, with
screenshots/video/console capture per the gate, is still the last step.
