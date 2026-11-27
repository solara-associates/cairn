"""R6-11: the ``design`` bounded context's MCP server (ADR-011, design
§4.1). Five tools: three ``READ`` over the real pattern catalogue
(``patterns/*.yaml``, loaded ``PUBLISHED`` at construction, the same
seed-once shape ``mappings_server.py``/``posture_server.py`` already
use) and a cache of what this server's own ``PROPOSE`` tool has
generated; two ``PROPOSE`` tools -- ``design.generate_target_model``
and ``planning.generate_roadmap`` -- folded onto this one server
rather than a separate ``planning`` context, matching the run sheet's
own two test files for this unit (``test_design_server.py``,
``test_transformation_server.py``; no third).

**No persistence at this layer, by design.** ``generate_target_model``/
``generate_roadmap`` are pure, principal-free generators
(``cairn_modules.design.target_model``/``cairn_modules.planning.
roadmap``) -- neither writes a row anywhere. A candidate this server's
``PROPOSE`` tool produces is cached in-process, keyed by the id the
caller supplied, purely so ``design.get_target_model`` can read back
what the same server instance just generated; turning a candidate into
an immutable, approvable revision row is the design-proposer agent's
own job (Wave 4, R6-13), not this tool's -- the same split design §3.2
describes ("the agent chooses the pattern and the parameters... the
generators do the generating").
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from cairn_contracts.estate import Resource, Workload
from cairn_contracts.mapping import ReleaseStatus
from cairn_contracts.mapping.pattern import PatternReleaseStatus
from cairn_kernel.errors import NotFoundError, ValidationError
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.design.patterns import load_pattern_catalogue
from cairn_modules.design.target_model import TargetModel, generate_target_model
from cairn_modules.mappings import load_mapping_release
from cairn_modules.planning.roadmap import MigrationRoadmap, generate_roadmap
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

#: apps/mcp-gateway/src/cairn_mcp_gateway/design_server.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PATTERNS_DIR = _REPO_ROOT / "patterns"
DEFAULT_MAPPING_SEED_PATH = _REPO_ROOT / "mappings" / "service-map.yaml"
PATTERN_CATALOGUE_VERSION = "2026.11.1"

DESIGN_CONTEXT_ID = "design"

TOOL_LIST_PATTERNS = "design.list_patterns"
TOOL_GET_PATTERN = "design.get_pattern"
TOOL_GET_TARGET_MODEL = "design.get_target_model"
TOOL_GENERATE_TARGET_MODEL = "design.generate_target_model"
TOOL_GENERATE_ROADMAP = "planning.generate_roadmap"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PatternArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str


class _TargetModelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: str


class _GenerateTargetModelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    design_id: str
    pattern_id: str
    mapping_version: str
    target_provider: str
    resources: list[dict[str, Any]] = []
    parameters: dict[str, Any] = {}


class _GenerateRoadmapArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    plan_id: str
    design_id: str
    workloads: list[dict[str, Any]] = []


def _parse(model_cls: type[_ArgsT], arguments: Mapping[str, object]) -> _ArgsT:
    try:
        return model_cls.model_validate(dict(arguments))
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def build_design_server(
    *,
    patterns_dir: Path | str = DEFAULT_PATTERNS_DIR,
    mapping_seed_path: Path | str = DEFAULT_MAPPING_SEED_PATH,
) -> BoundedContextServer:
    """Build the design bounded-context's MCP server. The pattern
    catalogue and the mapping release are both loaded once, at
    construction, from the real repo-root seeds -- the same shape every
    other read-heavy server in this wave already uses.
    """

    catalogue = load_pattern_catalogue(
        patterns_dir,
        version=PATTERN_CATALOGUE_VERSION,
        released_at=datetime(2026, 11, 15, tzinfo=UTC),
        status=PatternReleaseStatus.PUBLISHED,
    )
    mapping_release = load_mapping_release(mapping_seed_path).model_copy(
        update={"status": ReleaseStatus.PUBLISHED}
    )

    target_models: dict[str, TargetModel] = {}
    roadmaps: dict[str, MigrationRoadmap] = {}

    def _pattern(pattern_id: str) -> Any:
        for pattern in catalogue.patterns:
            if pattern.id == pattern_id:
                return pattern
        raise NotFoundError(f"pattern {pattern_id} not found in catalogue {catalogue.version}")

    def handle(tool_name: str, arguments: Mapping[str, object]) -> object:
        if tool_name == TOOL_LIST_PATTERNS:
            _parse(_NoArgs, arguments)
            return catalogue.patterns

        if tool_name == TOOL_GET_PATTERN:
            args = _parse(_PatternArgs, arguments)
            return _pattern(args.pattern_id)

        if tool_name == TOOL_GET_TARGET_MODEL:
            args = _parse(_TargetModelArgs, arguments)
            try:
                return target_models[args.design_id]
            except KeyError:
                raise NotFoundError(
                    f"no target model generated yet for design {args.design_id}"
                ) from None

        if tool_name == TOOL_GENERATE_TARGET_MODEL:
            args = _parse(_GenerateTargetModelArgs, arguments)
            pattern = _pattern(args.pattern_id)
            resources = tuple(Resource.model_validate(r) for r in args.resources)
            target_model = generate_target_model(
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                design_id=args.design_id,
                estate=resources,
                pattern=pattern,
                pattern_catalogue_version=catalogue.version,
                mapping_release=mapping_release,
                target_provider=args.target_provider,
                parameters=args.parameters,
            )
            target_models[args.design_id] = target_model
            return target_model

        if tool_name == TOOL_GENERATE_ROADMAP:
            args = _parse(_GenerateRoadmapArgs, arguments)
            workloads = tuple(Workload.model_validate(w) for w in args.workloads)
            roadmap = generate_roadmap(
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                plan_id=args.plan_id,
                workloads=workloads,
                target_model=target_models.get(args.design_id),
            )
            roadmaps[args.plan_id] = roadmap
            return roadmap

        raise ValidationError(f"design MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=DESIGN_CONTEXT_ID,
        name="design",
        tools=(
            TOOL_LIST_PATTERNS,
            TOOL_GET_PATTERN,
            TOOL_GET_TARGET_MODEL,
            TOOL_GENERATE_TARGET_MODEL,
            TOOL_GENERATE_ROADMAP,
        ),
        capabilities={
            TOOL_LIST_PATTERNS: ToolCapability.READ,
            TOOL_GET_PATTERN: ToolCapability.READ,
            TOOL_GET_TARGET_MODEL: ToolCapability.READ,
            TOOL_GENERATE_TARGET_MODEL: ToolCapability.PROPOSE,
            TOOL_GENERATE_ROADMAP: ToolCapability.PROPOSE,
        },
        handle=handle,
    )


__all__ = [
    "DEFAULT_MAPPING_SEED_PATH",
    "DEFAULT_PATTERNS_DIR",
    "DESIGN_CONTEXT_ID",
    "PATTERN_CATALOGUE_VERSION",
    "TOOL_GENERATE_ROADMAP",
    "TOOL_GENERATE_TARGET_MODEL",
    "TOOL_GET_PATTERN",
    "TOOL_GET_TARGET_MODEL",
    "TOOL_LIST_PATTERNS",
    "build_design_server",
]
