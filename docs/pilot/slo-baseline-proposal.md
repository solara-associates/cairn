# SLO baseline -- proposal, not a commitment

Status: R1-20. Numbers below are derived from this session's own
measurements against the real `cairn_api` app (R0-12's `cairn.red.*`
signals are the production equivalent of what was timed here --
`packages/kernel/src/cairn_kernel/observability/red.py`), not invented
targets. **These are a proposal for Allan to accept, adjust, or
replace -- nothing here is a commitment to a pilot customer.**

## How these numbers were produced

A local benchmark script ran 10 full iterations of create-project ->
queue-assessment-run (one small CSV file) -> get-results -> get-report
-> build-evidence-package against a locally running `cairn_api`
instance (in-memory stores, single process, no real database, no
network latency beyond localhost, one request at a time -- not a
deployed, multi-tenant, concurrently-loaded environment). Timings are
wall-clock per HTTP call, in milliseconds.

| Operation | n | min | p50 | p95 | max |
|---|---|---|---|---|---|
| `POST /v1/projects` | 10 | 1.7 | 1.8 | 53.8 | 53.8 |
| `POST .../assessment-runs` (queue + run to completion) | 10 | 1.8 | 1.9 | 2.3 | 2.3 |
| `GET .../assessment-runs/{id}/results` | 10 | 2.5 | 2.7 | 3.1 | 3.1 |
| `GET .../assessment-runs/{id}/report` | 10 | 1.8 | 1.9 | 2.2 | 2.2 |
| `POST .../assessment-runs/{id}/evidence-package` | 10 | 2.6 | 2.7 | 3.0 | 3.0 |

(The one 53.8ms outlier on project creation was the very first call in
the run, consistent with one-time import/warm-up cost, not a
representative steady-state figure.)

## What this does and does not prove

- **Proves**: the pipeline itself (ingest through evidence export) adds
  negligible latency against small fixtures with in-memory stores --
  single-digit milliseconds per call, end to end.
- **Does not prove**: anything about a real deployment. No real
  Postgres connection, no network hop between services, no concurrent
  load, no realistically sized estate file (hundreds or thousands of
  resources, not three), and no real GCP provider round-trip (R1-02's
  connection validate step used the default always-succeeds validator,
  never a live API call) were part of this measurement.

## Proposed baseline (pending Allan)

Framed as a starting point for a pilot, deliberately generous given
the gap between what was measured and a real deployment:

- **API availability**: `[ALLAN: decide]` -- no uptime commitment
  should be proposed from a local benchmark; this needs an actual
  SLA/support-tier decision, not an engineering number.
- **Read-path latency** (project list, run results, report): propose
  p95 < 500ms once a real deployed database and network hop are
  accounted for -- roughly 150-250x the measured in-memory figure, to
  leave real headroom for Postgres round-trips and TLS.
- **Assessment-run completion**: propose "completes within the same
  pilot session" rather than a fixed number -- this session's own
  measurement (a few milliseconds for a 3-row CSV) does not generalise
  to a pilot's real estate size, and no load test against a realistic
  file has been run.
- **Evidence-package export**: propose p95 < 1s once a real KMS-backed
  signer (not yet built, see `docs/runbooks/pilot-onboarding.md`'s
  Finding 5) replaces today's local HMAC signer -- a real KMS call
  adds network latency this measurement cannot predict.

## Needs Allan

1. Accept, adjust, or replace every number above -- these are
   engineering-derived starting points, not commitments.
2. Decide what uptime/support-tier commitment (if any) accompanies a
   pilot.
3. Decide whether a load test against a realistically sized estate
   file is required before any SLO is quoted to a pilot customer.
