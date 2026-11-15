"""R2-05: the fake/deterministic-test ``DiagramRendererPort`` adapter.

Spec §5.4: ``DiagramRendererPort | design | drawio emitter, fake``. This
is the "fake" half. Tests assert on the structured pre-render
``DiagramModel`` the compiler built (``cairn_modules.design.diagram``),
never on this adapter's output bytes or the real emitter's XML bytes --
both would be brittle. This adapter exists so ``compile_diagram`` has a
renderer to call in tests without depending on XML formatting at all;
its output is a plain, deterministic canonical-JSON projection of the
model, useful only for asserting "the renderer was in fact called with
this exact model" and for the reproducibility test (same model -> byte-
identical rendered content).
"""

from __future__ import annotations

import json

from cairn_modules.design.diagram import DiagramModel, DiagramShape


def _shape_to_jsonable(shape: DiagramShape) -> dict[str, object]:
    return {
        "shape_id": shape.shape_id,
        "source_provider": shape.source_provider,
        "source_service": shape.source_service,
        "target_provider": shape.target_provider,
        "target_service": shape.target_service,
        "marker": shape.marker.value,
        "detail": shape.detail,
    }


class FakeDiagramRenderer:
    """Deterministic ``DiagramRendererPort`` for tests: records every
    ``DiagramModel`` it was asked to render (so a test can assert what
    the compiler actually handed the port), and returns a stable
    canonical-JSON string for it -- the same model always renders to
    the identical string."""

    def __init__(self) -> None:
        self.rendered: list[DiagramModel] = []

    def render(self, diagram: DiagramModel) -> str:
        self.rendered.append(diagram)
        payload = {
            "design_id": diagram.design_id,
            "revision_id": diagram.revision_id,
            "revision_number": diagram.revision_number,
            "pattern_id": diagram.pattern_id,
            "target_provider": diagram.target_provider,
            "content_hash": diagram.content_hash,
            "shapes": [_shape_to_jsonable(shape) for shape in diagram.shapes],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = ["FakeDiagramRenderer"]
