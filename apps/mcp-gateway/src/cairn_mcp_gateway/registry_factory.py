"""Wires this unit's real bounded-context registrations into one
``McpRegistry``, and the scope each tool requires through
``McpGateway``.

Internal-only per ADR-011: no real network MCP server runs, and no
external agent host is wired up in this unit (that's R5-04b/819's A2A
bridge).
"""

from __future__ import annotations

from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_kernel.security import Role
from cairn_kits.mcp import McpRegistry
from cairn_modules.assessment import AssessmentService, InMemoryCheckpointStore
from cairn_modules.ingestion.run import InMemoryCheckpointStore as IngestionCheckpointStore
from cairn_modules.projects.repository import InMemoryProjectRepository
from cairn_modules.transformation.runs import FakeTransformationRunRepository

from cairn_mcp_gateway.design_server import (
    TOOL_GENERATE_ROADMAP,
    TOOL_GENERATE_TARGET_MODEL,
    TOOL_GET_PATTERN,
    TOOL_GET_TARGET_MODEL,
    TOOL_LIST_PATTERNS,
    build_design_server,
)
from cairn_mcp_gateway.estate_server import (
    TOOL_GET_DEPENDENCIES,
    TOOL_GET_WORKLOAD,
    TOOL_LIST_RESOURCES,
    TOOL_LIST_WORKLOADS,
    build_estate_server,
)
from cairn_mcp_gateway.finops_server import (
    TOOL_GET_BASELINE,
    TOOL_GET_TCO,
    TOOL_LIST_PRICE_RELEASES,
    build_finops_server,
)
from cairn_mcp_gateway.ingestion_server import (
    TOOL_ASSESSMENT_COVERAGE_REPORT,
    TOOL_ASSESSMENT_GET_DECISION,
    TOOL_ASSESSMENT_GET_RESULTS,
    TOOL_ASSESSMENT_GET_RUN,
    TOOL_GET_COVERAGE,
    TOOL_GET_RUN,
    TOOL_LIST_RUNS,
    build_ingestion_server,
)
from cairn_mcp_gateway.mappings_server import (
    TOOL_GET_RELEASE,
    TOOL_LIST_RELEASES,
    TOOL_RESOLVE,
    build_mappings_server,
)
from cairn_mcp_gateway.posture_server import TOOL_GET_CONTROL, build_posture_server
from cairn_mcp_gateway.tenancy_server import (
    TOOL_GET_PROJECT,
    TOOL_LIST_PROJECT_MEMBERS,
    build_tenancy_server,
)
from cairn_mcp_gateway.transformation_server import (
    TOOL_GET_DIFF,
    TOOL_GET_MANIFEST,
    TOOL_LIST_SOURCE_FILES,
    TOOL_RUN,
    TOOL_VALIDATE,
    build_transformation_server,
)
from cairn_mcp_gateway.transformation_server import TOOL_GET_RUN as TOOL_TRANSFORMATION_GET_RUN

#: Scope required to call each registered tool, by tool name. A control
#: catalogue entry is read-only but still compliance-sensitive content,
#: so this unit requires at least AUDITOR (the lowest role R0's taxonomy
#: grants read access to control/compliance data under) rather than
#: leaving it open to any authenticated VIEWER -- a judgement call, not
#: a fact handed down by ADR-011, which only says the gateway "handles
#: auth, per-tenant authorization".
#:
#: R6-08 (889/estate+mappings): both new servers' tools follow design
#: §4.1's own table exactly -- every one of them is VIEWER.
#: R6-09 (892/ingestion, folding in the four tools design originally
#: proposed as a ninth "assessment" server): VIEWER again, same table.
#: R6-10 (894/finops+tenancy): finops.* is VIEWER, same table;
#: tenancy.list_project_members is TENANT_ADMIN, per design §4.1's own
#: table and this unit's acceptance criterion.
#: R6-11 (895/design+transformation, folding planning.generate_roadmap
#: onto the design server): design.*/transformation.* reads are
#: VIEWER; the four PROPOSE tools need the role their own capability
#: implies -- ARCHITECT for design.generate_target_model/planning.
#: generate_roadmap, ENGINEER for transformation.run/validate -- per
#: design §4.1's own table.
REQUIRED_ROLES: dict[str, Role] = {
    TOOL_GET_CONTROL: Role.AUDITOR,
    TOOL_LIST_WORKLOADS: Role.VIEWER,
    TOOL_GET_WORKLOAD: Role.VIEWER,
    TOOL_LIST_RESOURCES: Role.VIEWER,
    TOOL_GET_DEPENDENCIES: Role.VIEWER,
    TOOL_RESOLVE: Role.VIEWER,
    TOOL_GET_RELEASE: Role.VIEWER,
    TOOL_LIST_RELEASES: Role.VIEWER,
    TOOL_GET_RUN: Role.VIEWER,
    TOOL_LIST_RUNS: Role.VIEWER,
    TOOL_GET_COVERAGE: Role.VIEWER,
    TOOL_ASSESSMENT_GET_RUN: Role.VIEWER,
    TOOL_ASSESSMENT_GET_RESULTS: Role.VIEWER,
    TOOL_ASSESSMENT_COVERAGE_REPORT: Role.VIEWER,
    TOOL_ASSESSMENT_GET_DECISION: Role.VIEWER,
    TOOL_GET_BASELINE: Role.VIEWER,
    TOOL_GET_TCO: Role.VIEWER,
    TOOL_LIST_PRICE_RELEASES: Role.VIEWER,
    TOOL_GET_PROJECT: Role.VIEWER,
    TOOL_LIST_PROJECT_MEMBERS: Role.TENANT_ADMIN,
    TOOL_LIST_PATTERNS: Role.VIEWER,
    TOOL_GET_PATTERN: Role.VIEWER,
    TOOL_GET_TARGET_MODEL: Role.VIEWER,
    TOOL_GENERATE_TARGET_MODEL: Role.ARCHITECT,
    TOOL_GENERATE_ROADMAP: Role.ARCHITECT,
    TOOL_LIST_SOURCE_FILES: Role.VIEWER,
    TOOL_TRANSFORMATION_GET_RUN: Role.VIEWER,
    TOOL_GET_MANIFEST: Role.VIEWER,
    TOOL_GET_DIFF: Role.VIEWER,
    TOOL_RUN: Role.ENGINEER,
    TOOL_VALIDATE: Role.ENGINEER,
}


def build_default_registry() -> McpRegistry:
    """Build this unit's reference registry: posture (R5-04a), estate,
    mappings (R6-08), ingestion (R6-09), finops and tenancy (R6-10),
    design and transformation (R6-11). ``estate``, ``ingestion`` and
    ``finops`` share one fresh, empty, in-memory ``AssessmentService``;
    ``transformation`` is backed by a fresh ``FakeTransformationPort``
    with no fixtures registered and an empty source-file scope -- this
    function is the internal reference wiring R6 units build on, not
    the eventual production composition root (``apps/worker``/
    ``apps/api`` construct their own real adapters; a later unit binds
    this registry to those instead of fresh/fake ones).
    """
    registry = McpRegistry()
    assessment_service = AssessmentService(
        checkpoint_store=InMemoryCheckpointStore(), outbox=InMemoryOutboxStore()
    )
    registry.register(build_posture_server())
    registry.register(build_estate_server(assessment_service))
    registry.register(build_mappings_server())
    registry.register(build_ingestion_server(IngestionCheckpointStore(), assessment_service))
    registry.register(build_finops_server(assessment_service))
    registry.register(build_tenancy_server(InMemoryProjectRepository()))
    registry.register(build_design_server())
    registry.register(
        build_transformation_server(
            FakeTransformationPort(), FakeTransformationRunRepository(), source_files=()
        )
    )
    return registry


__all__ = ["REQUIRED_ROLES", "build_default_registry"]
