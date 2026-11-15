# CAIRN dev cloud foundation (minimal)

The minimal set of resources needed before anything else in `dev` can be
applied: a Terraform state bucket, a KMS key ring and an evidence-signing
key, in a maintainer-chosen GCP project (`<your-dev-project-id>` below).
Not the full `dev` environment (`infra/terraform/envs/dev`) -- no network,
IAM service accounts, Cloud SQL, Cloud Run, events, observability or
guardrails. That remains a separate, larger acceptance criterion (see
"R0-16 terraform plan" note in `infra/terraform/README.md`).

## What this creates, and how

Two resources, in whichever project `var.project_id` names (`europe-west2`
to match the UK-only residency decision in
`docs/residency/uk-residency-matrix.md`):

- `gs://<your-dev-project-id>-tfstate` -- versioned, uniform bucket-level
  access, public access prevention enforced.
- KMS key ring `cairn-dev-evidence` with asymmetric signing key
  `cairn-dev-evidence-signing` (`EC_SIGN_P256_SHA256`, software
  protection level).

They can be created directly with `gcloud` first and imported into
Terraform afterwards (useful when a maintainer's own tooling restricts
`terraform init`/`apply` against a real backend from an unattended
session):

```
gcloud storage buckets create gs://<your-dev-project-id>-tfstate \
  --project=<your-dev-project-id> --location=europe-west2 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://<your-dev-project-id>-tfstate --versioning --project=<your-dev-project-id>

gcloud kms keyrings create cairn-dev-evidence --project=<your-dev-project-id> --location=europe-west2
gcloud kms keys create cairn-dev-evidence-signing \
  --project=<your-dev-project-id> --location=europe-west2 --keyring=cairn-dev-evidence \
  --purpose=asymmetric-signing --default-algorithm=ec-sign-p256-sha256 --protection-level=software
```

The IAM binding granting `roles/cloudkms.signerVerifier` on the signing
key (needed before anything can produce a real KMS signature) is
deliberately not declared in Terraform here -- grant it by hand, scoped to
one named principal, once you know which workload or operator needs it;
see `infra/terraform/modules/cairn-iam` for how a real workload's service
account gets this binding once that module is applied.

## Bringing gcloud-created resources under Terraform management

If you created the bucket and key with `gcloud` as above, import rather
than re-create:

```
cd infra/terraform/envs/dev-foundation
cp terraform.tfvars.example terraform.tfvars   # set project_id
terraform init
terraform import google_storage_bucket.terraform_state <your-dev-project-id>-tfstate
terraform import google_kms_key_ring.evidence projects/<your-dev-project-id>/locations/europe-west2/keyRings/cairn-dev-evidence
terraform import google_kms_crypto_key.evidence_signing projects/<your-dev-project-id>/locations/europe-west2/keyRings/cairn-dev-evidence/cryptoKeys/cairn-dev-evidence-signing
terraform plan   # should show no changes
```

Once `infra/terraform/envs/dev` (the full environment) is ever applied
for real, its `module.evidence` (`cairn-evidence`) will try to create a
key ring/key with these exact same names for the `dev` environment --
import these same resources into that module's state instead
(`terraform import module.evidence.google_kms_key_ring.evidence ...`),
not a fresh `apply`.

## Cost

Both resources together cost well under $1/month at dev/pilot-test
volumes: the state bucket holds a small file (negligible storage
cost); the key is software protection level (~$0.06/month per active
key version, plus a small per-signing-operation cost). Set a billing
budget alert on the project before creating either resource.

## Identity Platform / customer identity: not a fit for UK-only residency

Before using Google Identity Platform for sign-in, check where it stores
user account data, per the UK-only residency decisions in
`docs/residency/uk-residency-matrix.md`.
**Finding: Identity Platform does not offer a UK/EU-restricted data
location for user account records** -- unlike Cloud SQL, BigQuery, GCS
or KMS (all of which let you pin a region), Identity Platform/Firebase
Auth's user-account storage location is not configurable to
`europe-west2` or any other specific region, so it cannot satisfy a
UK-only (or any region-pinned) residency decision.

UK-compatible alternatives:
1. **Self-hosted OIDC in `europe-west2`** (e.g. `dex`, proven against
   CAIRN's own OIDC integration in
   `apps/api/tests/test_oidc_dex_integration.py` -- or Keycloak) -- full
   control over where user records live, and the console's sign-in flow
   (`apps/console/src/oidc.ts`) already works against any spec-compliant
   OIDC provider with no code change. See `docs/identity.md`.
2. **Customer SSO only** -- CAIRN never stores end-user credentials at
   all; each customer's own IdP (already resident wherever they need it)
   is the provider. Simplest residency story, but means every deployment
   needs a working OIDC/SAML IdP before onboarding.

Which to stand up, and for whom, is an operational decision for whoever
runs a given deployment -- CAIRN ships no hosted identity provider.
