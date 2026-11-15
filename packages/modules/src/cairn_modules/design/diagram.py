"""R2-05: the diagram compiler (spec §16's R2-05 row: "Approximate/
unavailable/unresolved distinct; no invented shapes").

Compiles 703's deterministic ``TargetModel`` (``cairn_modules.design.
target_model``) into a renderable diagram. This module owns exactly two
things:

1. ``DiagramModel`` -- a structured, provider-neutral, pre-render
   projection of the target model. Every ``DiagramShape`` in it has a
   real backing ``TargetResourceEntry``; a resource that could not be
   resolved by 703 is *never* omitted and *never* invented a substitute
   -- it renders as a shape in its own right, carrying a visually
   distinct ``DiagramShapeMarker`` instead of a resolved target service.
2. ``DiagramRendererPort`` -- the hexagonal port (spec §5.4) that turns
   a ``DiagramModel`` into renderable content (Draw.io/mxGraph XML for
   the real adapter, a deterministic canonical string for the fake
   test adapter in ``cairn_adapters.diagram_drawio``). This module
   never imports an adapter (``domain-purity``); it only depends on the
   adapter satisfying this Protocol structurally.

The distinct-marker rule (the concrete, testable rule this story's
acceptance text asks for, spec's "Approximate/unavailable/unresolved
distinct"):

* ``UNRESOLVED`` -- ``TargetResourceEntry.status`` is ``UNRESOLVED``:
  703's resolver could not produce any target mapping at all (no
  catalogue entry, or the matching entry's own equivalence is
  ``UNAVAILABLE``). No ``resolution`` exists for this entry.
* ``APPROXIMATE`` -- the entry resolved, and ``resolution.equivalence``
  is ``Equivalence.APPROXIMATE``: a target exists but is not a like-for-
  like replacement (``resolution.caveat`` explains why).
* ``UNAVAILABLE`` -- the entry resolved, but either
  ``resolution.equivalence`` is ``Equivalence.UNSUPPORTED`` or
  ``resolution.region_supported`` is ``False``: a mapping exists in the
  catalogue, but it is not actually usable for this resource (wrong
  region, or the catalogue itself marks the target as unsupported for
  this source/target pair).
* ``EXACT`` -- everything else: ``resolution.equivalence`` is
  ``Equivalence.EXACT`` and the mapping is supported in the resource's
  region. No marker is drawn.

This rule is evaluated per-entry, grounded entirely in fields 703's
``TargetResourceEntry``/``ResolvedMapping`` already expose -- it never
parses the resolver's free-text reason/caveat strings to recover a
distinction those types don't structurally carry (R-MAP-01: approximate/
unavailable must never be rendered as exact, and must never be
confused with each other by guesswork).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from cairn_contracts.estate import Equivalence
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import Port

from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.target_model import TargetModel, TargetResourceEntry, TargetResourceStatus

#: The ``artifact.kind`` value (spec's data-model table, line ~1133:
#: ``kind text NOT NULL -- DIAGRAM | IAC | REPORT | DIFF | EVIDENCE``)
#: this story's output is persisted/referenced under.
DIAGRAM_ARTEFACT_KIND = "DIAGRAM"


class DiagramShapeMarker(str, Enum):
    """The visually distinct marker drawn for one shape.

    ``EXACT`` means "no marker" -- a plain, resolved shape. The other
    three are the exact three states spec §16's R2-05 row requires to
    be "distinct": each gets its own marker value, never collapsed into
    a single generic "not exact" marker.
    """

    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class DiagramShape:
    """One shape in the diagram, backed by exactly one real
    ``TargetResourceEntry`` -- never a placeholder box for something the
    target model could not resolve (ADR-003; spec's "no invented
    shapes")."""

    shape_id: str
    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    marker: DiagramShapeMarker
    detail: str | None

    def __post_init__(self) -> None:
        if not self.shape_id.strip():
            raise ValidationError("diagram shape id is required")
        if self.marker is DiagramShapeMarker.EXACT and self.target_service is None:
            raise ValidationError("an EXACT shape must carry a resolved target service")
        if self.marker is DiagramShapeMarker.UNRESOLVED and self.target_service is not None:
            raise ValidationError("an UNRESOLVED shape must not carry a target service")


@dataclass(frozen=True, slots=True)
class DiagramModel:
    """The structured, pre-render projection of one target model.

    This is what tests assert against (never the real emitter's exact
    XML bytes, which is brittle and not the contract) -- the same
    pattern this codebase already uses for other renderers (e.g.
    ``cairn_modules.reporting.renderer.AssessmentReport``).
    """

    tenant_id: str
    project_id: str
    design_id: str
    revision_id: str
    revision_number: int
    pattern_id: str
    target_provider: str
    content_hash: str
    shapes: tuple[DiagramShape, ...]

    @property
    def unresolved_shape_ids(self) -> tuple[str, ...]:
        return tuple(
            shape.shape_id
            for shape in self.shapes
            if shape.marker is DiagramShapeMarker.UNRESOLVED
        )


@dataclass(frozen=True, slots=True)
class DiagramArtefact:
    """One compiled diagram, referencing the exact design revision
    (``subject_revision`` row) it was compiled from.

    ``artefact_id`` is a pure function of the revision identity and the
    structured diagram model's content -- not a random id -- so
    compiling the *same* revision twice always yields the identical
    ``artefact_id``/``content_hash``, and compiling a *different*
    revision always yields a visibly different one (this story's
    reproducibility acceptance criterion). ``kind`` is the
    ``artifact.kind`` value this artefact would be persisted/referenced
    under (spec's data-model table)."""

    artefact_id: str
    kind: str
    tenant_id: str
    project_id: str
    design_id: str
    revision_id: str
    revision_number: int
    content_hash: str
    model: DiagramModel
    rendered_content: str

    @property
    def unresolved_shape_ids(self) -> tuple[str, ...]:
        return self.model.unresolved_shape_ids


class DiagramRendererPort(Port, Protocol):
    """spec §5.4: ``DiagramRendererPort | design | drawio emitter, fake``.

    Turns a ``DiagramModel`` into renderable content. Implementations
    live in ``cairn_adapters.diagram_drawio`` (a real Draw.io/mxGraph XML
    emitter, and a deterministic fake for tests) -- this module never
    imports them, it only depends on this Protocol being satisfied
    structurally."""

    def render(self, diagram: DiagramModel) -> str:
        """Render ``diagram`` to its target representation (Draw.io XML
        for the real adapter). Must be a pure function of ``diagram`` --
        no timestamps, no randomness, no non-deterministic ordering."""


def _marker_for(entry: TargetResourceEntry) -> DiagramShapeMarker:
    if entry.status is TargetResourceStatus.UNRESOLVED:
        return DiagramShapeMarker.UNRESOLVED
    resolution = entry.resolution
    assert resolution is not None  # RESOLVED entries always carry one (target_model's own invariant)
    if resolution.equivalence is Equivalence.APPROXIMATE:
        return DiagramShapeMarker.APPROXIMATE
    if resolution.equivalence is Equivalence.UNSUPPORTED or not resolution.region_supported:
        return DiagramShapeMarker.UNAVAILABLE
    return DiagramShapeMarker.EXACT


def _detail_for(entry: TargetResourceEntry, marker: DiagramShapeMarker) -> str | None:
    if marker is DiagramShapeMarker.UNRESOLVED:
        return entry.reason
    resolution = entry.resolution
    assert resolution is not None
    if (
        marker is DiagramShapeMarker.UNAVAILABLE
        and resolution.equivalence is not Equivalence.UNSUPPORTED
        and not resolution.region_supported
    ):
        return resolution.caveat or "mapping is not supported in this resource's region"
    return resolution.caveat


def _shape_for(entry: TargetResourceEntry) -> DiagramShape:
    marker = _marker_for(entry)
    target_service: str | None = None
    target_provider = ""
    if entry.resolution is not None:
        target_provider = entry.resolution.target_provider
        if marker is not DiagramShapeMarker.UNRESOLVED:
            target_service = entry.resolution.target_service
    return DiagramShape(
        shape_id=entry.resource_id,
        source_provider=entry.source_provider,
        source_service=entry.source_service,
        target_provider=target_provider,
        target_service=target_service,
        marker=marker,
        detail=_detail_for(entry, marker),
    )


def build_diagram_model(*, target_model: TargetModel, revision: RevisionRecord) -> DiagramModel:
    """Project ``target_model`` into a ``DiagramModel``, referencing
    ``revision`` (703's ``subject_revision`` row this target model was
    recorded under).

    Every one of ``target_model.resources`` becomes exactly one
    ``DiagramShape`` -- same count, same order (already sorted by
    ``resource_id`` by ``generate_target_model``) -- never more, never
    fewer: this is the "no invented shapes" guarantee made concrete.
    """
    if revision.tenant_id != target_model.tenant_id or revision.project_id != target_model.project_id:
        raise ValidationError("revision does not belong to this target model's tenant/project")
    if revision.content_hash != target_model.content_hash:
        raise ValidationError(
            "revision.content_hash does not match target_model.content_hash -- "
            "the revision does not record this exact target model"
        )

    shapes = tuple(_shape_for(entry) for entry in target_model.resources)
    return DiagramModel(
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        design_id=target_model.design_id,
        revision_id=revision.revision_id,
        revision_number=revision.revision_number,
        pattern_id=target_model.pattern_id,
        target_provider=target_model.target_provider,
        content_hash=target_model.content_hash,
        shapes=shapes,
    )


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


def _diagram_content_hash(model: DiagramModel) -> str:
    """A stable fingerprint of the diagram's own rendered-agnostic
    content (pattern, provider, target-model content hash and every
    shape) -- independent of which ``DiagramRendererPort`` rendered it,
    so two renderers compiling the same target model agree on this
    value even though their ``rendered_content`` bytes differ."""
    payload = {
        "design_id": model.design_id,
        "pattern_id": model.pattern_id,
        "target_provider": model.target_provider,
        "target_model_content_hash": model.content_hash,
        "shapes": [_shape_to_jsonable(shape) for shape in model.shapes],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _diagram_artefact_id(model: DiagramModel, content_hash: str) -> str:
    """Deterministic artefact id: a pure hash of the exact revision this
    diagram was compiled from, plus its content hash. Same revision
    (same ``revision_id``/``revision_number``) compiled from the same
    content -> the identical id, every time; a different revision ->
    a visibly different id, every time -- this is what makes a later
    regeneration of the same revision reproducible, and a different
    revision's diagram artefact distinguishable from it."""
    payload = {
        "tenant_id": model.tenant_id,
        "project_id": model.project_id,
        "design_id": model.design_id,
        "revision_id": model.revision_id,
        "revision_number": model.revision_number,
        "content_hash": content_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_diagram(
    *,
    target_model: TargetModel,
    revision: RevisionRecord,
    renderer: DiagramRendererPort,
) -> DiagramArtefact:
    """Compile ``target_model`` (704's own revision it was recorded
    under, ``revision``) into a ``DiagramArtefact`` via ``renderer``.

    Calling this twice with the same ``target_model``/``revision`` (same
    content, same revision identity) always yields a ``DiagramArtefact``
    with an identical ``artefact_id`` and ``content_hash`` -- regardless
    of which ``DiagramRendererPort`` implementation is used, since both
    are derived from the structured ``DiagramModel``, not from the
    renderer's own output.
    """
    model = build_diagram_model(target_model=target_model, revision=revision)
    rendered_content = renderer.render(model)
    content_hash = _diagram_content_hash(model)
    artefact_id = _diagram_artefact_id(model, content_hash)
    return DiagramArtefact(
        artefact_id=artefact_id,
        kind=DIAGRAM_ARTEFACT_KIND,
        tenant_id=model.tenant_id,
        project_id=model.project_id,
        design_id=model.design_id,
        revision_id=model.revision_id,
        revision_number=model.revision_number,
        content_hash=content_hash,
        model=model,
        rendered_content=rendered_content,
    )


__all__ = [
    "DIAGRAM_ARTEFACT_KIND",
    "DiagramArtefact",
    "DiagramModel",
    "DiagramRendererPort",
    "DiagramShape",
    "DiagramShapeMarker",
    "build_diagram_model",
    "compile_diagram",
]
