"""R6-08: the ``mappings`` bounded context's MCP server (ADR-011,
design §4.1). Three ``READ`` tools over the published mapping release
-- ``cairn_modules.mappings.resolver.resolve_mapping`` and the release
content itself, never SQL or a provider SDK directly.

This server reads a published release only: ADR-004's propose/review/
publish workflow (``cairn_modules.mappings.MappingService``) is a
separate, Principal-scoped, outbox-publishing concern this server does
not expose. ``design.md`` §4.2 already lists "publishes a mapping
release" among what no MCP tool does -- this server loads the real
seed (``mappings/service-map.yaml``) as an already-``PUBLISHED``
release once, at construction, the same shape
``posture_server.py`` loads its control catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import MappingUnavailableError, ValidationError
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.mappings import load_mapping_release, resolve_mapping
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

#: apps/mcp-gateway/src/cairn_mcp_gateway/mappings_server.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SEED_PATH = _REPO_ROOT / "mappings" / "service-map.yaml"

MAPPINGS_CONTEXT_ID = "mappings"

TOOL_RESOLVE = "mappings.resolve"
TOOL_GET_RELEASE = "mappings.get_release"
TOOL_LIST_RELEASES = "mappings.list_releases"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _ResolveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_version: str
    source_provider: str
    source_service: str
    target_provider: str
    region: str | None = None


class _ReleaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _parse(model_cls: type[_ArgsT], arguments: Mapping[str, object]) -> _ArgsT:
    try:
        return model_cls.model_validate(dict(arguments))
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def build_mappings_server(seed_path: Path | str = DEFAULT_SEED_PATH) -> BoundedContextServer:
    """Build the mappings bounded-context's MCP server, loading
    ``seed_path`` once as an already-published release.

    The committed seed file's own top-level ``status`` is ``DRAFT``
    (it has never been through ADR-004's review workflow -- see
    ``cairn_modules.mappings.seed``'s own callers), so this server
    publishes it directly at load time rather than claiming a review
    history it does not have: a server exposing only read tools has no
    use for one anyway.
    """

    raw = load_mapping_release(seed_path)
    published = raw.model_copy(update={"status": ReleaseStatus.PUBLISHED})
    releases: dict[str, MappingRelease] = {published.version: published}

    def handle(tool_name: str, arguments: Mapping[str, object]) -> object:
        if tool_name == TOOL_RESOLVE:
            args = _parse(_ResolveArgs, arguments)
            release = releases.get(args.mapping_version)
            if release is None:
                raise MappingUnavailableError(
                    f"mapping release {args.mapping_version!r} is not available"
                )
            return resolve_mapping(
                release,
                source_provider=args.source_provider,
                source_service=args.source_service,
                target_provider=args.target_provider,
                region=args.region,
            )

        if tool_name == TOOL_GET_RELEASE:
            args = _parse(_ReleaseArgs, arguments)
            release = releases.get(args.version)
            if release is None:
                raise MappingUnavailableError(f"mapping release {args.version!r} is not available")
            return release

        if tool_name == TOOL_LIST_RELEASES:
            _parse(_NoArgs, arguments)
            return tuple(releases.values())

        raise ValidationError(f"mappings MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=MAPPINGS_CONTEXT_ID,
        name="mappings",
        tools=(TOOL_RESOLVE, TOOL_GET_RELEASE, TOOL_LIST_RELEASES),
        capabilities={
            TOOL_RESOLVE: ToolCapability.READ,
            TOOL_GET_RELEASE: ToolCapability.READ,
            TOOL_LIST_RELEASES: ToolCapability.READ,
        },
        handle=handle,
    )


__all__ = [
    "DEFAULT_SEED_PATH",
    "MAPPINGS_CONTEXT_ID",
    "TOOL_GET_RELEASE",
    "TOOL_LIST_RELEASES",
    "TOOL_RESOLVE",
    "build_mappings_server",
]
