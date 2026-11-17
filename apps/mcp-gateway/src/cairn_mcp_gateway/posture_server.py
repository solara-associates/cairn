"""R5-04a's proof registration: the posture module's existing read-only
control-catalogue lookup (``cairn_modules.posture.InMemoryControlCatalogue``),
exposed as one real MCP tool so the gateway's registry resolves to
something real, not a fixture.

``posture.get_control`` is read-only (Class A / ``READ_ONLY`` in R0-19's
classification, see ``cairn_kernel.classification.matrix``): it only
looks up a control already published in the seeded catalogue release
(``controls/gcp-cis-seed.yaml``, the same seed R1's own
``test_control_catalogue.py`` loads), nothing is mutated.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cairn_kernel.errors import ValidationError
from cairn_kits.mcp import BoundedContextServer
from cairn_modules.posture import InMemoryControlCatalogue

#: apps/mcp-gateway/src/cairn_mcp_gateway/posture_server.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SEED_PATH = _REPO_ROOT / "controls" / "gcp-cis-seed.yaml"

POSTURE_CONTEXT_ID = "posture"
TOOL_GET_CONTROL = "posture.get_control"


def build_posture_server(seed_path: Path | str = DEFAULT_SEED_PATH) -> BoundedContextServer:
    """Build the posture bounded-context's MCP server: one tool,
    ``posture.get_control``, backed by a catalogue loaded from
    ``seed_path``.
    """
    catalogue = InMemoryControlCatalogue()
    catalogue.load(seed_path)

    def handle(tool_name: str, arguments: Mapping[str, object]) -> object:
        if tool_name != TOOL_GET_CONTROL:
            raise ValidationError(f"posture MCP server does not expose tool {tool_name!r}")
        version = arguments.get("version")
        control_id = arguments.get("control_id")
        if not isinstance(version, str) or not version:
            raise ValidationError("posture.get_control requires a 'version' argument")
        if not isinstance(control_id, str) or not control_id:
            raise ValidationError("posture.get_control requires a 'control_id' argument")
        return catalogue.get_control(version, control_id)

    return BoundedContextServer(
        context_id=POSTURE_CONTEXT_ID,
        name="posture",
        tools=(TOOL_GET_CONTROL,),
        handle=handle,
    )


__all__ = [
    "DEFAULT_SEED_PATH",
    "POSTURE_CONTEXT_ID",
    "TOOL_GET_CONTROL",
    "build_posture_server",
]
