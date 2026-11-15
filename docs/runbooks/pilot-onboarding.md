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

**Update (session s684, 2026-11-14): Finding 1 below is
resolved in code.** The console now drives a real, provider-agnostic
OIDC authorization-code-with-PKCE flow (`apps/console/src/oidc.ts`,
`apps/console/src/screens/signin.ts`/`callback.ts`) instead of asking
the operator to paste a token; tokens are verified by the same
existing kernel middleware this runbook already relied on. Proven
against a real local OIDC provider (login, token refresh, RBAC role
mapping, tenant isolation, rejection of a token from the wrong issuer)
in `apps/api/tests/test_oidc_dex_integration.py`. What is **not** yet
done is pointing a real deployment's `config.json` at an actual
identity provider -- that is a per-deployment configuration decision,
not a further code change, and is **still Allan's to make** (see
"Needs Allan" below). Step 1 and the prerequisites below are updated
to describe the new flow; this story's own real-browser proof (the
rest of this runbook) predates it and has not been re-run end to end
against a real IdP's own login page, since none is configured yet.

## Prerequisites

- The CAIRN API (`apps/api`) and console (`apps/console`) are
  deployed and reachable, and the console's `config.json` points at a
  real OIDC provider (issuer, client ID, redirect URI) that has
  granted the pilot's user an account and role -- see
  `apps/console/public/config.json.example`. No provider is configured
  for any deployment today; that's Allan's decision (see "Needs
  Allan").
- The pilot has one estate-inventory file ready (CSV, JSON, an
  RVTools export, an HVTools export, or a BOM), or read-only
  credentials for a GCP project they want assessed.
- The pilot has an account with the identity provider configured
  above (Finding 1 -- previously this step itself needed an engineer
  to hand-issue a token; it no longer does, once a provider is
  configured).

## Steps

1. **Sign in.** Open the console and click "Sign in". You're taken to
   your organisation's identity provider to authenticate, then
   returned to the console signed in.
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

1. **Sign-in has no real login flow -- RESOLVED (session
   s684, 2026-11-14).** A real, provider-agnostic OIDC
   authorization-code-with-PKCE flow now exists
   (`apps/console/src/oidc.ts`); the console redirects to the
   configured identity provider instead of asking for a pasted token.
   Proven against a real local OIDC provider in
   `apps/api/tests/test_oidc_dex_integration.py`. **Still needs
   Allan**: no real deployment's `config.json` names an actual
   identity provider yet -- that's a configuration decision (which
   IdP, whose accounts) separate from this code existing. See "Needs
   Allan" below.
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
5. **The evidence signer is explicitly a non-production key by
   default -- a real one now exists but isn't wired to any deployment
   (session s684, 2026-11-14).** `apps/api`'s default remains
   `_LocalEvidenceSigner` (`FAKE_HMAC_SHA256`, process-local, does not
   survive a restart) unless `CAIRN_KMS_*` env vars are set. A real
   Cloud KMS signing key (`cairn-dev-evidence-signing`, `europe-west2`,
   software protection) now exists in `your-dev-project-id`, and
   `cairn_adapters.evidence_kms` implements the signing/verification
   ports against it (no longer a docstring stub) -- proven in
   `tools/ops/kms_signing_proof.py` against the real key. **Still needs
   Allan**: whether and when any real deployment is actually
   configured to use it (no deployment is today -- this is a
   configuration decision, not further code).
6. **"0" everywhere in the report can read as a failure, not an
   honest result (presenter must explain).** "Controls evaluated: 0/7",
   "Cost baseline: ... Total: 0", "TCO: 0 ... (projected)" are all
   correct and expected for a run with no posture scanner output and
   no billing export supplied -- not a bug -- but read, unexplained,
   like something didn't work.
7. **Refreshing the browser mid-journey signs the pilot out and loses
   their place (off-script, presenter must explain).** Confirmed
   directly: a page refresh at any step returns to the sign-in screen,
   because the session lives only in an in-memory JS variable
   (`apps/console/src/state.ts`), not persisted storage. The
   underlying project and any completed run are untouched server-side
   (nothing is lost there), but the pilot has to sign in again (now
   via the real OIDC redirect -- Finding 1's fix changes *how* they
   re-authenticate, not *whether* a refresh forces it) and re-select
   the project and run. Not re-verified against this session's own
   change; the underlying cause (no persisted session) is unchanged.
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

1. **Sign-in / identity** (Finding 1) -- the OIDC mechanism is built
   (session s684); what's left is naming a real identity
   provider (issuer, client ID, redirect URI, and who gets an
   account/role with it) for an actual pilot deployment's
   `config.json`.
2. **Evidence signing key** (Finding 5) -- a real KMS-backed signer
   now exists and is proven (session s684); decide whether and when
   to point any real deployment's `CAIRN_KMS_*` config at it, or keep
   running pilots against the local non-production signer for now.
3. **Data-handling terms and SLO baseline -- approved for
   publication.** Allan approved `docs/pilot/data-handling-terms-
   draft.md` and `docs/pilot/slo-baseline-proposal.md` as drafted, on
   2026-11-14, to be published with the open-source project (session
   s684). This approves publishing the documents in their current
   drafted form -- it does not resolve the `[ALLAN: decide]` markers
   each document still carries; those remain open questions within
   the published text, not settled by this approval. See
   `docs/acceptance/r0-20-review.md` for the recorded approval.
