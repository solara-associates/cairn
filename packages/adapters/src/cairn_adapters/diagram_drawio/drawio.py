"""R2-05: the real ``DiagramRendererPort`` adapter -- a Draw.io/mxGraph
compatible XML emitter.

Spec §5.4: ``DiagramRendererPort | design | drawio emitter, fake``. This
is the "drawio emitter" half; ``cairn_adapters.diagram_drawio.fake`` is
the "fake" half.

The emitter is a pure function of ``cairn_modules.design.diagram.
DiagramModel`` -- no timestamps, no randomness, no non-deterministic
ordering (the model's shapes are already sorted by ``shape_id`` by the
compiler). Two calls with the same model always produce byte-identical
XML. It never invents a shape and never upgrades a marked shape's style
to look like an exact match -- each ``DiagramShapeMarker`` maps to its
own fixed, named mxGraph style string, applied consistently.

This module never asserts anything about its own output in tests
(brittle); tests assert on the structured ``DiagramModel`` instead. This
module is exercised directly only by a light well-formedness smoke test
in ``packages/adapters/tests``.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from cairn_modules.design.diagram import DiagramModel, DiagramShape, DiagramShapeMarker

#: One fixed mxGraph style per marker -- the "concrete, testable rule"
#: this story's acceptance text asks for, made visual. Never "render
#: differently" left vague: each state gets exactly one named style.
_STYLE_BY_MARKER: dict[DiagramShapeMarker, str] = {
    DiagramShapeMarker.EXACT: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
    ),
    DiagramShapeMarker.APPROXIMATE: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;dashed=1;"
    ),
    DiagramShapeMarker.UNAVAILABLE: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;dashed=1;"
    ),
    DiagramShapeMarker.UNRESOLVED: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;"
        "dashed=1;fontColor=#990000;"
    ),
}

#: A short, visible label suffix per marker -- so the marker reads even
#: in a plain-text export of the label, not only in the fill colour.
_LABEL_SUFFIX_BY_MARKER: dict[DiagramShapeMarker, str] = {
    DiagramShapeMarker.EXACT: "",
    DiagramShapeMarker.APPROXIMATE: " [APPROXIMATE]",
    DiagramShapeMarker.UNAVAILABLE: " [UNAVAILABLE]",
    DiagramShapeMarker.UNRESOLVED: " [UNRESOLVED]",
}

_SHAPE_WIDTH = 160
_SHAPE_HEIGHT = 80
_COLUMN_GAP = 40
_ROW_GAP = 40
_COLUMNS = 4


def _label_for(shape: DiagramShape) -> str:
    target = shape.target_service or "no target mapping"
    base = f"{shape.source_provider}:{shape.source_service} -> {target}"
    return base + _LABEL_SUFFIX_BY_MARKER[shape.marker]


def _geometry_for(index: int) -> tuple[int, int]:
    column = index % _COLUMNS
    row = index // _COLUMNS
    x = column * (_SHAPE_WIDTH + _COLUMN_GAP)
    y = row * (_SHAPE_HEIGHT + _ROW_GAP)
    return x, y


def _cell_id(shape: DiagramShape) -> str:
    # mxGraph cell ids must be valid XML attribute values; the shape_id
    # is the real target-model resource_id, used verbatim (escaped) so
    # the diagram's own ids trace directly back to the estate.
    return f"shape-{shape.shape_id}"


def _render_cell(shape: DiagramShape, index: int) -> str:
    x, y = _geometry_for(index)
    style = _STYLE_BY_MARKER[shape.marker]
    label = escape(_label_for(shape))
    cell_id = quoteattr(_cell_id(shape))
    style_attr = quoteattr(style)
    return (
        f'<mxCell id={cell_id} value="{label}" style={style_attr} '
        f'vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{_SHAPE_WIDTH}" height="{_SHAPE_HEIGHT}" as="geometry" />'
        f"</mxCell>"
    )


class DrawioXmlDiagramRenderer:
    """The real ``DiagramRendererPort`` adapter: Draw.io/mxGraph XML."""

    def render(self, diagram: DiagramModel) -> str:
        cells = "".join(
            _render_cell(shape, index) for index, shape in enumerate(diagram.shapes)
        )
        diagram_name = escape(f"{diagram.design_id}-r{diagram.revision_number}")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<mxfile host="cairn"><diagram id={quoteattr(diagram.revision_id)} name="{diagram_name}">'
            '<mxGraphModel><root>'
            '<mxCell id="0" />'
            '<mxCell id="1" parent="0" />'
            f"{cells}"
            "</root></mxGraphModel></diagram></mxfile>"
        )


__all__ = ["DrawioXmlDiagramRenderer"]
