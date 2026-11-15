"""R2-05: ``DiagramRendererPort`` adapters (spec §5.4) -- a real Draw.io/
mxGraph XML emitter and a deterministic fake for tests."""

from cairn_adapters.diagram_drawio.drawio import DrawioXmlDiagramRenderer
from cairn_adapters.diagram_drawio.fake import FakeDiagramRenderer

__all__ = ["DrawioXmlDiagramRenderer", "FakeDiagramRenderer"]
