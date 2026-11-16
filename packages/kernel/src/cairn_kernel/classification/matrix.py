"""The R0-19 operation classification matrix: every API, MCP tool/resource,
event and worker job that exists in R0-01..R0-15's work today.

Table and bucket entity tenancy classification already exists and is kept
honest elsewhere (``cairn_kernel.tenancy.classification``, enforced live
against Postgres by ``tests/integration/test_migrations.py``); this module
does not duplicate it.

This module is deliberately exhaustive and deliberately small. Each entry
below has a one-line reason because the surface it describes is thin (R0 has
not built the production adapters yet); the reason is not padding, it is the
honest answer to "why is this classified this way" that the acceptance
criteria asks for.

Scope: no MCP tool/resource or worker job is classified below because none
exists in the codebase yet (``apps/mcp-gateway`` and ``apps/cli`` are
docstring-only stubs; no ``EventPublisher`` adapter is wired; the worker and
scheduler apps expose no job beyond the health API already listed). Nothing
here invents an R1 surface — see ``tests/conformance/
test_classification_matrix.py`` for the discovery that this matrix is kept
honest against.
"""

from __future__ import annotations

from cairn_kernel.classification.model import OperationEntry, SurfaceKind
from cairn_kernel.hex.primitives import MutationClass, OperationClass
from cairn_kernel.tenancy.classification import TenancyScope

# Health/readiness probes read in-process state only; no tenant data crosses them.
OPERATIONS: tuple[OperationEntry, ...] = (
    # --- apps/api: GET /healthz, GET /readyz (R0-15) ---
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /healthz",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /readyz",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    # --- apps/worker: GET /healthz, GET /readyz (R0-15) ---
    OperationEntry(
        surface=SurfaceKind.API,
        name="worker.GET /healthz",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="worker.GET /readyz",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    # --- apps/api: project, membership and settings APIs (R1-01) ---
    # Creating and listing projects are tenant-level actions (no project
    # exists yet, or the query spans every project the caller's tenant
    # owns); every other route below acts on one existing project and is
    # project-scoped. None of these crosses into a customer environment
    # (ADR-010), so each mutation is Class B INTERNAL_MUTATION with no
    # compensation contract, and each read is Class A READ_ONLY.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.PATCH /v1/projects/{project_id}",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/members",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/members",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.DELETE /v1/projects/{project_id}/members/{user_id}",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/settings",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.PUT /v1/projects/{project_id}/settings",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: assessment orchestration async operation API (R1-15) ---
    # Queuing/advancing a run is CAIRN's own workspace state (checkpoints,
    # artifacts derived from already-ingested data); it never touches a
    # customer environment (ADR-010), so each is Class B INTERNAL_MUTATION
    # with no compensation contract, same as the project routes above.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/assessment-runs",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/assessment-runs/{run_id}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: assessment run inspection, 6R review, report and
    # evidence export (R1-16, R1-17, R1-18) ---
    # Every route below reads or mutates this project's own already-
    # computed assessment artifacts (stage outputs, 6R review state, a
    # rendered report, a sealed evidence package); none of it crosses
    # into a customer environment (ADR-010), so reads are Class A
    # READ_ONLY and mutations are Class B INTERNAL_MUTATION with no
    # compensation contract, same reasoning as the routes above.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/assessment-runs/{run_id}/results",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/assessment-runs/{run_id}/report",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name=(
            "api.POST /v1/projects/{project_id}/assessment-runs/{run_id}"
            "/decisions/{decision_id}/accept"
        ),
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name=(
            "api.POST /v1/projects/{project_id}/assessment-runs/{run_id}"
            "/decisions/{decision_id}/reject"
        ),
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name=(
            "api.POST /v1/projects/{project_id}/assessment-runs/{run_id}"
            "/decisions/{decision_id}/amend"
        ),
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/assessment-runs/{run_id}/evidence-package",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: provider connection create/validate/revoke (R1-02) ---
    # A connection record is CAIRN's own workspace state (ADR-010: it
    # carries a read-only assessment credential only, never execution
    # scope), so creating/validating/revoking it is Class B
    # INTERNAL_MUTATION with no compensation contract, and reading it
    # is Class A READ_ONLY -- same reasoning as the project routes.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/connections",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/connections/{connection_id}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/connections/{connection_id}/validate",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/connections/{connection_id}/revoke",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: mapping registry service, workflow and resolver (R2-01) ---
    # Reads (list/get a release, resolve) are Class A READ_ONLY. The
    # release content itself is global (spec 8.1), but these entries carry
    # TENANT scope the same way ``api.GET /v1/projects`` does above: "every
    # tenant can read this", not "this data belongs to one tenant".
    # Proposing a mapping change is Class B INTERNAL_MUTATION, genuinely
    # tenant-scoped -- a proposal is tenant-owned (spec 8.1) even though
    # the release it targets is global. Publishing is Class B
    # INTERNAL_MUTATION too, but GLOBAL: it mutates the global
    # mapping_release/mapping_release_review tables and is gated by
    # PLATFORM_OPERATOR (spec 12.1), never a tenant role --
    # ``cairn_api.security.require_platform_operator``, not ``get_principal``.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/mappings",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/mappings/{version}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/mappings/resolve",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/mappings/proposals",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/mappings/{version}:publish",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    # --- apps/api: design/plan export (R2-08), reading 703-706's already-
    # generated target model, diagram, IaC preview and migration roadmap ---
    # Every route below only reads CAIRN's own workspace artefacts (a
    # design's target model/diagram/IaC preview, a plan's roadmap
    # revisions); none of it crosses into a customer environment
    # (ADR-010), so each is Class A READ_ONLY, project-scoped the same
    # way the assessment-run inspection routes above are.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}/diagram",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}/report",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/projects/{project_id}/plans",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/plans/{plan_id}/revisions/{revision_number}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: design console screens (R2-09) -- generating/
    # regenerating a design, and reading the pattern catalogue, per-
    # revision history and IaC preview text those screens need ---
    # Generating/regenerating a design produces CAIRN's own workspace
    # artefacts only (a target model, diagram and IaC *preview*, a
    # roadmap) -- it never applies anything and never crosses into a
    # customer environment (ADR-010), so each write below is Class B
    # INTERNAL_MUTATION with no compensation contract, the same
    # reasoning the assessment-run and connection routes above already
    # use. Regenerating never deletes or overwrites the previous
    # revision (it only appends one), so it carries no rollback/
    # compensation contract either -- the prior revision is simply still
    # there.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/patterns",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/designs",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/designs/{design_id}/regenerate",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}/revisions",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}/revisions/{revision_number}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/designs/{design_id}/iac",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: unified diff artefact and preview API (R3-04) ---
    # Scanning and producing a preview triggers 721's RepositorySourcePort
    # (reads a customer repository, never writes to it -- ADR-010/R3-01's
    # own "no write-back" discipline) and 726's TransformationPort (computes
    # a manifest, applies nothing), then records that manifest as CAIRN's
    # own workspace state -- it never crosses into a customer environment
    # with a write, so it is Class B WORKSPACE_MUTATION/INTERNAL_MUTATION
    # with no compensation contract, the same reasoning the design-console
    # write routes above already use. Reading a recorded run's summary or
    # its rendered diff is Class A READ_ONLY, same as every other read
    # route in this app.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/projects/{project_id}/transformations",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/transformations/{run_id}",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/transformations/{run_id}/diff",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # 729/R3-05's validation route runs every configured ValidationPort
    # check (cairn_modules.transformation.validation) against an already-
    # recorded run's manifest/diff and records the aggregated outcome on
    # this app's own TransformationRegistry -- it never fetches from, or
    # writes to, a customer environment (no adapter it calls does either:
    # the static check re-parses in-memory text, the test-suite check
    # runs only against an isolated temp copy, the dependency check reads
    # only the already-fetched files), so this is Class B
    # WORKSPACE_MUTATION/INTERNAL_MUTATION with no compensation contract,
    # the same reasoning the create-transformation route above already
    # uses.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/transformations/{run_id}:validate",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- apps/api: diff review and validation console's own two
    # additional routes (R3-07) ---
    # Sealing a transformation run's evidence package is this app's own
    # workspace action (730's signed-evidence machinery, the same
    # reasoning the assessment evidence-package route above already
    # uses) -- it reads a customer environment nowhere in this call
    # path, so Class B WORKSPACE_MUTATION/INTERNAL_MUTATION. The review-
    # comment thread is likewise CAIRN's own workspace annotation,
    # attached to an already-recorded run -- posting one is Class B
    # WORKSPACE_MUTATION/INTERNAL_MUTATION, same reasoning; reading the
    # thread is Class A READ_ONLY, same as every other read route above.
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/transformations/{run_id}/evidence-package",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.POST /v1/transformations/{run_id}/review-comments",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.API,
        name="api.GET /v1/transformations/{run_id}/review-comments",
        operation_class=OperationClass.READ,
        mutation_class=MutationClass.READ_ONLY,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- cairn_contracts.events: declared event envelopes (R0-05) ---
    # Every event below records a CAIRN-workspace fact or state change; none
    # of them is produced by a wired publisher yet (no EventPublisher adapter
    # exists in R0), and none crosses into a customer environment, so each is
    # Class B / INTERNAL_MUTATION with no compensation contract (spec 5.2:
    # "Not applicable; no customer-environment effect").
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="ingestion.requested.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="ingestion.completed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="ingestion.failed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="estate.normalized.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="estate.fact.confirmed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="assessment.requested.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="assessment.completed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="finding.recorded.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="exception.accepted.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="cost.imported.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="baseline.created.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="scenario.created.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="mapping.release.published.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        # Global mapping releases are CAIRN-operated control data (spec 8.1),
        # not scoped to any one tenant.
        tenancy_scope=TenancyScope.GLOBAL,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="mapping.proposed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        # A tenant's proposed amendment to a mapping; no global publish authority.
        tenancy_scope=TenancyScope.TENANT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="design.generated.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="plan.created.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="plan.revised.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="approval.requested.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="approval.decided.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="evidence.sealed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="evidence.verified.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="model.call.completed.v1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
        # The AI-call log entry is attributed to the project whose work triggered the call.
        tenancy_scope=TenancyScope.PROJECT,
    ),
    # --- cairn_contracts.events: execution lifecycle (R0-05 contract only) ---
    # These three event types describe a Class C governed-environment mutation
    # by construction (spec 1423, 1674), but R0 has no execution adapter and
    # no revision/approval model (those are R1-21/R1-22). The concrete
    # mutation class (reversible / compensatable / irreversible) and its
    # compensation contract are bound per approved revision, not fixed at the
    # event-type level (spec 5.3: "bound to the immutable revision and
    # approval"), so they are correctly deferred here rather than guessed.
    # R-MUT-01/R-MUT-02 in tools/conformance/rules.yaml enforce the concrete,
    # per-instance obligation once R1-21/R1-22 land; this entry only commits
    # to the Class C envelope that already exists in the contract today.
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="execution.started.v1",
        operation_class=OperationClass.GOVERNED_ENV_MUTATION,
        mutation_class=None,
        tenancy_scope=TenancyScope.PROJECT,
        defer_reason=(
            "mutation class is bound to the approved revision's compensation contract"
            " (spec 5.3); no execution adapter exists before R4 (ADR-010)"
        ),
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="execution.completed.v1",
        operation_class=OperationClass.GOVERNED_ENV_MUTATION,
        mutation_class=None,
        tenancy_scope=TenancyScope.PROJECT,
        defer_reason=(
            "mutation class is bound to the approved revision's compensation contract"
            " (spec 5.3); no execution adapter exists before R4 (ADR-010)"
        ),
    ),
    OperationEntry(
        surface=SurfaceKind.EVENT,
        name="execution.failed.v1",
        operation_class=OperationClass.GOVERNED_ENV_MUTATION,
        mutation_class=None,
        tenancy_scope=TenancyScope.PROJECT,
        defer_reason=(
            "mutation class is bound to the approved revision's compensation contract"
            " (spec 5.3); no execution adapter exists before R4 (ADR-010)"
        ),
    ),
)

__all__ = ["OPERATIONS"]
