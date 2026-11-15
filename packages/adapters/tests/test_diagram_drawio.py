"""R2-05: smoke tests for the real Draw.io/mxGraph XML emitter.

Deliberately does not pin exact XML bytes (brittle) -- only that the
output is well-formed XML, references every shape by its real
resource-backed id, and is a pure/deterministic function of the
structured ``DiagramModel``. The acceptance-level tests (marker rule,
no-invented-shapes, reproducibility) live in ``packages/modules/tests/
test_diagram_compiler.py`` against the fake adapter, per this story's
own "never assert on the real emitter's exact bytes" instruction.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from cairn_adapters.diagram_drawio import DrawioXmlDiagramRenderer
from cairn_modules.design.diagram import DiagramModel, DiagramShape, DiagramShapeMarker


def _model(**overrides: object) -> DiagramModel:
    payload: dict[str, object] = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "design_id": "design-1",
        "revision_id": "revision-1",
        "revision_number": 1,
        "pattern_id": "web-app",
        "target_provider": "gcp",
        "content_hash": "abc123",
        "shapes": (
            DiagramShape(
                shape_id="res-1",
                source_provider="aws",
                source_service="s3",
                target_provider="gcp",
                target_service="cloud-storage",
                marker=DiagramShapeMarker.EXACT,
                detail=None,
            ),
            DiagramShape(
                shape_id="res-2",
                source_provider="aws",
                source_service="route53",
                target_provider="",
                target_service=None,
                marker=DiagramShapeMarker.UNRESOLVED,
                detail="no mapping entry",
            ),
        ),
    }
    payload.update(overrides)
    return DiagramModel(**payload)


def test_renders_well_formed_xml_referencing_every_shape() -> None:
    renderer = DrawioXmlDiagramRenderer()
    xml_text = renderer.render(_model())

    # Strip the leading declaration for ElementTree, which rejects a
    # second declaration-looking prolog in some stdlib versions when fed
    # through certain wrappers; parsing the full string directly works.
    root = ET.fromstring(xml_text)
    assert root.tag == "mxfile"
    cell_ids = {cell.get("id") for cell in root.iter("mxCell")}
    assert "shape-res-1" in cell_ids
    assert "shape-res-2" in cell_ids


def test_each_marker_gets_its_own_distinct_style() -> None:
    renderer = DrawioXmlDiagramRenderer()
    xml_text = renderer.render(_model())
    root = ET.fromstring(xml_text)
    styles = {cell.get("id"): cell.get("style") for cell in root.iter("mxCell") if cell.get("style")}
    assert styles["shape-res-1"] != styles["shape-res-2"]


def test_rendering_is_a_pure_function_of_the_model() -> None:
    renderer = DrawioXmlDiagramRenderer()
    model = _model()
    assert renderer.render(model) == renderer.render(model)


def test_no_invented_shapes_in_the_rendered_xml() -> None:
    model = _model()
    renderer = DrawioXmlDiagramRenderer()
    xml_text = renderer.render(model)
    root = ET.fromstring(xml_text)
    rendered_shape_cells = [cell for cell in root.iter("mxCell") if cell.get("id", "").startswith("shape-")]
    assert len(rendered_shape_cells) == len(model.shapes)
