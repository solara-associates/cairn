# Data-handling terms -- structured draft, not legal language

This is an engineering-drafted outline of what a pilot or customer's
data-handling terms need to cover, with every fact that is already true
in code/Terraform stated as fact, and every legal or commercial clause
marked `[ADOPTER TO DECIDE]`. **This is not finished legal language and
must not be shown to, or signed by, a customer as written.** It exists
so whoever operates a CAIRN deployment -- and drafts the real terms for
their own customers -- starts from an accurate technical baseline
instead of guessing what the product actually does.

## What CAIRN collects

- **Estate inventory**: whatever the customer uploads (CSV/JSON/RVTools/
  HVTools/BOM export) or whatever a connected read-only GCP connection's
  inventory/billing/posture-scan APIs return (read-only scope only,
  ADR-010; no write or execute credential is ever requested or stored).
- **6R review decisions**: the reviewer's accept/amend/reject choice,
  rationale and the acting user's identifier.
- **Assessment artifacts**: normalized estate records, workloads,
  posture findings, cost/TCO figures, the rendered report and the
  signed evidence package.
- **Audit trail**: every mutation above is recorded with actor,
  action, timestamp (ADR-008).
- `[ADOPTER TO DECIDE]` whether any of the above needs an explicit
  retention or deletion request path beyond what
  `docs/runbooks/tenant-deletion.md`'s existing tenant-deletion
  procedure already provides.

## Where it's stored

- Fact (ADR-016, `docs/residency/uk-residency-matrix.md`): in this
  project's own reference deployment, customer data, backups and the
  evidence-signing key are UK-only (`europe-west2`), with no copy
  outside the UK. A different deployment's residency depends on where
  its operator deploys it.
- Fact: a provider connection never carries an execution credential,
  only a read-only one (ADR-010); no write path into a customer's
  cloud environment exists before R4.
- `[ADOPTER TO DECIDE]` whether your terms need to name the specific
  subprocessors/infrastructure provider by name, and whether any
  sub-processor list needs to be kept current and disclosed.

## Retention

- `[ADOPTER TO DECIDE]` how long a customer's estate/assessment data is
  kept after an engagement ends, and whether that differs from an
  active engagement's retention.
- Fact: `docs/runbooks/tenant-deletion.md` exists and is tested
  (`tests/integration/test_tenant_deletion_runbook.py`) -- it scrubs
  and tombstones `tenant`/`project` rows (their audit-table foreign
  keys require this) and deletes every other classified row.
  `[ADOPTER TO DECIDE]` whether this procedure runs automatically at
  engagement end, on request, or on a fixed schedule.

## Who can access it

- Fact: `docs/residency/uk-residency-matrix.md`'s decision 3 -- in this
  project's own reference deployment, support access is not restricted
  by location, but must be logged, approved and auditable. No
  support-access *feature* exists yet to grant that access through
  (flagged in that matrix as a future story, not invented here).
- `[ADOPTER TO DECIDE]` which named roles (engineering, support, a named
  individual) may access a customer's data, and under what approval
  process, until an audited support-access feature is built.

## Engagement-specific terms

- `[ADOPTER TO DECIDE]` whether an engagement is free, paid, or
  trial-with-conversion, and the commercial terms for each.
- `[ADOPTER TO DECIDE]` what happens to a customer's data and evidence
  packages if the engagement does not convert or renew.
- `[ADOPTER TO DECIDE]` liability/warranty language -- in particular,
  that the 6R classifier is an explicitly conservative default (see
  `packages/modules/src/cairn_modules/planning/classification.py`'s
  own docstring) and the posture/cost sections can be empty/zero when
  no scanner or billing export was supplied (see
  `docs/runbooks/pilot-onboarding.md`'s Finding 6) -- the terms should
  not imply a completeness the product does not yet claim for itself.

## What this draft is not

- Not reviewed by a lawyer, and not worded as a contract.
- Not terms for anyone to show a customer as written -- it is an
  engineering reference for drafting real terms.
- Not a commitment on any adopter's behalf to any of the
  `[ADOPTER TO DECIDE]` items above.
