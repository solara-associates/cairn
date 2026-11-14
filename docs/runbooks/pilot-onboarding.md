# Pilot onboarding runbook

Status: R1-20 (spec acceptance: "Pilot can be run without engineering
intervention"). Covers the exact steps a pilot customer follows, end to
end, using only the R1-18 console and the APIs built in this wave --
no engineering intervention, per the acceptance criterion.

**This runbook was proven by actually following it once against the
real, running system** (the real `cairn_api` FastAPI app and the real
`apps/console` Vite dev build, in a real browser), per Allan's
demo-readiness rule that code that works is not a pass. Every step
below is what actually happened, not what was expected to happen. See
"Findings from the real run" below for what did not go cleanly.

**This runbook does not fully satisfy its own acceptance criterion
today.** Step 1 (sign-in) requires an access token nobody but an
engineer can currently produce -- see Finding 1. That gap is the single
largest blocker to a real "no engineering intervention" pilot and
needs Allan's decision (see "Needs Allan" at the end).

## Prerequisites

- The CAIRN API (`apps/api`) and console (`apps/console`) are
  deployed and reachable.
- The pilot has one estate-inventory file ready (CSV, JSON, an
  RVTools export, an HVTools export, or a BOM), or read-only
  credentials for a GCP project they want assessed.
- The pilot has an access token issued for CAIRN (see Finding 1 --
  today this step itself needs an engineer).

## Steps

1. **Sign in.** Open the console. Paste the access token into the
   "Access token" field and click Continue.
2. **Create a project.** On the Projects screen, type a project name
   (e.g. the customer or workload name) into "New project name" and
   click Create. The new project appears in the list below.
3. **Select the project.** Click "Select" next to the project just
   created.
4. **Connect a provider, or upload a file.** Either:
   - fill in Provider / Account id / Credential and click Connect
     (read-only scope only -- CAIRN never requests write or execute
     access, per ADR-010), or
   - choose a Format, paste the file's content into "File content"
     and click "Add file" (repeatable for more than one file).
   At least one of these is needed before starting the assessment;
   neither is required to have the other.
5. **Start the assessment.** Click "Start assessment". The console
   moves straight to the Assessment results screen once the run
   completes -- see Finding 3 below; the intermediate "running" status
   may not be visible at all for a small file.
6. **Review the 6R recommendations.** Each workload lists a proposed
   disposition (one of REHOST/REPLATFORM/REFACTOR/REPURCHASE/
   RETIRE/RETAIN), a plain-language rationale and a confidence score.
   For each workload, either:
   - click Accept to keep the recommendation as proposed, or
   - type a reason and click Reject, or
   - choose a different disposition, type a rationale and a
     confidence (0-1), and click Amend.
7. **View the report.** Click "View report" to see the full
   human-readable assessment report (coverage, posture, cost, TCO,
   versions).
8. **Export the signed evidence package.** Click "Export signed
   evidence package". The resulting package's payload hash, signing
   key and chain-to-previous-package status are shown, along with the
   final report text (now with the evidence hash filled in).

## Findings from the real run

Each of these either needs a presenter's spoken explanation today, or
needs Allan's decision before a real pilot can run this unaided.

1. **Sign-in has no real login flow (presenter must explain / needs
   Allan).** No identity-provider integration exists anywhere in this
   codebase -- the console asks the operator to paste an
   already-issued access token. A real pilot customer has no way to
   obtain one without an engineer handing it to them, directly
   contradicting this story's own acceptance criterion ("without
   engineering intervention"). This is the single biggest gap between
   what was proven today and a truly unassisted pilot. **Needs
   Allan**: either wire in a real OIDC provider before any pilot, or
   explicitly decide this story ships as "engineer provisions the
   first token, pilot does everything after that."
2. **The connect-a-provider fields can be silently autofilled by the
   browser's own saved-password manager (presenter must explain).**
   Observed directly during this run: Chrome's autofill populated the
   Account id and Credential fields with an unrelated saved
   credential the moment the page rendered, because the fields are
   unlabelled generic text/password inputs. Nothing was leaked (nothing
   submits until the pilot clicks Connect, and no third-party host is
   involved), but a pilot who doesn't look closely could connect with
   the wrong account by accident. One-line fix for a future session:
   `autocomplete="off"` (or a more specific `autocomplete` value) on
   those two fields.
3. **The run may complete before anyone sees it running (presenter
   must explain).** Against a two- or three-row CSV, R1-15's pipeline
   finishes well under a second; the console's own "Assessment run"
   screen (state/coverage/pending stages) can be navigated straight
   past before a human ever sees it rendered. Not a bug -- the console
   already polls and transitions correctly -- but a pilot watching a
   live demo may never see a "progress" moment for a small input,
   which is worth saying out loud rather than leaving unexplained.
4. **The report and evidence screens are full of engineering jargon
   (presenter must explain).** Raw UUIDs for tenant/project/run,
   control-catalogue codes like `gcp-cis-1.1` listed as "not
   evaluated", internal version strings like
   `r1-14-conservative-default-v1`, and a cryptographic signing-key id
   whose algorithm literally reads `FAKE_HMAC_SHA256` (Finding 5) all
   appear verbatim. None of this is wrong, but none of it reads as
   customer-facing copy either.
5. **The evidence signer is explicitly a non-production key, and says
   so in the algorithm name (needs Allan).** `FAKE_HMAC_SHA256`
   (`apps/api/src/cairn_api/app.py`'s `_LocalEvidenceSigner`) is a
   process-local key minted fresh on every API restart -- it does not
   survive a restart and is not a real signing key. A pilot's signed
   evidence package is real in structure (hash chain, tamper
   detection) but not yet backed by a durable, production key.
   **Needs Allan**: decide whether a pilot may run against this local
   signer, or whether a real KMS-backed signer (not yet built --
   `cairn_adapters.evidence_kms` is still a docstring stub) is required
   first.
6. **"0" everywhere in the report can read as a failure, not an
   honest result (presenter must explain).** "Controls evaluated: 0/7",
   "Cost baseline: ... Total: 0", "TCO: 0 ... (projected)" are all
   correct and expected for a run with no posture scanner output and
   no billing export supplied -- not a bug -- but read, unexplained,
   like something didn't work.
7. **Refreshing the browser mid-journey signs the pilot out and loses
   their place (off-script, presenter must explain).** Confirmed
   directly: a page refresh at any step returns to the sign-in screen
   with an empty token field. The underlying project and any
   completed run are untouched server-side (nothing is lost there),
   but the pilot has to paste their token again and re-select the
   project and run -- which also means Finding 1 (no real login) is
   now a recurring friction point, not just a one-time one.
8. **The browser's own Back button does nothing (off-script, not
   harmful).** Confirmed directly: the console's router never pushes
   browser history entries, so Back does not return to the previous
   screen -- it simply has no next page to go to and stays put. Not a
   crash, just not what a pilot used to normal web navigation would
   expect.
9. **A wrong click is recoverable.** Clicking "Add file" with an empty
   "File content" field, or submitting Reject/Amend without filling
   in the required text, shows an inline error message in place
   rather than losing any other state -- confirmed directly, no further
   action needed.

## Needs Allan

1. **Sign-in / identity** (Finding 1) -- decide the real pilot auth
   story before any external pilot runs this.
2. **Evidence signing key** (Finding 5) -- decide whether a pilot may
   run against the local non-production signer, or needs a real
   KMS-backed one first.
3. See `docs/pilot/data-handling-terms-draft.md` and
   `docs/pilot/slo-baseline-proposal.md` for the other two items this
   story asks for -- both stop at an explicit Allan decision point by
   design, per the brief.
