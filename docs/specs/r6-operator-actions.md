# R6 operator actions — what Allan must do

**Status:** a list, not a script. **Nothing in this file has been run.** No command here was executed while writing it, and none should be run by an agent: every one of them touches IAM, service accounts, API enablement or Secret Manager, which the command guard denies to a generating agent (A7.agent-credentials, A9.irreversible-confirm) and which are the product owner's to authorise.

Project throughout: `solara-cairn-dev`. Every command carries `--project=solara-cairn-dev` explicitly — no `gcloud config set` anywhere, so nothing here depends on or changes an ambient default.

Read §6 before running anything: it says which units are blocked on which action, and what the cost exposure is.

---

## 1. Enable the Vertex AI API

Required before any Gemini call can succeed. One API; nothing else in R6 needs a new API.

```
gcloud services enable aiplatform.googleapis.com --project=solara-cairn-dev
```

To confirm:

```
gcloud services list --enabled --project=solara-cairn-dev --filter="config.name:aiplatform.googleapis.com"
```

---

## 2. Service accounts

Two, one per workload that calls a model. Separate accounts rather than one shared, so the API service's blast radius and the worker's differ and each can be revoked independently.

```
gcloud iam service-accounts create cairn-agent-worker \
    --display-name="CAIRN agent worker (R6)" \
    --description="Runs agent plan-act-observe loops; calls Vertex AI Gemini" \
    --project=solara-cairn-dev

gcloud iam service-accounts create cairn-agent-api \
    --display-name="CAIRN agent API (R6)" \
    --description="Starts and reads agent runs; calls Vertex AI Gemini for synchronous steps" \
    --project=solara-cairn-dev
```

If a service account for the existing worker or API already exists and you would rather reuse it, that is a reasonable call — the design does not require new identities, only that the identity which calls Vertex holds `roles/aiplatform.user` and nothing more. Check first:

```
gcloud iam service-accounts list --project=solara-cairn-dev
```

---

## 3. IAM bindings

One role per service account. `roles/aiplatform.user` is the least-privilege role that permits `generateContent`; it grants no model tuning, no dataset access and no deployment.

```
gcloud projects add-iam-policy-binding solara-cairn-dev \
    --member="serviceAccount:cairn-agent-worker@solara-cairn-dev.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user" \
    --condition=None

gcloud projects add-iam-policy-binding solara-cairn-dev \
    --member="serviceAccount:cairn-agent-api@solara-cairn-dev.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user" \
    --condition=None
```

For your own machine, so the live smoke test (R6-20) can authenticate as you rather than as a service account:

```
gcloud auth application-default login
gcloud auth application-default set-quota-project solara-cairn-dev
```

To confirm the bindings:

```
gcloud projects get-iam-policy solara-cairn-dev \
    --flatten="bindings[].members" \
    --filter="bindings.role:roles/aiplatform.user" \
    --format="table(bindings.role, bindings.members)"
```

### Attaching the accounts to the services

The Cloud Run services are managed by Terraform in `infra/terraform`, so the service-account attachment belongs in that code and in a reviewed plan, not in a `gcloud run services update`. The change is: set the `cairn-runtime` module's worker and API service accounts to the two above, and add the three non-secret environment values from §4. That is a Terraform PR for you to review and apply — this design does not apply it, and no agent should.

---

## 4. Secrets

**R6 needs no secret value.** This is worth stating plainly because the brief anticipated some:

- Vertex AI authenticates by application default credentials — the attached service account in Cloud Run, your ADC locally. There is no API key, and the adapter has no code path that reads one (R6-06's acceptance test asserts this by grep).
- Model configuration is not secret: `CAIRN_VERTEX_PROJECT`, `CAIRN_VERTEX_LOCATION`, `CAIRN_GEMINI_MODEL`, `CAIRN_MODEL_ADAPTER`. All four are plain environment values set by Terraform, and all four are safe in a repository, a plan output and a log line.

So there is no new Secret Manager entry to create, and no name to reserve. If a later unit does need one, the convention this repository already follows applies — a name only, never a value, never read or printed by an agent:

```
projects/solara-cairn-dev/secrets/cairn-<purpose>/versions/latest
```

Existing secrets (database credentials, OIDC client secret, KMS key references) are unchanged by R6. Nothing in this design reads, rotates, prints or needs the value of any of them.

---

## 5. Database migration

R6-15 adds two tables (`agent_run`, `agent_step`) with forced row-level security. The migration is written and reviewed like every other migration in `packages/adapters/src/cairn_adapters/persistence_postgres/migrations`, and is applied by the existing documented path — **not** by an agent, and not by an ad-hoc `psql`. `tests/integration/test_migrations.py` proves the RLS policies under the application role before it goes anywhere near a deployed database.

What you need to do: review the migration PR when R6-15 opens, and run the apply the way the existing runbook specifies.

---

## 6. What is blocked on what, and what it will cost

| Action | Blocks | Consequence if not done |
|---|---|---|
| §1 Enable `aiplatform.googleapis.com` | R6-20 (live smoke) | Every unit still completes against the fake adapter; the ADK adapter is never proven against a real provider, so the honest claim stays "agentic against deterministic adapters". |
| §2 Service accounts | Deploying R6 to `dev` | Nothing blocked in development; `make test` needs no GCP project at all. |
| §3 IAM bindings | R6-20, and any deployed agent run | As §1. Your own ADC login is the minimum for the live smoke test. |
| §3 Terraform attachment | Deploying R6 to `dev` | A deployed service would fall back to the fake adapter (the default) rather than fail — which is safe, and also means a misconfiguration would be quiet. R6-06 makes it loud instead: selecting `vertex` with missing config fails at startup. |
| §4 Secrets | nothing | No secret is needed. |
| §5 Migration | R6-15 onward in a deployed environment | Tests use the in-memory implementations; a deployed agent run needs the tables. |

**Cost exposure.** Once §1 and §3 are done, a real Gemini call is billable. Three things bound it, and they are design commitments, not hopes: the per-run budgets (ADR-019 §4, five dimensions, no dimension defaulting to unbounded), the per-tenant R5-02b cost-control loop which can throttle or stop on a spend window, and the fake adapter remaining the default so nothing calls a real provider unless a deployment explicitly opts in. The live smoke test is one call with a tiny prompt. Worth setting the per-run cost ceiling you are comfortable with before R6-03 fixes the defaults — the numbers in the design are bounds chosen to be safe, not measurements.

**Nothing here is reversible for free.** Enabling an API and granting IAM are both cheap to undo, but a billable call is not. That is why this is your list and not a script.
