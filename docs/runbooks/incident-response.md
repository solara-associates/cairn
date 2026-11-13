# Incident response runbook

Status: R0-20 gate 12 (incident-response half). Paired with a conformance
check (`tests/conformance/test_incident_response_signals.py`) that asserts
every signal named below actually exists, under that name, in the
observability kit's code. If a signal is renamed or removed in
`packages/kernel/src/cairn_kernel/observability/`, this document fails CI
instead of silently going stale.

This runbook covers detection, escalation, containment, evidence
preservation and post-incident review for an incident in a CAIRN
environment (a production outage, a suspected tenant-isolation breach, a
bad deploy, or a security event). It does not cover routine alerting
thresholds or on-call rotation policy -- those are operational decisions
for whoever owns on-call, not something a file-only session can set.

## Instrumented signals (checked by CI)

`tests/conformance/test_incident_response_signals.py` parses this table and
asserts, for every row, that the source file exists and that its current
content contains the signal literally. A signal rename or removal in the
observability kit fails this test until the table below is updated to
match -- the runbook cannot silently drift from what is actually
instrumented.

| Signal | Source |
| --- | --- |
| `cairn.red.requests` | `packages/kernel/src/cairn_kernel/observability/red.py` |
| `cairn.red.errors` | `packages/kernel/src/cairn_kernel/observability/red.py` |
| `cairn.red.duration` | `packages/kernel/src/cairn_kernel/observability/red.py` |
| `x-correlation-id` | `packages/kernel/src/cairn_kernel/observability/correlation.py` |
| `trace_attributes` | `packages/kernel/src/cairn_kernel/observability/tracing.py` |
| `model.call.completed` | `packages/kernel/src/cairn_kernel/observability/ai.py` |
| `REQUIRED_LOG_FIELDS` | `packages/kernel/src/cairn_kernel/observability/logging.py` |
| `ledger_entry_append_only` | `packages/adapters/src/cairn_adapters/persistence_postgres/migrations/0003_audit_ledger.up.sql` |
| `subject_revision_append_only` | `packages/adapters/src/cairn_adapters/persistence_postgres/migrations/0005_revision_approval_execution.up.sql` |

## 1. Detection

Detection is the observability kit that already exists on `main`
(`packages/kernel/src/cairn_kernel/observability/`), not a separate
monitoring stack. An incident is first noticed through one or more of:

- **RED metrics** (`observability/red.py`, `RedMetrics`): the three
  OpenTelemetry instruments every service and adapter emits per operation --
  `cairn.red.requests` (rate), `cairn.red.errors` (errors) and
  `cairn.red.duration` (latency histogram, ms), each labeled `service`,
  `operation`, `outcome` (`OK`/`ERROR`). A sustained rise in
  `cairn.red.errors` or `cairn.red.duration` for one `service`/`operation`
  pair is the primary automated signal. `RedMiddleware` wires this into
  every HTTP request automatically.
- **Trace correlation** (`observability/tracing.py`,
  `observability/correlation.py`): every request carries a correlation ID
  (`x-correlation-id` header, `correlation_from_header`/
  `new_correlation_id`), and `trace_attributes()` stamps `tenant_id`,
  `project_id`, `correlation_id` and `operation_id` onto the active span.
  Given one failing request's correlation ID (from a user report, a log
  line, or an alert), every span and log line for that request across
  every service is findable by that one ID -- this is how an operator
  moves from "something is wrong" to "here is the exact failing call."
- **The AI-call log** (`observability/ai.py`, `AiCallRecord` /
  `JsonAiCallLogger`): every model call emits a `model.call.completed`
  structured log event carrying `provider`, `model`, `input_hash`,
  `schema_valid`, `outcome`, `latency_ms`, token counts, `cost_micro_usd`,
  `correlation_id`, `tenant_id`, `project_id` and `agent_run_id`. A spike in
  `schema_valid: false` or a particular `outcome` is the detection signal
  for an AI-specific incident (a model returning malformed output, or a
  provider outage).
- **Structured logs generally** (`observability/logging.py`,
  `StructuredLogger` / `JsonLogFormatter`): every log line is JSON and
  always carries `REQUIRED_LOG_FIELDS` -- `correlation_id`, `tenant_id`,
  `project_id`, `operation_id` -- even when `None`, so a log search never
  needs to guess whether a field exists.

If a reported incident cannot be pointed at one of the above (a metric
name, a trace, a log event), the first containment step is to establish
which one *should* have fired and treat the gap itself as a finding for
the post-incident review (section 5) -- not to invent a new ad hoc signal
mid-incident.

## 2. Escalation

1. Whoever notices the incident (an alert, a support report, or an
   engineer) opens an incident channel/ticket and states, in one line:
   what signal fired (metric name, or "no signal fired, reported by
   <channel>"), which `service`/`operation` and which `tenant_id` (if
   known) are affected.
2. Classify severity by blast radius, using the tenancy classification
   this estate already enforces
   (`cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS`,
   ADR-012): a `GLOBAL`-scope anomaly (e.g. `schema_migration`) is a
   platform-wide incident by definition; a `TENANT`- or `PROJECT`-scope
   anomaly confined to one `tenant_id` is scoped to that tenant until
   proven otherwise.
3. A suspected cross-tenant data exposure (any finding that a `tenant_id`
   filter was missing, bypassed, or returned another tenant's rows) is
   always Sev-1 regardless of blast radius measured so far, and escalates
   immediately to whoever owns ADR-012 (the tenancy contract) -- this is
   the exact adversarial failure mode `R-TENANT-03` and
   `tests/integration/test_migrations.py`'s `test_missing_context_fails_closed`
   etc. exist to make structurally rare, which is why one occurring in
   practice is never treated as routine.
4. Allan is notified for any Sev-1, and for any Sev-2 that is still open
   after the first hour.

## 3. Containment

- Containment actions are themselves mutations, so the same
  classification and gating this estate applies to every other mutation
  applies here: an `IRREVERSIBLE_EXTERNAL_MUTATION` containment action
  (e.g. revoking a credential, disabling a connected customer
  integration) still needs the compensation-contract discipline of
  ADR-010 -- "move fast" is not a license to skip recording *why* and
  *with what authority* a containment step was taken.
- Prefer feature-flag/traffic-level containment (pausing an ingestion
  path, rejecting new requests for the affected `operation`) over data
  mutation wherever the incident allows it, because it is reversible and
  does not touch the tables the deletion/retention runbooks and the audit
  ledger care about.
- Record every containment action's timestamp and correlation/trace ID as
  you take it, in the incident channel, before context-switching to the
  next action. Mid-incident intentions that are never written down are
  the single most common gap found during post-incident review.

## 4. Evidence preservation

The audit/evidence ledger is the one piece of this estate that an
incident must never be allowed to make worse:

- `ledger_entry` (migration
  `packages/adapters/src/cairn_adapters/persistence_postgres/migrations/0003_audit_ledger.up.sql`)
  is append-only by trigger (`ledger_entry_append_only`,
  `ledger_entry_no_truncate`) -- UPDATE, DELETE and TRUNCATE are rejected
  unconditionally, for every role, including the migration superuser. No
  incident containment step may attempt to disable that trigger to "clean
  up" a ledger row; if a row looks wrong, that is itself the finding, not
  something to edit away.
- `subject_revision` (migration `0005_revision_approval_execution.up.sql`)
  is append-only the same way, for the same reason: a revision history
  that could be edited mid-incident would be evidence that cannot be
  trusted afterwards.
- `packages/kernel/src/cairn_kernel/evidence/` (`envelope.py`, `verify.py`,
  R0-11/R-EVID-01) is how a canonicalized, signed evidence package is
  verified offline, independent of the database -- if an incident calls the
  ledger's own integrity into question, `verify_ledger` (R-EVID-01's test
  suite, `packages/kernel/tests/test_evidence.py`) is the tool to run
  against it, not a manual row-by-row read.
- The tenant-deletion procedure (`docs/runbooks/tenant-deletion.md`) is
  built on exactly this constraint: it never deletes `ledger_entry` or
  `subject_revision` rows, even for a tenant being deleted. An incident
  responder should expect the same -- evidence outlives the thing it is
  evidence of.
- If a containment step requires writing new facts into the ledger (a
  forced tenant suspension, a credential revocation), it must flow through
  the normal `PostgresAuditSink`/`append_entry` path
  (`packages/adapters/src/cairn_adapters/persistence_postgres/audit.py`),
  signed and sequenced like any other mutation -- never a raw `UPDATE`
  against another table hoping the ledger catches up later.

## 5. Post-incident review

Within 5 business days of containment:

1. Reconstruct the timeline from the correlation IDs and `cairn.red.*`
   metrics gathered during detection/containment -- not from memory.
2. State which detection signal fired first, how long between that signal
   firing and a human acting on it, and whether that gap is acceptable.
3. If no signal fired and the incident was reported externally, that is a
   detection gap: file it as a follow-up to extend
   `packages/kernel/src/cairn_kernel/observability/` (a new RED label, a
   new structured-log field, a new AI-call outcome category), not as a
   one-off dashboard query.
4. Record the review itself as a ledger entry or linked evidence package
   if the incident involved any tenant-scoped data, so the review is
   itself subject to the same evidence-preservation guarantees as the
   incident it reviews.
5. Any containment action that turned out to be irreversible and was not
   pre-approved under ADR-010's compensation-contract discipline is a
   process finding in its own right, reported to Allan regardless of
   whether the incident itself was otherwise resolved cleanly.
