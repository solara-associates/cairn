"""787 (R4-03a): Terraform plan orchestration and diff capture (spec
§2.4, ADR-009, ADR-010). Every test here runs against
``FakeProviderExecutionAdapter`` (``cairn_adapters.provider_execution.
fake``) and a plain, directly-constructed ``IaCPlanArtefact`` -- no real
Terraform binary, no real GCP/AWS network call, no cloud SDK, no real
project anywhere. R2-07's own pipeline (``generate_iac_plan`` against a
real ``TargetModel``) has its own test suite
(``packages/modules/tests/test_iac_plan.py``); this suite only proves the
orchestration layer this unit adds on top of an already-built
``IaCPlanArtefact``.
"""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.iac_terraform import (
    TERRAFORM_PLAN_OPERATION,
    PlanDiffAction,
    TerraformPlanDiffEntry,
    TerraformPlanRevisionPayload,
    orchestrate_terraform_plan,
)
from cairn_adapters.provider_execution import FakeProviderExecutionAdapter
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.planning.iac_plan import (
    IAC_PLAN_ARTEFACT_KIND,
    IaCPlanArtefact,
    IaCPlanModel,
    IaCResourcePlan,
    IaCResourceStatus,
)

REPO_ROOT = Path(__file__).parents[3]
PLAN_ORCHESTRATION_SRC = (
    Path(__file__).parents[1] / "src" / "cairn_adapters" / "iac_terraform"
)
PROVIDER_EXECUTION_SRC = (
    Path(__file__).parents[1] / "src" / "cairn_adapters" / "provider_execution"
)

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


def _model(**overrides: object) -> IaCPlanModel:
    payload: dict[str, object] = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "design_id": "design-1",
        "revision_id": "revision-1",
        "revision_number": 1,
        "pattern_id": "web-app",
        "pattern_catalogue_version": "2026.11.1",
        "mapping_release_version": "2026.11.1",
        "target_provider": "gcp",
        "target_model_content_hash": "target-model-hash-abc",
        "resources": (
            IaCResourcePlan(
                resource_id="res-1",
                source_provider="aws",
                source_service="s3",
                target_provider="gcp",
                target_service="cloud-storage",
                status=IaCResourceStatus.PLANNED,
                approximate=False,
                detail=None,
            ),
            IaCResourcePlan(
                resource_id="res-2",
                source_provider="aws",
                source_service="route53",
                target_provider="",
                target_service=None,
                status=IaCResourceStatus.GAP,
                approximate=False,
                detail="no mapping entry",
            ),
        ),
    }
    payload.update(overrides)
    return IaCPlanModel(**payload)


def _artefact(model: IaCPlanModel | None = None, **overrides: object) -> IaCPlanArtefact:
    model = model or _model()
    payload: dict[str, object] = {
        "artefact_id": "artefact-1",
        "kind": IAC_PLAN_ARTEFACT_KIND,
        "tenant_id": model.tenant_id,
        "project_id": model.project_id,
        "design_id": model.design_id,
        "revision_id": model.revision_id,
        "revision_number": model.revision_number,
        "content_hash": "plan-content-hash-abc",
        "model": model,
        "rendered_content": "# rendered preview text",
    }
    payload.update(overrides)
    return IaCPlanArtefact(**payload)


def _orchestrate(
    *,
    artefact: IaCPlanArtefact | None = None,
    adapter: FakeProviderExecutionAdapter | None = None,
    mutation_class: MutationClass = MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
    created_by: str = "actor-1",
) -> tuple[TerraformPlanRevisionPayload, FakeProviderExecutionAdapter]:
    artefact = artefact or _artefact()
    adapter = adapter or FakeProviderExecutionAdapter()
    payload = orchestrate_terraform_plan(
        plan_artefact=artefact,
        provider_port=adapter,
        mutation_class=mutation_class,
        created_by=created_by,
        clock=_FixedClock(),
    )
    return payload, adapter


# --- the diff: no invented or dropped resources, gaps stay visible --------


def test_every_plan_resource_becomes_exactly_one_diff_entry_same_order() -> None:
    payload, _ = _orchestrate()
    assert [entry.resource_id for entry in payload.diff] == ["res-1", "res-2"]
    assert payload.resource_list == ("res-1", "res-2")


def test_a_planned_resource_becomes_a_create_diff_entry() -> None:
    payload, _ = _orchestrate()
    entry = payload.diff[0]
    assert entry.action is PlanDiffAction.CREATE
    assert entry.target_service == "cloud-storage"


def test_a_gap_resource_stays_a_visible_gap_diff_entry_never_dropped() -> None:
    payload, _ = _orchestrate()
    entry = payload.diff[1]
    assert entry.action is PlanDiffAction.GAP
    assert entry.target_service is None
    assert entry.detail == "no mapping entry"


def test_a_gap_diff_entry_cannot_carry_a_target_service() -> None:
    with pytest.raises(ValidationError):
        TerraformPlanDiffEntry(
            resource_id="res-x",
            action=PlanDiffAction.GAP,
            source_provider="aws",
            source_service="s3",
            target_provider="gcp",
            target_service="cloud-storage",
            approximate=False,
            detail="should not be possible",
        )


def test_a_create_diff_entry_requires_a_resolved_target_service() -> None:
    with pytest.raises(ValidationError):
        TerraformPlanDiffEntry(
            resource_id="res-x",
            action=PlanDiffAction.CREATE,
            source_provider="aws",
            source_service="s3",
            target_provider="gcp",
            target_service=None,
            approximate=False,
            detail=None,
        )


# --- revision binding (§2.4 / ADR-009) -------------------------------------


def test_the_payload_is_bound_to_the_exact_design_revision_identity() -> None:
    artefact = _artefact()
    payload, _ = _orchestrate(artefact=artefact)
    assert payload.revision_id == artefact.revision_id
    assert payload.revision_number == artefact.revision_number
    assert payload.tenant_id == artefact.tenant_id
    assert payload.project_id == artefact.project_id
    assert payload.design_id == artefact.design_id


def test_input_versions_carries_the_plan_artefacts_own_content_hash() -> None:
    artefact = _artefact()
    payload, _ = _orchestrate(artefact=artefact)
    assert ("iac_plan_content_hash", artefact.content_hash) in payload.input_versions
    assert ("pattern_catalogue_version", "2026.11.1") in payload.input_versions
    assert ("target_provider", "gcp") in payload.input_versions


def test_the_mutation_class_requested_is_carried_onto_the_payload() -> None:
    payload, _ = _orchestrate(mutation_class=MutationClass.COMPENSATABLE_EXTERNAL_MUTATION)
    assert payload.mutation_class is MutationClass.COMPENSATABLE_EXTERNAL_MUTATION


def test_created_by_and_created_at_are_recorded() -> None:
    payload, _ = _orchestrate(created_by="alice")
    assert payload.created_by == "alice"
    assert payload.created_at == NOW


def test_a_revision_payload_rejects_a_read_only_mutation_class_directly() -> None:
    artefact = _artefact()
    diff = (
        TerraformPlanDiffEntry(
            resource_id="res-1",
            action=PlanDiffAction.CREATE,
            source_provider="aws",
            source_service="s3",
            target_provider="gcp",
            target_service="cloud-storage",
            approximate=False,
            detail=None,
        ),
    )
    with pytest.raises(ValidationError):
        TerraformPlanRevisionPayload(
            revision_id=artefact.revision_id,
            tenant_id=artefact.tenant_id,
            project_id=artefact.project_id,
            design_id=artefact.design_id,
            revision_number=artefact.revision_number,
            content_hash="hash",
            input_versions=(),
            created_by="actor-1",
            created_at=NOW,
            mutation_class=MutationClass.READ_ONLY,
            diff=diff,
            resource_list=("res-1",),
            reversible=True,
            provider_preview={},
        )


def test_resource_list_must_match_the_diffs_resource_ids_in_order() -> None:
    artefact = _artefact()
    diff = (
        TerraformPlanDiffEntry(
            resource_id="res-1",
            action=PlanDiffAction.CREATE,
            source_provider="aws",
            source_service="s3",
            target_provider="gcp",
            target_service="cloud-storage",
            approximate=False,
            detail=None,
        ),
    )
    with pytest.raises(ValidationError):
        TerraformPlanRevisionPayload(
            revision_id=artefact.revision_id,
            tenant_id=artefact.tenant_id,
            project_id=artefact.project_id,
            design_id=artefact.design_id,
            revision_number=artefact.revision_number,
            content_hash="hash",
            input_versions=(),
            created_by="actor-1",
            created_at=NOW,
            mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            diff=diff,
            resource_list=("res-999",),
            reversible=True,
            provider_preview={},
        )


# --- orchestration validation ----------------------------------------------


def test_orchestration_rejects_a_read_only_mutation_class() -> None:
    with pytest.raises(ValidationError):
        _orchestrate(mutation_class=MutationClass.READ_ONLY)


def test_orchestration_rejects_a_blank_created_by() -> None:
    with pytest.raises(ValidationError):
        _orchestrate(created_by="   ")


def test_orchestration_rejects_a_provider_that_disagrees_about_mutation_class() -> None:
    class _DisagreeingAdapter(FakeProviderExecutionAdapter):
        def plan(self, request):  # type: ignore[override]
            result = super().plan(request)
            return type(result)(
                mutation_class=MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
                preview=result.preview,
                reversible=result.reversible,
            )

    with pytest.raises(ValidationError):
        _orchestrate(adapter=_DisagreeingAdapter())


# --- 784's contract: exactly one plan() call, correctly scoped ------------


def test_orchestration_calls_plan_exactly_once_with_the_right_scope() -> None:
    _, adapter = _orchestrate()
    assert len(adapter.plan_calls) == 1
    request = adapter.plan_calls[0]
    assert request.scope.tenant_id == "tenant-1"
    assert request.scope.project_id == "project-1"
    assert request.scope.revision_id == "revision-1"
    assert request.scope.operation == TERRAFORM_PLAN_OPERATION
    assert request.mutation_class is MutationClass.REVERSIBLE_EXTERNAL_MUTATION


def test_orchestration_never_calls_apply_or_rollback() -> None:
    _, adapter = _orchestrate()
    assert adapter.apply_calls == []
    assert adapter.rollback_calls == []


def test_reversible_flag_follows_the_providers_plan_result() -> None:
    payload, _ = _orchestrate(mutation_class=MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION)
    assert payload.reversible is False

    payload, _ = _orchestrate(mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    assert payload.reversible is True


# --- determinism: the plan diff becomes a reproducible revision payload ---


def test_the_same_artefact_and_provider_result_yield_an_identical_content_hash() -> None:
    artefact = _artefact()
    first, _ = _orchestrate(artefact=artefact)
    second, _ = _orchestrate(artefact=artefact)
    assert first.content_hash == second.content_hash
    assert first.content_hash != ""


def test_content_hash_is_independent_of_created_by_and_created_at() -> None:
    artefact = _artefact()
    first, _ = _orchestrate(artefact=artefact, created_by="alice")
    second, _ = _orchestrate(artefact=artefact, created_by="bob")
    assert first.content_hash == second.content_hash
    assert first.created_by != second.created_by


def test_a_different_plan_model_yields_a_different_content_hash() -> None:
    first_artefact = _artefact()
    second_model = _model(
        resources=(
            IaCResourcePlan(
                resource_id="res-1",
                source_provider="aws",
                source_service="s3",
                target_provider="gcp",
                target_service="cloud-storage",
                status=IaCResourceStatus.PLANNED,
                approximate=False,
                detail=None,
            ),
        )
    )
    second_artefact = _artefact(model=second_model, content_hash="plan-content-hash-different")

    first, _ = _orchestrate(artefact=first_artefact)
    second, _ = _orchestrate(artefact=second_artefact)
    assert first.content_hash != second.content_hash


def test_a_different_mutation_class_yields_a_different_content_hash() -> None:
    artefact = _artefact()
    first, _ = _orchestrate(artefact=artefact, mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    second, _ = _orchestrate(
        artefact=artefact, mutation_class=MutationClass.COMPENSATABLE_EXTERNAL_MUTATION
    )
    assert first.content_hash != second.content_hash


# --- no cloud, no Terraform binary anywhere in this unit's code path ------

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "cairn_adapters",
    "cairn_kernel",
    "cairn_modules",
    "collections",
    "dataclasses",
    "datetime",
    "enum",
    "hashlib",
    "json",
    "typing",
}


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package_dir", [PLAN_ORCHESTRATION_SRC, PROVIDER_EXECUTION_SRC])
def test_no_cloud_sdk_or_network_import_anywhere_in_this_units_packages(
    package_dir: Path,
) -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in _ALLOWED_IMPORT_ROOTS
        }
        if disallowed:
            violations[f"{package_dir.name}/{path.name}"] = disallowed
    assert not violations, f"disallowed (cloud SDK / network) imports: {violations}"


def test_no_network_or_subprocess_call_shaped_source_in_this_units_packages() -> None:
    forbidden_substrings = ("socket.", "urllib", "http.client", "subprocess")
    for package_dir in (PLAN_ORCHESTRATION_SRC, PROVIDER_EXECUTION_SRC):
        for path in sorted(package_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for bad in forbidden_substrings:
                assert bad not in source, f"{path}: found forbidden substring {bad!r}"
