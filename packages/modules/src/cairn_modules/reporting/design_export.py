"""R2-08: machine-readable (JSON) design/plan export bundle (spec §16's
R2-08 row: "Machine-readable and human-readable exports").

Bundles four already-generated artefacts that share one provenance chain
-- 703's design revision (``TargetModel`` + its ``subject_revision``
row), 704's compiled diagram, 705/706's plan revision (``MigrationRoadmap``
+ its own ``subject_revision`` row) and 706's IaC plan preview -- into one
``DesignExportBundle``.

This module invents no new content: every field it exposes is read
straight off the objects 703-706 already produce
(``cairn_modules.design.target_model``, ``cairn_modules.design.diagram``,
``cairn_modules.planning.roadmap``, ``cairn_modules.planning.iac_plan``).
Its only real job -- the thing R2-10 (708) will check -- is naming the
version stamp consistently: ``pattern_catalogue_version``,
``mapping_release_version`` and ``target_provider`` appear, spelled
identically, on every one of the four sections below, even though the
diagram and plan/roadmap objects do not carry those fields natively
(``DiagramArtefact``/``MigrationRoadmap`` only record a content hash and,
for the roadmap, wave/workload counts). This module is the one place that
projects all four onto the one ``TargetModel`` that produced them -- the
same ``target_model`` 704's diagram and 706's IaC preview were compiled
from, and the same one 705's roadmap generation was (optionally) given --
rather than inventing four different spellings across four call sites.

Every cross-reference between the four inputs is verified before the
bundle is built, never assumed: a diagram/IaC artefact that was not
actually compiled from this exact ``design_revision``, or a plan revision
that does not actually record this exact ``roadmap``, is rejected with
``ValidationError`` rather than silently bundled as if it matched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn_kernel.errors import ValidationError

from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.diagram import DiagramArtefact
from cairn_modules.design.target_model import TargetModel
from cairn_modules.planning.iac_plan import IaCPlanArtefact
from cairn_modules.planning.roadmap import MigrationRoadmap


@dataclass(frozen=True, slots=True)
class VersionStamp:
    """The exact three fields, spelled identically, carried by every
    section of a ``DesignExportBundle`` -- the consistency contract
    R2-10 (708) checks by field name, not by section-specific spelling."""

    pattern_catalogue_version: str
    mapping_release_version: str
    target_provider: str


@dataclass(frozen=True, slots=True)
class DesignRevisionSection:
    design_id: str
    revision_id: str
    revision_number: int
    content_hash: str
    pattern_id: str
    parameters: tuple[tuple[str, Any], ...]
    versions: VersionStamp


@dataclass(frozen=True, slots=True)
class DiagramSection:
    artefact_id: str
    kind: str
    revision_id: str
    revision_number: int
    content_hash: str
    shape_count: int
    unresolved_shape_ids: tuple[str, ...]
    versions: VersionStamp


@dataclass(frozen=True, slots=True)
class PlanSection:
    plan_id: str
    revision_id: str
    revision_number: int
    content_hash: str
    wave_count: int
    workload_count: int
    blocked_workload_ids: tuple[str, ...]
    versions: VersionStamp


@dataclass(frozen=True, slots=True)
class IacSection:
    artefact_id: str
    kind: str
    revision_id: str
    revision_number: int
    content_hash: str
    gap_resource_ids: tuple[str, ...]
    versions: VersionStamp


@dataclass(frozen=True, slots=True)
class DesignExportBundle:
    """The full R2-08 machine-readable export: one design's target model,
    compiled diagram, migration plan and IaC preview, as a single JSON-
    shaped document."""

    tenant_id: str
    project_id: str
    design_id: str
    design: DesignRevisionSection
    diagram: DiagramSection
    plan: PlanSection
    iac: IacSection

    @property
    def version_stamps_consistent(self) -> bool:
        """``True`` iff every section's ``versions`` carries the exact
        same ``(pattern_catalogue_version, mapping_release_version,
        target_provider)`` triple -- the round-trip property this
        story's tests prove, and the exact check 708 (R2-10) will run
        against this bundle by field name."""
        stamps = {
            (
                section.versions.pattern_catalogue_version,
                section.versions.mapping_release_version,
                section.versions.target_provider,
            )
            for section in (self.design, self.diagram, self.plan, self.iac)
        }
        return len(stamps) == 1


def _version_stamp(target_model: TargetModel) -> VersionStamp:
    return VersionStamp(
        pattern_catalogue_version=target_model.pattern_catalogue_version,
        mapping_release_version=target_model.mapping_release_version,
        target_provider=target_model.target_provider,
    )


def build_design_export_bundle(
    *,
    target_model: TargetModel,
    design_revision: RevisionRecord,
    diagram: DiagramArtefact,
    plan_id: str,
    roadmap: MigrationRoadmap,
    plan_revision: RevisionRecord,
    iac: IaCPlanArtefact,
) -> DesignExportBundle:
    """Bundle one design's full export set.

    Every input must actually belong to the same ``target_model``/
    ``design_revision`` provenance chain -- never assumed from the
    caller's say-so:

    - ``diagram``/``iac`` must have been compiled from ``design_revision``
      (``revision_id`` match) and from ``target_model.design_id``.
    - ``roadmap``/``plan_revision`` must share ``target_model``'s
      tenant/project, and ``plan_revision`` must actually record
      ``roadmap`` (``content_hash`` match) under ``plan_id``.
    """
    if design_revision.content_hash != target_model.content_hash:
        raise ValidationError(
            "design_revision.content_hash does not match target_model.content_hash"
        )
    if diagram.revision_id != design_revision.revision_id or diagram.design_id != target_model.design_id:
        raise ValidationError("diagram artefact was not compiled from this design revision")
    if iac.revision_id != design_revision.revision_id or iac.design_id != target_model.design_id:
        raise ValidationError("iac artefact was not generated from this design revision")
    if roadmap.tenant_id != target_model.tenant_id or roadmap.project_id != target_model.project_id:
        raise ValidationError("roadmap does not belong to this design's tenant/project")
    if plan_revision.content_hash != roadmap.content_hash:
        raise ValidationError("plan_revision.content_hash does not match roadmap.content_hash")
    if plan_revision.subject_id != plan_id:
        raise ValidationError("plan_revision does not belong to the given plan_id")

    stamp = _version_stamp(target_model)
    workload_count = sum(len(wave.workloads) for wave in roadmap.waves)

    design_section = DesignRevisionSection(
        design_id=target_model.design_id,
        revision_id=design_revision.revision_id,
        revision_number=design_revision.revision_number,
        content_hash=target_model.content_hash,
        pattern_id=target_model.pattern_id,
        parameters=target_model.parameters,
        versions=stamp,
    )
    diagram_section = DiagramSection(
        artefact_id=diagram.artefact_id,
        kind=diagram.kind,
        revision_id=diagram.revision_id,
        revision_number=diagram.revision_number,
        content_hash=diagram.content_hash,
        shape_count=len(diagram.model.shapes),
        unresolved_shape_ids=diagram.unresolved_shape_ids,
        versions=stamp,
    )
    plan_section = PlanSection(
        plan_id=plan_id,
        revision_id=plan_revision.revision_id,
        revision_number=plan_revision.revision_number,
        content_hash=plan_revision.content_hash,
        wave_count=len(roadmap.waves),
        workload_count=workload_count,
        blocked_workload_ids=roadmap.blocked_workload_ids,
        versions=stamp,
    )
    iac_section = IacSection(
        artefact_id=iac.artefact_id,
        kind=iac.kind,
        revision_id=iac.revision_id,
        revision_number=iac.revision_number,
        content_hash=iac.content_hash,
        gap_resource_ids=iac.gap_resource_ids,
        versions=stamp,
    )

    return DesignExportBundle(
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        design_id=target_model.design_id,
        design=design_section,
        diagram=diagram_section,
        plan=plan_section,
        iac=iac_section,
    )


__all__ = [
    "DesignExportBundle",
    "DesignRevisionSection",
    "DiagramSection",
    "IacSection",
    "PlanSection",
    "VersionStamp",
    "build_design_export_bundle",
]
