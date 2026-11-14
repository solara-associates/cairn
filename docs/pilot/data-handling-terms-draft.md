# Data-handling terms -- structured draft, not legal language

Status: R1-20. This is an engineering-drafted outline of what a pilot
customer's data-handling terms need to cover, with every fact that is
already true in code/Terraform stated as fact, and every legal or
commercial clause marked `[ALLAN: decide]`. **This is not finished
legal language and must not be shown to, or signed by, a pilot
customer as written.** It exists so Allan (or whoever drafts the real
terms) starts from an accurate technical baseline instead of guessing
what the product actually does.

## What CAIRN collects

- **Estate inventory**: whatever the pilot uploads (CSV/JSON/RVTools/
  HVTools/BOM export) or whatever a connected read-only GCP connection's
  inventory/billing/posture-scan APIs return (R1-02/R1-05/R1-09 --
  read-only scope only, ADR-010; no write or execute credential is ever
  requested or stored).
- **6R review decisions**: the reviewer's accept/amend/reject choice,
  rationale and the acting user's identifier (R1-14).
- **Assessment artifacts**: normalized estate records, workloads,
  posture findings, cost/TCO figures, the rendered report and the
  signed evidence package (R1-06..R1-17).
- **Audit trail**: every mutation above is recorded with actor,
  action, timestamp (ADR-008/R0-10).
- `[ALLAN: decide]` whether any of the above needs an explicit
  retention or deletion request path for a pilot customer beyond what
  `docs/runbooks/tenant-deletion.md`'s existing tenant-deletion
  procedure already provides.

## Where it's stored

- Fact (ADR-016, `docs/residency/uk-residency-matrix.md`): customer
  data, backups and the evidence-signing key are UK-only
  (`europe-west2`), with no copy outside the UK.
- Fact: a provider connection never carries an execution credential,
  only a read-only one (ADR-010); no write path into a customer's
  cloud environment exists before R4.
- `[ALLAN: decide]` whether the pilot terms need to name the specific
  subprocessors/infrastructure provider (GCP) by name, and whether any
  sub-processor list needs to be kept current and disclosed.

## Retention

- `[ALLAN: decide]` how long a pilot's estate/assessment data is kept
  after the pilot ends, and whether that differs from an active
  pilot's retention.
- Fact: `docs/runbooks/tenant-deletion.md` exists and is tested
  (`tests/integration/test_tenant_deletion_runbook.py`) -- it scrubs
  and tombstones `tenant`/`project` rows (their audit-table foreign
  keys require this) and deletes every other classified row. Whether
  this procedure is run automatically at pilot end, on request, or on
  a fixed schedule is `[ALLAN: decide]`.

## Who can access it

- Fact: `docs/residency/uk-residency-matrix.md`'s decision 3 -- support
  access is not restricted by location, but must be logged, approved
  and auditable. No support-access *feature* exists yet to grant that
  access through (flagged in that matrix as a future story, not
  invented here).
- `[ALLAN: decide]` which named roles (engineering, support, a named
  individual) may access a pilot's data, and under what approval
  process, until the audited support-access feature above is built.

## Pilot-specific terms

- `[ALLAN: decide]` whether the pilot is free, paid, or trial-with-
  conversion, and the commercial terms for each.
- `[ALLAN: decide]` what happens to the pilot's data and evidence
  packages if the pilot does not convert to a paying customer.
- `[ALLAN: decide]` liability/warranty language -- in particular, that
  the 6R classifier is an explicitly conservative default (see
  `packages/modules/src/cairn_modules/planning/classification.py`'s
  own docstring) and the posture/cost sections can be empty/zero when
  no scanner or billing export was supplied (see
  `docs/runbooks/pilot-onboarding.md`'s Finding 6) -- the terms should
  not imply a completeness the product does not yet claim for itself.

## What this draft is not

- Not reviewed by a lawyer, and not worded as a contract.
- Not published anywhere a pilot customer could see it -- it lives in
  this repo's `docs/` tree as an engineering reference only.
- Not a commitment on Allan's behalf to any of the `[ALLAN: decide]`
  items above.
