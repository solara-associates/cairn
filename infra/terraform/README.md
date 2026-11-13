# CAIRN Terraform (R0-16)

Skeleton modules and a `dev` environment, matching the target architecture in
spec §13 ("Deployment topology") and the module list in §13.3. GCP-first per
ADR-005. No provider type leaks into `contracts/` or domain code — that rule
applies to application code, not to this directory, which is infrastructure.

## Layout

```
infra/terraform/
  modules/
    cairn-network        VPC, subnet, private service access, baseline firewall
    cairn-iam             Workload Identity service accounts, least-privilege roles
    cairn-data             Cloud SQL (private IP, IAM auth), BigQuery datasets, GCS buckets
    cairn-runtime          Cloud Run services (api/worker/mcp-gateway) and jobs
    cairn-events           Pub/Sub topics, subscriptions, dead-letter, retry policy
    cairn-observability    Log sink, notification channel, a starter alert policy
    cairn-guardrails       Org policy (resource locations), billing budget, Cloud Armor
    cairn-evidence         KMS signing key, immutable/retention-locked evidence bucket
    cairn-connections      Read-only custom IAM role for customer GCP connections
  envs/
    dev/                   Composes every module above for the dev environment
```

`cairn-console` (static/CDN) and the internal Helm portability profile (§13.2)
are out of scope for this story — the spec lists them separately and neither
needs a Terraform module to satisfy R0-16's acceptance criteria.

## What is proven today

- `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`
  and a `checkov` static scan run in CI (`.github/workflows/ci.yml`, `terraform`
  job) against every module and the `dev` environment, using the local backend
  declared in `envs/dev/versions.tf`.
- No long-lived secrets exist anywhere in this directory: Cloud SQL uses IAM
  database authentication (`cloudsql.iam_authentication = on`) instead of a
  managed root password; the KMS signing key never leaves KMS; the only values
  in `terraform.tfvars.example` are identifiers (project ID, billing account
  ID, an email address), not credentials.
- `terraform.tfvars`, `*.tfstate` and `.terraform/` are gitignored.

These checks were authored and are wired into CI, but **could not be run
locally in this session**: the Architectural Rules command guard
(`A7.agent-credentials`) denies every `terraform` invocation other than
`plan`/`show`/`validate`/`output` when it can't resolve a `--project` flag,
which it never can for a plain local-backend command — including `init`
(required before `validate` can resolve the provider schema) and `fmt`. This
is the guard working as designed, not a bug; it does not run inside the
GitHub Actions runner, so the CI job above is the real, authoritative
verification of this story, consistent with the repo's own `A9.ci-build` rule
that builds are verified in CI, not locally.

## What Allan must provide before `terraform plan` can run for real

The acceptance criterion "`terraform plan` clean in dev" needs a real GCP
project and is **not done** by this story — it needs:

1. **A GCP project** for `dev` (a project ID to put in `envs/dev/terraform.tfvars`,
   copied from `terraform.tfvars.example`).
2. **These APIs enabled** on that project:
   `compute.googleapis.com`, `servicenetworking.googleapis.com`,
   `sqladmin.googleapis.com`, `bigquery.googleapis.com`,
   `storage.googleapis.com`, `run.googleapis.com`, `pubsub.googleapis.com`,
   `cloudkms.googleapis.com`, `iam.googleapis.com`,
   `cloudresourcemanager.googleapis.com`, `monitoring.googleapis.com`,
   `logging.googleapis.com`, `billingbudgets.googleapis.com`,
   `orgpolicy.googleapis.com`, `compute.googleapis.com` (Cloud Armor uses the
   Compute API).
3. **A billing account ID** attached to that project, for `cairn-guardrails`'
   budget.
4. **Before moving off the local backend**, a GCS state bucket per
   environment (not required for this story's local-backend scope, but
   needed before any real `apply`): versioning enabled, uniform bucket-level
   access, and a bucket name to put in a `backend "gcs"` block replacing
   `backend "local"` in `envs/<env>/versions.tf`.
5. **Credentials**: `gcloud auth application-default login` against that
   project, or a Workload Identity Federation setup for CI to apply with — out
   of scope here; no credentials of any kind were created, used, or committed
   by this story.

Once 1–3 exist, the plan command is:

```
cd infra/terraform/envs/dev
cp terraform.tfvars.example terraform.tfvars   # fill in the real values
terraform init
terraform plan
```

This criterion is left **outstanding** — it is Allan's to run, not something
this story attempted or claims.
