# Rollback and compensation recovery runbook

Status: R4-04a (unit 790), ADR-010's compensation-contract table,
"Failure handling" row. Companion to `docs/runbooks/incident-response.md`
-- this runbook covers the one failure mode specific to recovery itself
(a rollback or compensation call that fails while trying to undo a failed
Class C mutation); everything after containment follows the general
incident-response runbook's escalation and post-incident review sections
unchanged.

This runbook does not cover a successful recovery (`ROLLED_BACK`) or an
irreversible mutation's accepted risk (`ACCEPT_IRREVERSIBLE`) -- both are
expected, non-incident outcomes of
`cairn_adapters.provider_execution.recovery.RecoveryEngine`. It covers only
what an operator does when `RecoveryEngine.recover` returns an
`IncidentRecord`.

## 1. What triggers this runbook

`RecoveryEngine.recover` (`packages/adapters/src/cairn_adapters/
provider_execution/recovery.py`) is reached when an `AUTHORIZED` Class C
execution's `apply` attempt fails while `EXECUTING`, for a mutation whose
compensation contract declares `ROLLBACK` or `COMPENSATE`
(`cairn_kernel.classification.model.RecoveryStrategy`). The engine calls
the injected `ProviderExecutionPort.rollback()` exactly once. This runbook
starts the moment that call either:

- raises an exception of any kind, or
- returns a `RollbackResult` whose `status` is not the literal
  `"ROLLED_BACK"` (`EXPECTED_ROLLBACK_STATUS`) -- a provider response that
  merely *looks* successful is treated exactly like a raised exception,
  never as a silent success.

In both cases the engine's own `validate_execution_transition` call
(`cairn_modules.execution.model`, the same ADR-009 transition table R1-22's
execution gate already uses) moves the execution to `ExecutionState.FAILED`
-- never `ROLLED_BACK`, never `SUCCEEDED` -- and the engine returns a
`RecoveryOutcome` carrying a populated `incident: IncidentRecord`.

## 2. First response

1. Read the `IncidentRecord` the engine produced
   (`incident_id`, `tenant_id`, `project_id`, `execution_id`, `approval_id`,
   `strategy`, `reason`, `detail`, `runbook_ref`, `created_at`) -- `reason`
   states plainly whether the provider call raised or returned an
   unexpected status, and `detail` carries the raw exception type/message
   or the adapter's returned status and detail payload.
2. Treat the named `execution_id`/`approval_id`/`revision_id` exactly as
   `docs/runbooks/incident-response.md` section 2 (Escalation) treats any
   other incident: classify severity by blast radius using
   `cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS`, open an
   incident channel/ticket, and state what failed (`recovery strategy`,
   `execution_id`) and which `tenant_id`/`project_id` are affected.
3. A failed recovery for a `COMPENSATABLE_EXTERNAL_MUTATION` or
   `REVERSIBLE_EXTERNAL_MUTATION` means the customer environment is left in
   whatever state the original failed `apply` left it in -- **not** rolled
   back, **not** compensated. This is always at least Sev-2: the
   environment's actual state and CAIRN's recorded state may now diverge
   until a human intervenes. Escalate to whoever holds the `authority` role
   named in the mutation's own `CompensationContract.authority`.
4. Do not retry the same `rollback_token` through `RecoveryEngine` blindly.
   The engine does not retry internally (ADR-010's audit-before-effect and
   idempotency discipline applies to recovery the same way it applies to
   the original mutation) -- a human decides whether retrying is safe,
   informed by `IncidentRecord.detail`, before any further adapter call is
   attempted.

## 3. Containment and manual reconciliation

1. Use the `ReconciliationRecord` the engine also returns alongside the
   incident (`expected_state=ROLLED_BACK`, `actual_state=FAILED`,
   `reconciled=False`) as the starting statement of the gap: CAIRN expected
   the mutation to be undone and it was not.
2. Determine the target environment's actual current state out-of-band
   (the same provider console/CLI a human would use outside CAIRN,
   scoped read-only where possible) and record it against the
   `IncidentRecord.execution_id` -- this is manual because 790 is
   explicitly "no cloud": the engine itself never makes a second,
   unplanned provider call to go find out.
3. Record every manual containment or verification step's timestamp and
   correlation ID in the incident channel as you take it, exactly as
   `docs/runbooks/incident-response.md` section 3 requires for any other
   incident.
4. If manual reconciliation itself requires a further mutation against the
   customer environment (e.g. a hand-run undo), that mutation is itself a
   new Class C operation: propose, approve and authorize it through the
   normal execution gate and compensation-contract discipline -- never a
   raw, ungoverned call "to clean up," even under incident pressure.

## 4. Post-incident review

Follow `docs/runbooks/incident-response.md` section 5 in full, plus:

1. State explicitly whether the provider call raised or returned a wrong
   status -- the two have different likely root causes (a transient
   provider fault vs. an adapter/contract mismatch) and point at different
   fixes.
2. If the failure was an unexpected `RollbackResult.status` rather than an
   exception, treat the adapter's status contract itself as suspect: check
   whether `ProviderExecutionPort.rollback`'s documented return shape
   (`packages/adapters/src/cairn_adapters/provider_execution/ports.py`) has
   drifted from what the adapter in use actually returns.
3. Record the review as a ledger entry or linked evidence package per the
   general runbook's section 5, item 4, referencing the `incident_id` so
   the review and the `IncidentRecord` it reviews stay linked.
