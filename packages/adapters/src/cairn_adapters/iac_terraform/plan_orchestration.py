"""787 (R4-03a): Terraform plan orchestration (spec §2.4, ADR-009,
ADR-010). "No cloud" -- tested entirely against a fake backend, no real
project.

This module sits between two things already built and never reinvents
either:

* R2-07's ``IaCGeneratorPort``/``IaCPlanArtefact``
  (``cairn_modules.planning.iac_plan``) -- the deterministic, pre-emission
  projection of one design revision's resources into a Terraform-style
  plan preview. This module treats an ``IaCPlanArtefact`` as its input;
  it never recomputes anything ``generate_iac_plan`` already computed.
* 784's ``ProviderExecutionPort`` contract
  (``cairn_adapters.provider_execution.ports``) -- its ``plan`` method is
  the one call this module makes, exactly once, to get a dry-run preview
  from whichever adapter is injected (the fake adapter
  (``cairn_adapters.provider_execution.fake.FakeProviderExecutionAdapter``)
  in every test this unit ships; a real provider adapter's ``apply``/
  ``rollback`` are 788/789's cloud-gated job, never called from here).

§2.4 (the plan document, quoted verbatim in this unit's brief): "The
plan's exact diff, resource list and mutation class become the immutable
revision payload (ADR-009) -- ``revision_id``, ``content_hash``, input
versions, creator, timestamp." ``TerraformPlanRevisionPayload`` is exactly
that payload: it carries the same ``revision_id`` the design revision
(``cairn_modules.approvals.model.RevisionRecord``) this plan was generated
from already owns -- this module never invents a separate, untethered
revision identity -- plus the diff (every resource's planned action),
the resource list and the mutation class the provider's ``plan`` call was
asked to dry-run against.

Determinism (the same discipline ``cairn_modules.planning.iac_plan``
already applies to ``IaCPlanArtefact.content_hash``): calling
``orchestrate_terraform_plan`` twice with the same ``IaCPlanArtefact``,
the same injected adapter and the same ``mutation_class`` always yields
an identical ``TerraformPlanRevisionPayload.content_hash`` -- the hash is
a pure function of the diff, the resource list, the mutation class, the
provider's returned preview and the input versions, never of
``created_by``/``created_at``.

No Terraform binary, no cloud SDK and no cloud credential anywhere in
this module -- see ``packages/adapters/tests/
test_terraform_plan_orchestration.py`` for the AST-based import-scan proof
this module and its fake backend share with
``cairn_adapters.execution_gcp``/``cairn_adapters.provider_execution``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.ports import Clock
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.planning.iac_plan import IaCPlanArtefact, IaCResourcePlan, IaCResourceStatus

from cairn_adapters.provider_execution.ports import (
    ExecutionScope,
    PlanRequest,
    PlanResult,
    ProviderExecutionPort,
)

#: The ``ExecutionScope.operation`` literal every call this module makes
#: to ``ProviderExecutionPort.plan`` carries -- a dry-run preview, never
#: an apply, so this is deliberately distinct from any ``*.apply.*``/
#: ``*.rollback.*`` operation literal a real adapter dispatches on.
TERRAFORM_PLAN_OPERATION = "terraform.plan"


class PlanDiffAction(str, Enum):
    """What the plan diff says about one resource -- mirrors
    ``IaCResourceStatus`` exactly (every ``PLANNED`` entry in the plan
    model becomes a ``CREATE`` diff entry; every ``GAP`` entry stays a
    visible, named ``GAP`` diff entry, never silently dropped)."""

    CREATE = "CREATE"
    GAP = "GAP"


@dataclass(frozen=True, slots=True)
class TerraformPlanDiffEntry:
    """One resource's outcome in the captured diff -- backed by exactly
    one ``IaCResourcePlan`` entry from the plan artefact this orchestration
    was given, same count, same order, never more, never fewer."""

    resource_id: str
    action: PlanDiffAction
    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    approximate: bool
    detail: str | None

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValidationError("plan diff entry resource_id is required")
        if self.action is PlanDiffAction.GAP and self.target_service is not None:
            raise ValidationError("a GAP diff entry must not carry a target service")
        if self.action is PlanDiffAction.CREATE and self.target_service is None:
            raise ValidationError("a CREATE diff entry must carry a resolved target service")


@dataclass(frozen=True, slots=True)
class TerraformPlanRevisionPayload:
    """§2.4's "immutable revision payload": the plan's exact diff,
    resource list and mutation class, bound to the exact design revision
    this plan was orchestrated from.

    ``revision_id``/``revision_number`` are the design revision's own
    (``RevisionRecord.revision_id``/``revision_number``) -- this payload
    augments that revision's identity with the Terraform plan's content,
    it never creates a second, competing revision concept. ``content_hash``
    is this payload's own fingerprint (diff + resource list + mutation
    class + provider preview + input versions) -- deliberately a
    different value from the design revision's ``content_hash``
    (``IaCPlanArtefact.model.target_model_content_hash``), which is
    carried forward unchanged inside ``input_versions`` so the binding
    back to that exact target model is still provable from this payload
    alone.
    """

    revision_id: str
    tenant_id: str
    project_id: str
    design_id: str
    revision_number: int
    content_hash: str
    input_versions: tuple[tuple[str, str], ...]
    created_by: str
    created_at: datetime
    mutation_class: MutationClass
    diff: tuple[TerraformPlanDiffEntry, ...]
    resource_list: tuple[str, ...]
    reversible: bool
    provider_preview: dict[str, object]

    def __post_init__(self) -> None:
        if not self.revision_id.strip():
            raise ValidationError("revision payload requires a revision identifier")
        if not self.content_hash.strip():
            raise ValidationError("revision payload requires a content hash")
        if not self.created_by.strip():
            raise ValidationError("revision payload requires a creator")
        if self.revision_number < 1:
            raise ValidationError("revision_number must start at 1 and increase monotonically")
        if self.mutation_class is MutationClass.READ_ONLY:
            raise ValidationError(
                "a terraform-plan revision payload only ever carries an external mutation class"
            )
        expected_resource_list = tuple(entry.resource_id for entry in self.diff)
        if self.resource_list != expected_resource_list:
            raise ValidationError(
                "resource_list must list exactly the diff entries' resource_ids, in order"
            )


def _diff_entry_for(resource: IaCResourcePlan) -> TerraformPlanDiffEntry:
    action = PlanDiffAction.GAP if resource.status is IaCResourceStatus.GAP else PlanDiffAction.CREATE
    return TerraformPlanDiffEntry(
        resource_id=resource.resource_id,
        action=action,
        source_provider=resource.source_provider,
        source_service=resource.source_service,
        target_provider=resource.target_provider,
        target_service=resource.target_service,
        approximate=resource.approximate,
        detail=resource.detail,
    )


def _entry_to_jsonable(entry: TerraformPlanDiffEntry) -> dict[str, object]:
    return {
        "resource_id": entry.resource_id,
        "action": entry.action.value,
        "source_provider": entry.source_provider,
        "source_service": entry.source_service,
        "target_provider": entry.target_provider,
        "target_service": entry.target_service,
        "approximate": entry.approximate,
        "detail": entry.detail,
    }


def _jsonable(value: object) -> object:
    """Recursively coerce a provider-returned preview (a plain
    ``Mapping``, possibly nesting other mappings/sequences) into plain
    ``dict``/``list`` so it can be canonically hashed -- the preview is
    never trusted to already be exactly ``dict``/``list``/primitive."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _payload_content_hash(
    *,
    diff: tuple[TerraformPlanDiffEntry, ...],
    resource_list: tuple[str, ...],
    mutation_class: MutationClass,
    plan_result: PlanResult,
    input_versions: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "resource_list": list(resource_list),
        "diff": [_entry_to_jsonable(entry) for entry in diff],
        "mutation_class": mutation_class.value,
        "reversible": plan_result.reversible,
        "provider_preview": _jsonable(dict(plan_result.preview)),
        "input_versions": [[key, value] for key, value in input_versions],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def orchestrate_terraform_plan(
    *,
    plan_artefact: IaCPlanArtefact,
    provider_port: ProviderExecutionPort,
    mutation_class: MutationClass,
    created_by: str,
    clock: Clock,
) -> TerraformPlanRevisionPayload:
    """Orchestrate one Terraform plan: capture the diff and resource list
    from ``plan_artefact`` (R2-07's output), ask ``provider_port`` for a
    dry-run preview of it (784's contract), and bind the result into one
    immutable revision payload (§2.4/ADR-009), bound to ``plan_artefact``'s
    own design revision identity.

    Calls ``provider_port.plan`` exactly once -- this function never calls
    ``apply`` or ``rollback``; that is explicitly out of scope for this
    unit (788/789's cloud-gated job). Raises ``ValidationError`` for a
    ``READ_ONLY`` mutation class (a provider execution adapter only ever
    handles external mutation classes -- the same rule
    ``ProviderExecutionDescriptor`` already enforces) or a blank
    ``created_by``, and if the provider's ``PlanResult.mutation_class``
    somehow disagrees with the one requested (a defensive check: this
    function must never silently accept a provider that dry-ran a
    different mutation class than the one it was asked for).
    """
    if mutation_class is MutationClass.READ_ONLY:
        raise ValidationError(
            "this orchestration requires an external mutation class"
        )
    if not created_by.strip():
        raise ValidationError("this orchestration requires a creator")

    diff = tuple(_diff_entry_for(resource) for resource in plan_artefact.model.resources)
    resource_list = tuple(entry.resource_id for entry in diff)

    scope = ExecutionScope(
        tenant_id=plan_artefact.tenant_id,
        project_id=plan_artefact.project_id,
        revision_id=plan_artefact.revision_id,
        operation=TERRAFORM_PLAN_OPERATION,
    )
    request = PlanRequest(
        scope=scope,
        mutation_class=mutation_class,
        payload={"resources": [_entry_to_jsonable(entry) for entry in diff]},
    )
    result = provider_port.plan(request)
    if result.mutation_class is not mutation_class:
        raise ValidationError(
            "provider plan result mutation_class does not match the requested mutation_class"
        )

    input_versions = (
        ("pattern_catalogue_version", plan_artefact.model.pattern_catalogue_version),
        ("mapping_release_version", plan_artefact.model.mapping_release_version),
        ("target_provider", plan_artefact.model.target_provider),
        ("iac_plan_content_hash", plan_artefact.content_hash),
    )

    content_hash = _payload_content_hash(
        diff=diff,
        resource_list=resource_list,
        mutation_class=mutation_class,
        plan_result=result,
        input_versions=input_versions,
    )

    return TerraformPlanRevisionPayload(
        revision_id=plan_artefact.revision_id,
        tenant_id=plan_artefact.tenant_id,
        project_id=plan_artefact.project_id,
        design_id=plan_artefact.design_id,
        revision_number=plan_artefact.revision_number,
        content_hash=content_hash,
        input_versions=input_versions,
        created_by=created_by,
        created_at=clock.now(),
        mutation_class=mutation_class,
        diff=diff,
        resource_list=resource_list,
        reversible=result.reversible,
        provider_preview=_jsonable(dict(result.preview)),
    )


__all__ = [
    "TERRAFORM_PLAN_OPERATION",
    "PlanDiffAction",
    "TerraformPlanDiffEntry",
    "TerraformPlanRevisionPayload",
    "orchestrate_terraform_plan",
]
