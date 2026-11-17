# Roadmap: rest of R4, R5, and open-source readiness

Dated 2026-11-17. Written against `origin/main` @ `f4deb52` (R0-R3 complete; R4
cloud-free units 780-784, 787, 790, 792, 793 merged, PRs #80-#89; halted before
unit 785 per `cairn-r4-progress.md`'s halt report and `s735-handover.md`). New
units in this document are numbered **810 upward**; existing R4 units (785-794)
keep the numbers already assigned in `cairn-r4-briefs.md`/`cairn-r4-progress.md`
and are restated here, not renumbered. Every unit is marked **cloud-free** or
**cloud-blocked**.

## 0. A discrepancy this roadmap surfaces, not resolves

`ADR-018-open-source.md` (accepted 2026-11-09) states the source is already
public at `github.com/solara-associates/cairn` under Apache-2.0, and the
technical spec's §16.2 describes R0 itself as having shipped on "a public
open-source repository." A live check during this planning session confirms
the GitHub repository's actual visibility is **public today** (`gh repo view
solara-associates/cairn` reports `PUBLIC`), and its history already contains
superseded content naming a reference engagement ("[prior reference engagement]") in commits before
PR #56 removed it from `HEAD` — visible to anyone who runs `git log -p`
against the public history today, not just the current tree.

This conflicts with this task's own framing ("CAIRN is open-sourced only after
R5, with a one-time history rewrite first"). This roadmap does not resolve the
conflict — it is an Allan decision, not a planning judgement call, and no
session should force-push a history rewrite or change repository visibility
without his explicit instruction. It is listed as **decision D0** in §4 and
flagged again in §5's risk list, because every day it stands, the repo's
existing public history is exactly as exposed as it will be the day the OSS
plan in §4 formally begins.

## 1. Remaining R4 units (785 onward), restated

Unchanged from `cairn-r4-briefs.md` §3 and `cairn-r4-progress.md`'s halt
report — reproduced here so this one document carries the full remaining R4
picture alongside R5 and OSS. Every acceptance item referenced is
`docs/r4-acceptance.md`'s numbering.

| Unit | Story | Goal | Depends on | Friday setup step that unblocks it | Acceptance items that apply | Cloud? |
|---|---|---|---|---|---|---|
| 785 | R4-02b | First real read proof against `solara-cairn-dev-exec` | 784 (merged) | Steps 1-5, 7 (project exists, `cairn-exec-reader` SA + bindings, keyless federation) | 1, 2, 3, 8, 9 | **Cloud-blocked** |
| 786 | R4-02c | First real write + rollback proof (pilot bucket label toggle) | 785 | Steps 6, 7, 9, 10 (`cairn-exec-writer` SA + custom role, KMS cross-project binding, pilot bucket) + Allan's plan approval | 1, 2, 3, 4, 6, 7, 8, 9, 11 | **Cloud-blocked** |
| 788 | R4-03b | Real `terraform plan`/drift proof | 785, 787 | Reuses 785's SA (no new IAM); step 8 (`iac_allowances` entry for the new `dev-exec` Terraform directory) | 1, 2, 3, 5, 7, 8, 9 | **Cloud-blocked** |
| 789 | R4-03c | Real `terraform apply` + reconciliation proof | 786, 788 | Reuses 786's SA + step 8's `iac_allowances` entry + a fresh plan approval | 1, 2, 3, 4, 5, 7, 8, 9, 10, 11 | **Cloud-blocked** |
| 791 | R4-04b | Real rollback proof via the recovery engine (not 786's simpler adapter-level rollback) | 789, 790 (merged) | Reuses 786's SA + a fresh approval | 1, 2, 3, 7, 8, 9, 11 | **Cloud-blocked** |
| 794 | R4-06b | Real distributed-boundary + irreversible-rollback-attempt proof | 785, 786, 793 (merged) | Reuses both existing SAs | 1, 2, 3, 6, 7, 8, 9, 12 | **Cloud-blocked** |

**No unit in this table can start before Allan's Friday 20 Nov setup.** All ten
setup commands from `cairn-r4-briefs.md` §2.6 are restated below, verbatim,
with the renumbered unit references `cairn-r4-progress.md`'s halt report
already carries — unchanged from that halt report, not re-derived:

> 1. **Decide: new project `solara-cairn-dev-exec`, or extend
>    `solara-cairn-dev`.** This is still open — not assumed by this run. If
>    new:
>    ```
>    gcloud projects create solara-cairn-dev-exec --folder=<folder-id> --name="CAIRN dev exec"
>    gcloud billing projects link solara-cairn-dev-exec --billing-account=<billing-account-id>
>    ```
> 2. Budget alert, mirroring the existing $50/month alert on
>    `solara-cairn-dev`:
>    ```
>    gcloud billing budgets create --billing-account=<billing-account-id> --display-name="cairn-dev-exec" --budget-amount=50 --project=solara-cairn-dev-exec
>    ```
> 3. Enable the APIs the adapter and Terraform orchestration need:
>    ```
>    gcloud services enable compute.googleapis.com storage.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com cloudkms.googleapis.com --project=solara-cairn-dev-exec
>    ```
> 4. Add `solara-cairn-dev-exec` to `~/.config/architectural-rules/
>    projects.yaml`'s `non_production` list (edit the file directly, same as
>    for `solara-cairn-dev`) — without this, every cloud write the guard sees
>    against the new project is denied by default, by design.
> 5. Reader service account (needed for **785**):
>    ```
>    gcloud iam service-accounts create cairn-exec-reader --project=solara-cairn-dev-exec --display-name="CAIRN execution adapter - read"
>    gcloud projects add-iam-policy-binding solara-cairn-dev-exec --member="serviceAccount:cairn-exec-reader@solara-cairn-dev-exec.iam.gserviceaccount.com" --role="roles/compute.viewer"
>    gcloud projects add-iam-policy-binding solara-cairn-dev-exec --member="serviceAccount:cairn-exec-reader@solara-cairn-dev-exec.iam.gserviceaccount.com" --role="roles/storage.viewer"
>    ```
> 6. Writer service account and its custom, narrow role (needed for **786**;
>    permissions below are a placeholder for step 10's pilot resource — 786's
>    own brief restates this exact command once the pilot resource type is
>    confirmed):
>    ```
>    gcloud iam service-accounts create cairn-exec-writer --project=solara-cairn-dev-exec --display-name="CAIRN execution adapter - write"
>    gcloud iam roles create cairnExecWriterPilot --project=solara-cairn-dev-exec --title="CAIRN exec writer pilot" --permissions=storage.buckets.update,storage.buckets.get
>    gcloud projects add-iam-policy-binding solara-cairn-dev-exec --member="serviceAccount:cairn-exec-writer@solara-cairn-dev-exec.iam.gserviceaccount.com" --role="projects/solara-cairn-dev-exec/roles/cairnExecWriterPilot"
>    ```
> 7. Keyless federation for both service accounts (needed for both **785** and
>    **786**; no SA key file is ever created):
>    ```
>    gcloud iam workload-identity-pools create cairn-exec-pool --project=solara-cairn-dev-exec --location=global
>    gcloud iam workload-identity-pools providers create-oidc cairn-exec-provider --project=solara-cairn-dev-exec --location=global --workload-identity-pool=cairn-exec-pool --issuer-uri=<CAIRN's own token issuer, per apps/console's existing OIDC work from s684> --attribute-mapping="google.subject=assertion.sub"
>    gcloud iam service-accounts add-iam-policy-binding cairn-exec-writer@solara-cairn-dev-exec.iam.gserviceaccount.com --project=solara-cairn-dev-exec --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/cairn-exec-pool/*"
>    gcloud iam service-accounts add-iam-policy-binding cairn-exec-reader@solara-cairn-dev-exec.iam.gserviceaccount.com --project=solara-cairn-dev-exec --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/cairn-exec-pool/*"
>    ```
> 8. Terraform allowance for whatever new directory **788/789**'s units
>    create (e.g. `infra/terraform/envs/dev-exec`) — add it to
>    `projects.yaml`'s `iac_allowances` the same way `dev-foundation` was
>    added (edit the file; not a `gcloud` command).
> 9. Cross-project KMS binding so the execution service can seal evidence
>    without Allan signing every record by hand (needed before **786**):
>    ```
>    gcloud kms keys add-iam-policy-binding cairn-dev-evidence-signing --project=solara-cairn-dev --location=europe-west2 --keyring=cairn-dev-evidence --role=roles/cloudkms.signerVerifier --member="serviceAccount:cairn-exec-writer@solara-cairn-dev-exec.iam.gserviceaccount.com"
>    ```
> 10. Create exactly one real pilot target (needed for **786**'s first real
>     write):
>     ```
>     gcloud storage buckets create gs://solara-cairn-dev-exec-pilot --project=solara-cairn-dev-exec --location=europe-west2 --uniform-bucket-level-access
>     ```

Steps 1-5 and 7 (the reader half) unblock 785 alone. All ten steps, plus
Allan's own approval of 786's specific revision, are needed before 786 can
run. 788 reuses 785's creds plus step 8. 789/791 reuse 786's creds plus a
fresh approval each. 794 reuses both existing SAs.

## 2. R5 scope, as numbered units (810 upward)

Source: `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` §16 R5-01..R5-06 (FinOps,
LLMOps, MLOps, MCP/A2A, resilience/sovereignty, vertical packs), `docs/adr/
ADR-011-mcp-a2a.md` (MCP per bounded context, internal until R5), `docs/adr/
ADR-016-launch-jurisdiction.md` (residency), and this task's explicit asks: the
ninth adversarial failure-mode test, an end-to-end demonstration reusing the
727 golden corpus, and documented (not implemented) VAID/SYNTHERA boundaries.

These units are roadmap-level, sized the same way `cairn-r4-briefs.md`'s own
780-794 were before a dedicated briefs session (that plan's own `s734`
equivalent) turned them into run-sheet detail. **Unit 810 is that dedicated
session for R5** — it produces `cairn-r5-briefs.md` with the same level of
unit-by-unit detail R4 got, before 811 onward actually builds anything. This
mirrors how R4 itself was planned before being run.

| Unit | Story | Goal | Depends on | Cloud? |
|---|---|---|---|---|
| 810 | R5 planning | Write `cairn-r5-briefs.md`: run-sheet detail for 811-829 below, same shape as `cairn-r4-briefs.md` | R4 complete through unit 794 (cloud-blocked — see §5) | Cloud-free |
| 811 | R4-06 completion | **The missing ninth adversarial failure-mode test** — irreversible rollback attempt against the real project. This is unit **794**, restated here because it is the one item this roadmap must not let fall through the cracks between R4's own table and R5's: R5 should not start build work assuming R4-06 is complete when 8 of 9 modes are fake-adapter-only. | 785, 786, 793 | **Cloud-blocked** (it is unit 794) |
| 812 | R5-01a | FinOps policy engine: alert/throttle/cap/stop/disable tiers, keyed to 783's risk-tier model, built and tested against a fake billing/cost adapter | R1-12 (merged), 783 (merged) | Cloud-free |
| 813 | R5-01b | FinOps Class C remediation adapter (cap/stop/disable) behind the kernel gate, reusing 784's `ProviderExecutionPort` contract and 790's recovery engine, fake-adapter only | 812, 784, 790 | Cloud-free |
| 814 | R5-02a | LLMOps gateway: security + reliability pillars (request/response policy, rate/circuit controls), reusing R0-12's OTel+RED+per-call-cost observability | R0-12 (merged) | Cloud-free |
| 815 | R5-02b | LLMOps gateway: cost + observability pillars, control-loop decision/act cycle closed against a fake model-provider adapter (ADR-014's `ModelPort`) | 814, ADR-014 | Cloud-free |
| 816 | R5-03a | MLOps registry + drift detection module | R0-13 (merged) | Cloud-free |
| 817 | R5-03b | MLOps self-healing with explicit bounds (no unbounded autonomous retraining — bounds are a policy object, tested with a deliberate-break exceeding them) | 816 | Cloud-free |
| 818 | R5-04a | MCP gateway: registry, OAuth, per-bounded-context server scaffolding (ADR-011) | R0-13 (merged) | Cloud-free |
| 819 | R5-04b | A2A bridge + bridge conformance tests | 818 | Cloud-free |
| 820 | R5-05a | Resilience module: failover rules, keyed to the canonical estate model (R2-01) | R2-01 (merged) | Cloud-free |
| 821 | R5-05b | Sovereignty module: residency sweeps against ADR-016's UK-only pack, evidence of every sweep | 820, `docs/residency/uk-residency-matrix.md` | Cloud-free (sweeps run against the fake/inventory adapter until a real one exists; a real sweep is itself cloud-blocked and deferred past this roadmap) |
| 822 | R5-06a | Vertical accelerator pack conformance harness (every pack must satisfy the kernel/contract suite, per spec acceptance text) | R0-02 (merged) | Cloud-free |
| 823 | R5-06b | First vertical pack built against 822's harness, as the harness's own proof | 822 | Cloud-free |
| 824 | R5 e2e demo | End-to-end demonstration on a synthetic cloud estate, reusing unit 727's golden corpus (`tests/golden/transform/`) extended with R5's operate loops: ingest the synthetic estate, run FinOps/LLMOps/MLOps/resilience loops against it end to end, produce one signed evidence package covering the whole run | 812-823 | Cloud-free — "synthetic" by construction; this is the demonstration the R5 exit criterion needs before any real-cloud R5 proof is even proposed |
| 825 | R5 integration boundaries | Document the optional VAID and SYNTHERA integration boundaries: where a port/contract could admit either as an MCP client or A2A peer (818/819's gateway is the natural boundary point), with an explicit import-linter test proving **no actual dependency on either exists** in the codebase today | 818, 819 | Cloud-free |

**R5 is entirely cloud-free except unit 811 (which is R4's own unit 794,
cross-listed here only so it isn't forgotten).** Nothing in 810, 812-825 needs
`solara-cairn-dev-exec`, a real credential, or Allan's plan approval — every
one builds and tests against a fake/deterministic adapter, the same pattern
R0-R4's cloud-free units already used successfully.

## 3. Open-source readiness plan (after R5)

Sequenced strictly after R5 completes (810-825), per this task's framing.
§0 already flags that the *premise* behind this sequencing (that the repo
isn't public yet) does not match the live repository state — this plan is
written as asked, with that conflict carried forward as decision D0, not
silently resolved by assuming either answer.

| Unit | Step | What it does | Allan's decision needed | Cloud? |
|---|---|---|---|---|
| 826 | OSS decision record | Write `docs/specs/oss-launch-decisions.md` capturing D0-D4 below as a decision record, not a resolution — each decision stays open until Allan answers it here | **D0**: is the repository's current public visibility and existing history intentional (matches ADR-018/spec §16.2) or does it need to be made private now, before anything else in this plan proceeds? | Cloud-free (docs only) |
| 827 | History rewrite spec | Document exactly what a history rewrite would remove (every "[prior reference engagement]" mention across all commits, not just `HEAD`; any other reference-engagement or internal-codename text the clean-room register doesn't already disclose; any path or filename naming an internal-only system) and how it would be verified (full-history `git log -p \| grep`, not a `HEAD`-only check; confirm the old blobs are unreachable after a `git filter-repo`-style rewrite, not merely hidden; a fresh clone's byte size and commit count sanity-checked against expectation) | **D1**: proceed with the rewrite at all, given D0's answer may make it moot or urgent; **D2**: exact scope of what gets removed, since over-removal can destroy legitimate audit history (`docs/specs/reference-register.md`'s own "none read" disclosures are evidence, not something to scrub) | Cloud-free (spec only — the actual rewrite is **not** executed by this unit or any unattended session; it is a destructive, unrebasable operation on public history and needs Allan's explicit go-ahead and participation, consistent with this estate's no-force-push rule) |
| 828 | README/SECURITY/status refresh | Bring `README.md`, `SECURITY.md`, and the roadmap/status tables current for a public-launch announcement (distinct from the routine "bring current" updates R2/R3/R4 already did mid-run — this pass is specifically for an external, first-time audience) | **D3**: confirm the public-launch announcement date/venue, since the docs should say "launched" only once it has | Cloud-free |
| 829 | Contributor onboarding | Review and refresh `CONTRIBUTING.md`, `GOVERNANCE.md`, `CODE_OF_CONDUCT.md`; label a small set of real "good first issue" items from the backlog | None beyond confirming the backlog items chosen are genuinely safe for an external contributor (no cloud-adjacent or security-sensitive work) | Cloud-free |
| 830 | Release process | Define versioning scheme, changelog format, and a release checklist (what gates must be green, who tags, how the tag is signed) | **D4**: who besides Allan, if anyone, ever gets tag/release authority — currently a solo-maintainer question with no delegate | Cloud-free |
| 831 | Licence check | Audit every direct and transitive dependency's licence for Apache-2.0 compatibility; confirm `NOTICE` and `docs/third-party-licenses.md` are accurate and complete | None — a factual audit, flagged to Allan only if an incompatible licence is actually found | Cloud-free |

Every unit in this section is cloud-free and buildable unattended **except the
rewrite itself** (827 only specifies and verifies the method; executing it is
explicitly out of scope for any unattended session, same as "history rewrite,
publishing" being named as Allan-only in this task's own rules).

## 4. Allan's decisions, collected in one place

- **D0** (§0, §3 unit 826): is the repository's current public state and
  history intentional, or does something need to change before this plan's
  own premise (open-source only after R5) can be true again?
- **D1/D2** (§3 unit 827): whether and exactly what to rewrite out of history.
- **D3** (§3 unit 828): the actual public-launch date/venue the refreshed docs
  should name.
- **D4** (§3 unit 830): release/tag authority beyond Allan alone.
- Carried forward, unchanged, from `cairn-r4-briefs.md`: §2.1's project choice
  (`solara-cairn-dev-exec` vs. extending `solara-cairn-dev`), every IAM
  binding in §1's restated setup commands, and 786/789/791's plan approvals.

## 5. Risk to the UAB launch (10 Dec) — UAB has priority

Today is 2026-11-17. Allan's Friday 20 Nov setup unblocks 785 onward; UAB
launches 2026-12-10 — 20 days later, with UAB holding first claim on both
Allan's time and this estate's usage limits per this task's own instruction.

- **810 (R5 briefs) and 826-831 (OSS plan) are explicitly not time-critical**
  and should not run concurrently with UAB launch-prep work in the days
  immediately before 10 Dec — they are docs/planning-and-fake-adapter work
  with no customer-facing deadline of their own, unlike UAB.
- **785-794 and 811 (the real-cloud R4 proofs) depend on Allan's hands-on
  setup time (§1's ten commands) and his plan-approval attention (786, 789,
  791, 794).** Scheduling that setup and those approvals inside the UAB
  crunch window risks exactly the contention this task's instructions warn
  against. Recommend Allan's Friday 20 Nov session covers §1's setup only,
  with 786/789/791/794's plan approvals scheduled for whichever days between
  20 Nov and UAB's own go-live are least contended — not assumed to be
  immediately after Friday's setup.
- **No unit in this roadmap, cloud-free or cloud-blocked, touches any UAB
  service, project, or credential.** Confirmed by scope: every project named
  anywhere in this document is `solara-cairn-dev` or `solara-cairn-dev-exec`;
  neither appears in `~/.config/architectural-rules/projects.yaml`'s existing
  UAB-related entries (`synthera-uab-staging`).
- The main residual risk is **usage-limit contention from running R5's
  cloud-free build (810, 812-825) and the OSS-prep docs (826-831) unattended
  at volume** in the same window UAB needs headroom. This roadmap recommends
  running R5/OSS work in modest batches with explicit pauses around UAB's own
  critical days, rather than one uninterrupted unattended run through all of
  810-831 — a decision for whoever supervises the run, not fixed here.
