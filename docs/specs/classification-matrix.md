# Operation and mutation classification matrix (R0-19)

**Source of truth:** code, not this page.

- Operations (APIs, MCP tools/resources, events, worker jobs):
  `packages/kernel/src/cairn_kernel/classification/matrix.py` (`OPERATIONS`).
- Entities (tables, buckets), Global/Tenant/Project:
  `packages/kernel/src/cairn_kernel/tenancy/classification.py`
  (`TABLE_CLASSIFICATIONS`) — this already existed before R0-19 and is
  enforced live against Postgres by
  `tests/integration/test_migrations.py::test_every_table_is_classified_with_required_rls`.

This page is a reader's map to that code, not a second copy of it.

## Enforcement

`tools/conformance/rules.yaml` rule `R-OPCLASS-01` runs:

- `packages/kernel/tests/test_classification_model.py` — proves the
  classification mechanism itself: operation class and mutation class must
  agree (spec section 5.2), and an external mutation class
  (`REVERSIBLE_EXTERNAL_MUTATION` / `COMPENSATABLE_EXTERNAL_MUTATION` /
  `IRREVERSIBLE_EXTERNAL_MUTATION`) cannot exist without a complete
  compensation contract (spec section 5.3) whose strategy matches the
  mutation class.
- `tests/conformance/test_classification_matrix.py` — discovers the real
  surfaces in the running code (API routes on `apps/api` and `apps/worker`,
  every event type declared in `cairn_contracts.events.model`) and fails if
  one is missing from `OPERATIONS`, or if `OPERATIONS` names a surface that
  no longer exists.

Removing a classification entry for a surface that still exists fails
`tests/conformance/test_classification_matrix.py` immediately — this was
verified during R0-19 by deleting one entry, confirming the test failed, and
restoring it.

## Counts as of R0-19 (R0-01..R0-15's work)

| Surface | Count | Classes present |
|---|---|---|
| API (apps/api, apps/worker health/readiness) | 4 | Class A, `READ_ONLY` |
| Event (declared in `cairn_contracts.events.model`) | 20 | 17 Class B `INTERNAL_MUTATION`; 3 Class C (`execution.*`) with a deferred mutation class — see below |
| MCP tool / resource | 0 | `apps/mcp-gateway` is a docstring-only stub |
| Worker job | 0 | no job beyond the health API above exists yet |
| Table (Global/Tenant/Project) | 8 | see `cairn_kernel.tenancy.classification` |
| Bucket | 0 | no GCS adapter is wired yet |

No external mutation (`REVERSIBLE_EXTERNAL_MUTATION`,
`COMPENSATABLE_EXTERNAL_MUTATION`, or `IRREVERSIBLE_EXTERNAL_MUTATION`) exists
in R0 — ADR-010 and spec section 1423/1601 both require no Class C adapter
before R4. The compensation-contract mechanism (`CompensationContract` in
`cairn_kernel.classification.model`) is built and unit-tested now so that the
first real external mutation, whenever it lands, cannot be added without one.

### The three `execution.*` events are a deliberate exception

`execution.started.v1`, `execution.completed.v1` and `execution.failed.v1`
are Class C (`GOVERNED_ENV_MUTATION`) by construction, but their concrete
mutation class is not fixed here: spec section 5.3 binds the compensation
contract "to the immutable revision and approval," which does not exist
until R1-21/R1-22. Each entry carries `mutation_class=None` with a
`defer_reason` explaining this, and the model (`OperationEntry.__post_init__`
in `cairn_kernel/classification/model.py`) only allows that deferral for
Class C. `tools/conformance/rules.yaml` rules `R-MUT-01`/`R-MUT-02` already
track the per-instance enforcement as pending on R1-21/R1-22 — this matrix
does not duplicate or pre-empt that work.

## Review

**Allan's review of this classification is outstanding.** The spec's
acceptance criterion for R0-19 includes "review approved"; this matrix and
its enforcing tests are ready for that review but have not been through it.
