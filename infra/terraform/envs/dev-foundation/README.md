# CAIRN dev cloud foundation (session 684)

The minimal set Allan authorised for `solara-cairn-dev`: a Terraform
state bucket, a KMS key ring and an evidence-signing key. Not the full
`dev` environment (`infra/terraform/envs/dev`) -- no network, IAM
service accounts, Cloud SQL, Cloud Run, events, observability or
guardrails. That remains R0-16's own, separate, unmet acceptance
criterion (see "R0-16 terraform plan" note below).

## What exists today, and how it was created

Both resources already exist in `solara-cairn-dev` (`europe-west2`):

- `gs://solara-cairn-dev-tfstate` -- versioned, uniform bucket-level
  access, public access prevention enforced.
- KMS key ring `cairn-dev-evidence` with asymmetric signing key
  `cairn-dev-evidence-signing` (`EC_SIGN_P256_SHA256`, software
  protection level).

They were created directly with `gcloud`, not `terraform apply`:

```
gcloud storage buckets create gs://solara-cairn-dev-tfstate \
  --project=solara-cairn-dev --location=europe-west2 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://solara-cairn-dev-tfstate --versioning --project=solara-cairn-dev

gcloud kms keyrings create cairn-dev-evidence --project=solara-cairn-dev --location=europe-west2
gcloud kms keys create cairn-dev-evidence-signing \
  --project=solara-cairn-dev --location=europe-west2 --keyring=cairn-dev-evidence \
  --purpose=asymmetric-signing --default-algorithm=ec-sign-p256-sha256 --protection-level=software
```

**Why not Terraform directly:** the Architectural Rules guard
(`A7.agent-credentials`) denies `terraform init` with a real backend
from a local generating session unless the directory has an
`iac_allowances` entry in `~/.config/architectural-rules/projects.yaml`.
Allan added that entry for this directory, but `terraform init` was
still denied with the identical message afterwards -- the bypass does
not appear to be wired into the guard's actual enforcement yet (the
file's own original comment -- "No iac_allowances... to be decided per
directory if needed" -- suggests it may be aspirational, not
implemented). Rather than work around a guard that explicitly says not
to be worked around, this session used plain `gcloud` (which the
project allowlist does unblock) and wrote this Terraform config to
match, so the state it describes is accurate even though it was never
the thing that created the resources.

The IAM binding granting `roles/cloudkms.signerVerifier` on the signing
key (needed to prove a real signature) was applied by Allan directly,
after this session presented the exact command for confirmation
(`A9.irreversible-confirm` denies IAM changes outright for a generating
session, confirmation or not).

## Bringing these under real Terraform management

The next session that can actually run `terraform init`/`apply` against
`solara-cairn-dev` (either the guard gap above is fixed, or someone runs
it manually) should import rather than re-create:

```
cd infra/terraform/envs/dev-foundation
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform import google_storage_bucket.terraform_state solara-cairn-dev-tfstate
terraform import google_kms_key_ring.evidence projects/solara-cairn-dev/locations/europe-west2/keyRings/cairn-dev-evidence
terraform import google_kms_crypto_key.evidence_signing projects/solara-cairn-dev/locations/europe-west2/keyRings/cairn-dev-evidence/cryptoKeys/cairn-dev-evidence-signing
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
key version, plus a small per-signing-operation cost). The existing
`cairn-dev` billing budget (`$50/month`, already alerting on this
project) comfortably covers this.

## Identity Platform / customer identity: not created, see the residency finding

Before creating anything for sign-in, this session checked where
Google Identity Platform stores user account data, per the UK-only
residency decisions in `docs/residency/uk-residency-matrix.md`.
**Finding: Identity Platform does not offer a UK/EU-restricted data
location for user account records** -- unlike Cloud SQL, BigQuery, GCS
or KMS (all of which let you pin a region), Identity Platform/Firebase
Auth's user-account storage location is not configurable to
`europe-west2` or any other specific region, so it cannot be made to
satisfy decision 1 ("customer data... UK only... no copy outside the
UK"). **Identity Platform was not created.**

UK-compatible alternatives, in order of fit with what this session
already built:
1. **Self-hosted OIDC in `europe-west2`** (e.g. `dex`, the same
   provider this session's console sign-in work (a separate PR) proved
   against in tests -- or Keycloak) -- full control over where user
   records live, and the console's new sign-in flow
   (`apps/console/src/oidc.ts`) already works against any spec-
   compliant OIDC provider with no code change.
2. **Customer SSO only** -- CAIRN never stores pilot end-user
   credentials at all; each customer's own IdP (already UK-resident
   for them, presumably) is the provider. Simplest residency story,
   but means every pilot needs their own working OIDC/SAML IdP before
   onboarding, which not all will have.

No resource was created for either option in this session -- which one
to stand up (and for whom) is Allan's decision, not inferred here.
