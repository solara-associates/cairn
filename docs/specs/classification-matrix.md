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

## Counts as of R1-01 (R0-01..R0-15, R0-19 and R1-01's work)

| Surface | Count | Classes present |
|---|---|---|
| API (apps/api, apps/worker health/readiness; R1-01 project/membership/settings) | 13 | Class A `READ_ONLY` (health/readiness, project/member/settings reads); Class B `INTERNAL_MUTATION` (project create/update, member add/remove, settings set) |
| Event (declared in `cairn_contracts.events.model`) | 20 | 17 Class B `INTERNAL_MUTATION`; 3 Class C (`execution.*`) with a deferred mutation class — see below |
| MCP tool / resource | 0 | `apps/mcp-gateway` is a docstring-only stub |
| Worker job | 0 | no job beyond the health API above exists yet |
| Table (Global/Tenant/Project) | 8 | see `cairn_kernel.tenancy.classification`; R1-01's project/membership/settings surface reuses the existing `project` and `role_grant` tables, so no new table was added |
| Bucket | 0 | no GCS adapter is wired yet |

R1-01 added 9 API routes (create/read/update project; add/remove/list
members; get/set settings, under `/v1/projects`), backed by
`cairn_modules.projects.InMemoryProjectRepository` — the first in-process
adapter any bounded-context module has shipped. `apps/api` still wires no
production datastore for any surface, so this matches R0's existing
maturity rather than introducing one ahead of need. Cross-tenant isolation
is enforced the same way `packages/kernel/tests/test_tenancy_isolation.py`
proves it for a generic repository: through the ambient `TenantContext`
(ADR-012), not a new RLS policy — no new table was added, so none was
needed.

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

R0-19 classification matrix (PR #14) approved by Allan Smeyatsky on
2026-11-13.
