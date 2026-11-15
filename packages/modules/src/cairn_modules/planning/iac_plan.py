"""R2-07: Terraform plan preview (spec §16's R2-07 row: "Plan only; no
apply; mapping and pattern versions recorded").

Compiles 703's deterministic ``TargetModel`` (``cairn_modules.design.
target_model``) into a Terraform plan **preview**: deterministic HCL/
plan-preview *text*, never a real `plan` or `apply` run of the Terraform
binary and never a call to any Terraform binary, cloud SDK or cloud
credential.

ADR-010 draws the release boundary this story must respect by
construction, not by omission: R0-R3 permit **no Class C operation**
against a customer environment, and "apply IaC" is explicitly named as a
Class C effect. This story's output is a plan *preview* a human reads --
the same "fake adapter, no real executor" shape the rest of this
codebase already uses for every port before its production adapter is
in scope (``ExecutionGatePort``'s deterministic test adapter,
``ProviderExecutionPort``'s total absence before R4). There is no
Terraform binary invocation, no cloud SDK import and no cloud credential
anywhere in this module or its adapters
(``cairn_adapters.iac_terraform``) -- see
``packages/modules/tests/test_iac_plan.py::
test_iac_plan_code_path_touches_no_real_terraform_or_cloud`` and
``packages/adapters/tests/test_iac_terraform.py`` for the proof. This is
also why CAIRN's *own* infrastructure tooling
(``infra/terraform/README.md``) is kept entirely separate from this
story: that directory manages CAIRN's own deployment and is driven by a
human maintainer running a real `terraform` binary by hand or in CI;
this module never shares a binary, a backend, a state file or a
credential with it, and produces output *for the customer's future
environment*, never applied by CAIRN itself before R4 (ADR-010).

This module owns exactly two things, mirroring 704's diagram compiler
shape:

1. ``IaCPlanModel`` -- a structured, provider-neutral, pre-emission
   projection of the target model, carrying the exact pattern catalogue
   version and mapping release version the target model recorded (spec's
   repeated "records versions" requirement, same discipline 703's
   ``TargetModel`` and 704's diagram compiler both follow). Every
   ``TargetModel.resources`` entry becomes exactly one
   ``IaCResourcePlan`` -- same count, same order -- never more, never
   fewer. A resource 703's resolver could not resolve at all
   (``UNRESOLVED``), or resolved to a mapping that is not actually usable
   (``UNAVAILABLE`` per the same rule 704's diagram compiler uses --
   ``Equivalence.UNSUPPORTED`` or an unsupported region), is never
   silently skipped: it becomes a named ``GAP`` entry a reader of the
   rendered preview sees directly, carrying the resolver's own
   explanation, never a resource block that pretends a mapping exists.
2. ``IaCGeneratorPort`` -- the hexagonal port (spec §5.4:
   ``IaCGeneratorPort | planning | Terraform emitter, fake``) that turns
   an ``IaCPlanModel`` into rendered preview text. This module never
   imports an adapter (``domain-purity``); it only depends on the
   adapter satisfying this Protocol structurally. Implementations live
   in ``cairn_adapters.iac_terraform``.

The gap rule (grounded entirely in fields 703's ``TargetResourceEntry``/
``ResolvedMapping`` already expose, the same discipline 704's
``_marker_for`` uses for its finer four-way distinction):

* ``GAP`` -- either ``TargetResourceEntry.status`` is ``UNRESOLVED`` (no
  mapping entry at all, or the matching entry's own equivalence is
  ``UNAVAILABLE``), or the entry resolved but
  ``resolution.equivalence`` is ``Equivalence.UNSUPPORTED`` or
  ``resolution.region_supported`` is ``False`` (a mapping exists in the
  catalogue but isn't actually usable for this resource). No resource
  block is emitted for a ``GAP`` entry; it is rendered as a visible,
  named gap instead (never a silently-skipped resource).
* ``PLANNED`` -- everything else: a real resource block is emitted. When
  ``resolution.equivalence`` is ``Equivalence.APPROXIMATE``, the entry is
  still ``PLANNED`` (a usable target exists) but ``approximate`` is
  ``True`` and the resolver's caveat is carried into ``detail`` so the
  rendered preview never presents an approximate mapping as if it were
  exact (R-MAP-01).
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
IAC_PLAN_ARTEFACT_KIND = "IAC"

#: Fixed banner text rendered at the top of every real-emitter preview --
#: the human-readable restatement of ADR-010's "plan only; no apply"
#: boundary, so the preview itself never lets a reader believe this
#: output was, or could be, applied by CAIRN.
IAC_PLAN_DISCLAIMER = (
    "CAIRN IaC plan preview -- PLAN ONLY. Not executed. Not applied. "
    "No Terraform binary was invoked and no cloud credential was used "
    "to produce this text; nothing here changes any customer environment."
)


class IaCResourceStatus(str, Enum):
    """Whether a target resource entry becomes a real Terraform resource
    block in the rendered preview, or a named gap."""

    PLANNED = "PLANNED"
    GAP = "GAP"


@dataclass(frozen=True, slots=True)
class IaCResourcePlan:
    """One source resource's outcome in the plan preview, backed by
    exactly one real ``TargetResourceEntry`` -- never a placeholder
    resource for something the target model could not resolve."""

    resource_id: str
    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    status: IaCResourceStatus
    approximate: bool
    detail: str | None

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValidationError("iac resource plan id is required")
        if self.status is IaCResourceStatus.GAP and self.target_service is not None:
            raise ValidationError("a GAP entry must not carry a target service")
        if self.status is IaCResourceStatus.GAP and not self.detail:
            raise ValidationError("a GAP entry must carry an explanatory detail")
        if self.status is IaCResourceStatus.PLANNED and self.target_service is None:
            raise ValidationError("a PLANNED entry must carry a resolved target service")
        if self.status is IaCResourceStatus.GAP and self.approximate:
            raise ValidationError("a GAP entry cannot also be approximate")


@dataclass(frozen=True, slots=True)
class IaCPlanModel:
    """The structured, pre-emission projection of one target model into
    a plan preview. This is what tests assert against -- never the real
    emitter's exact HCL text, which is brittle and not the contract."""

    tenant_id: str
    project_id: str
    design_id: str
    revision_id: str
    revision_number: int
    pattern_id: str
    pattern_catalogue_version: str
    mapping_release_version: str
    target_provider: str
    target_model_content_hash: str
    resources: tuple[IaCResourcePlan, ...]

    @property
    def gap_resource_ids(self) -> tuple[str, ...]:
        return tuple(
            resource.resource_id
            for resource in self.resources
            if resource.status is IaCResourceStatus.GAP
        )


@dataclass(frozen=True, slots=True)
class IaCPlanArtefact:
    """One compiled plan preview, referencing the exact design revision
    (``subject_revision`` row) it was generated from.

    ``artefact_id`` is a pure function of the revision identity and the
    structured plan model's content -- not a random id -- so generating
    a preview for the *same* revision twice always yields the identical
    ``artefact_id``/``content_hash``, and a *different* revision always
    yields a visibly different one."""

    artefact_id: str
    kind: str
    tenant_id: str
    project_id: str
    design_id: str
    revision_id: str
    revision_number: int
    content_hash: str
    model: IaCPlanModel
    rendered_content: str

    @property
    def gap_resource_ids(self) -> tuple[str, ...]:
        return self.model.gap_resource_ids


class IaCGeneratorPort(Port, Protocol):
    """spec §5.4: ``IaCGeneratorPort | planning | Terraform emitter,
    fake``.

    Turns an ``IaCPlanModel`` into rendered preview text. Implementations
    live in ``cairn_adapters.iac_terraform`` (a real deterministic
    text/HCL emitter, and a deterministic fake for tests) -- this module
    never imports them, it only depends on this Protocol being satisfied
    structurally. By construction, nothing an implementation of this
    Protocol is required to do ever touches a Terraform binary, a cloud
    SDK, or a cloud credential: ``generate`` takes one in-process
    ``IaCPlanModel`` and returns one ``str``."""

    def generate(self, plan: IaCPlanModel) -> str:
        """Render ``plan`` to its preview text (Terraform-style HCL
        comments/blocks for the real adapter). Must be a pure function of
        ``plan`` -- no timestamps, no randomness, no non-deterministic
        ordering, no I/O of any kind."""


def _status_for(entry: TargetResourceEntry) -> tuple[IaCResourceStatus, bool]:
    """Returns ``(status, approximate)`` for one target resource entry,
    per this module's gap rule."""
    if entry.status is TargetResourceStatus.UNRESOLVED:
        return IaCResourceStatus.GAP, False
    resolution = entry.resolution
    assert resolution is not None  # RESOLVED entries always carry one (target_model's own invariant)
    if resolution.equivalence is Equivalence.UNSUPPORTED or not resolution.region_supported:
        return IaCResourceStatus.GAP, False
    if resolution.equivalence is Equivalence.APPROXIMATE:
        return IaCResourceStatus.PLANNED, True
    return IaCResourceStatus.PLANNED, False


def _detail_for(entry: TargetResourceEntry, status: IaCResourceStatus, approximate: bool) -> str | None:
    if status is IaCResourceStatus.GAP:
        if entry.status is TargetResourceStatus.UNRESOLVED:
            return entry.reason
        resolution = entry.resolution
        assert resolution is not None
        if resolution.equivalence is Equivalence.UNSUPPORTED:
            return resolution.caveat or "mapping is marked unsupported in this release"
        return resolution.caveat or "mapping is not supported in this resource's region"
    resolution = entry.resolution
    assert resolution is not None
    if approximate:
        return resolution.caveat or "target is an approximate equivalent, not a like-for-like match"
    return resolution.caveat


def _resource_plan_for(entry: TargetResourceEntry) -> IaCResourcePlan:
    status, approximate = _status_for(entry)
    target_service: str | None = None
    target_provider = ""
    if entry.resolution is not None:
        target_provider = entry.resolution.target_provider
        if status is IaCResourceStatus.PLANNED:
            target_service = entry.resolution.target_service
    return IaCResourcePlan(
        resource_id=entry.resource_id,
        source_provider=entry.source_provider,
        source_service=entry.source_service,
        target_provider=target_provider,
        target_service=target_service,
        status=status,
        approximate=approximate,
        detail=_detail_for(entry, status, approximate),
    )


def build_iac_plan_model(*, target_model: TargetModel, revision: RevisionRecord) -> IaCPlanModel:
    """Project ``target_model`` into an ``IaCPlanModel``, referencing
    ``revision`` (703's ``subject_revision`` row this target model was
    recorded under).

    Rejects a ``revision`` that doesn't actually record this exact
    ``target_model`` (tenant/project mismatch, or ``content_hash``
    mismatch) -- the same revision-binding guard 704's diagram compiler
    uses, applied here too.

    Every one of ``target_model.resources`` becomes exactly one
    ``IaCResourcePlan`` -- same count, same order (already sorted by
    ``resource_id`` by ``generate_target_model``) -- never more, never
    fewer.
    """
    if revision.tenant_id != target_model.tenant_id or revision.project_id != target_model.project_id:
        raise ValidationError("revision does not belong to this target model's tenant/project")
    if revision.content_hash != target_model.content_hash:
        raise ValidationError(
            "revision.content_hash does not match target_model.content_hash -- "
            "the revision does not record this exact target model"
        )

    resources = tuple(_resource_plan_for(entry) for entry in target_model.resources)
    return IaCPlanModel(
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        design_id=target_model.design_id,
        revision_id=revision.revision_id,
        revision_number=revision.revision_number,
        pattern_id=target_model.pattern_id,
        pattern_catalogue_version=target_model.pattern_catalogue_version,
        mapping_release_version=target_model.mapping_release_version,
        target_provider=target_model.target_provider,
        target_model_content_hash=target_model.content_hash,
        resources=resources,
    )


def _resource_to_jsonable(resource: IaCResourcePlan) -> dict[str, object]:
    return {
        "resource_id": resource.resource_id,
        "source_provider": resource.source_provider,
        "source_service": resource.source_service,
        "target_provider": resource.target_provider,
        "target_service": resource.target_service,
        "status": resource.status.value,
        "approximate": resource.approximate,
        "detail": resource.detail,
    }


def _iac_plan_content_hash(model: IaCPlanModel) -> str:
    """A stable fingerprint of the plan's own emission-agnostic content
    (pattern, versions, provider, target-model content hash and every
    resource) -- independent of which ``IaCGeneratorPort`` rendered it,
    so two generators compiling the same target model agree on this
    value even though their ``rendered_content`` bytes differ."""
    payload = {
        "design_id": model.design_id,
        "pattern_id": model.pattern_id,
        "pattern_catalogue_version": model.pattern_catalogue_version,
        "mapping_release_version": model.mapping_release_version,
        "target_provider": model.target_provider,
        "target_model_content_hash": model.target_model_content_hash,
        "resources": [_resource_to_jsonable(resource) for resource in model.resources],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iac_plan_artefact_id(model: IaCPlanModel, content_hash: str) -> str:
    """Deterministic artefact id: a pure hash of the exact revision this
    plan preview was generated from, plus its content hash -- the same
    "same revision -> identical id, different revision -> different id"
    guarantee 704's diagram compiler proves for ``DiagramArtefact``."""
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


def generate_iac_plan(
    *,
    target_model: TargetModel,
    revision: RevisionRecord,
    generator: IaCGeneratorPort,
) -> IaCPlanArtefact:
    """Generate one ``IaCPlanArtefact`` from ``target_model`` (703's
    deterministic model) and the exact ``revision`` it was recorded
    under, via ``generator``.

    Calling this twice with the same ``target_model``/``revision`` (same
    content, same revision identity) always yields an ``IaCPlanArtefact``
    with an identical ``artefact_id`` and ``content_hash`` -- regardless
    of which ``IaCGeneratorPort`` implementation is used. This function
    never invokes a Terraform binary, a cloud SDK or a cloud credential;
    ``generator.generate`` is called exactly once, with one in-process
    ``IaCPlanModel``, and its return value is used verbatim as
    ``rendered_content`` -- there is no execution step here at all
    (ADR-010: plan preview only, never applied).
    """
    model = build_iac_plan_model(target_model=target_model, revision=revision)
    rendered_content = generator.generate(model)
    content_hash = _iac_plan_content_hash(model)
    artefact_id = _iac_plan_artefact_id(model, content_hash)
    return IaCPlanArtefact(
        artefact_id=artefact_id,
        kind=IAC_PLAN_ARTEFACT_KIND,
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
    "IAC_PLAN_ARTEFACT_KIND",
    "IAC_PLAN_DISCLAIMER",
    "IaCGeneratorPort",
    "IaCPlanArtefact",
    "IaCPlanModel",
    "IaCResourcePlan",
    "IaCResourceStatus",
    "build_iac_plan_model",
    "generate_iac_plan",
]
