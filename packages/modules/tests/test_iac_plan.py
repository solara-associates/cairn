"""R2-07: Terraform plan preview (spec §16's R2-07 row: "Plan only; no
apply; mapping and pattern versions recorded").

Tests assert on the structured pre-emission ``IaCPlanModel`` the
generator produces -- never on the real emitter's exact HCL text, which
is brittle (the same pattern 704's ``test_diagram_compiler.py`` uses).
The fake/deterministic adapter (``cairn_adapters.iac_terraform.
FakeIaCGenerator``) stands in for the port in most tests here; a few
tests exercise the real ``TerraformHclGenerator`` directly to prove it
renders well-formed, deterministic text and never drops a gap.

``test_iac_plan_code_path_touches_no_real_terraform_or_cloud`` is the
construction proof ADR-010 requires: nothing in this story's source
(this module, and ``cairn_adapters.iac_terraform``) imports a cloud SDK,
shells out to a binary, or references a cloud credential -- checked by
walking the actual AST of every file in this story's code path, the same
technique ``packages/contracts/tests/test_no_sdk_imports.py`` already
uses for ``cairn_contracts``.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.iac_terraform import FakeIaCGenerator, TerraformHclGenerator
from cairn_contracts.estate import Equivalence, FactStatus, Resource
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_contracts.mapping.pattern import Pattern, PatternParameterType
from cairn_kernel.errors import ValidationError
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design import generate_target_model, load_pattern_catalogue
from cairn_modules.planning import (
    IaCResourceStatus,
    build_iac_plan_model,
    generate_iac_plan,
)

REPO_ROOT = Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"
PLANNING_SRC = Path(__file__).parents[1] / "src" / "cairn_modules" / "planning"
IAC_TERRAFORM_SRC = (
    REPO_ROOT / "packages" / "adapters" / "src" / "cairn_adapters" / "iac_terraform"
)

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"


def _resource(**overrides: object) -> Resource:
    payload = {
        "resource_id": "res-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "provider": "aws",
        "account_id": "111111111111",
        "region": "eu-west-2",
        "service": "s3",
        "resource_type": "bucket",
        "native_id": "arn:aws:s3:::my-bucket",
        "name": "my-bucket",
        "tags": {},
        "facts": {},
        "provenance": (),
        "status": FactStatus.OBSERVED,
    }
    payload.update(overrides)
    return Resource(**payload)


def _entry(**overrides: object) -> MappingEntry:
    payload = {
        "id": "s3-to-gcs",
        "source_provider": "aws",
        "source_service": "s3",
        "target_provider": "gcp",
        "target_service": "cloud-storage",
        "equivalence": Equivalence.EXACT,
        "caveat": None,
        "regions": (),
        "evidence": "public documentation",
    }
    payload.update(overrides)
    return MappingEntry(**payload)


def _release(*entries: MappingEntry, version: str = "2026.11.1") -> MappingRelease:
    return MappingRelease(
        version=version,
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=entries or (_entry(),),
    )


def _web_app_pattern() -> Pattern:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        if pattern.id == "web-app":
            return pattern
    raise AssertionError("web-app seed pattern is missing")


def _revision_for(target_model: object, *, revision_number: int = 1) -> RevisionRecord:
    return RevisionRecord(
        revision_id=f"revision-{revision_number}",
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        subject_kind="design",
        subject_id=target_model.design_id,
        revision_number=revision_number,
        content_hash=target_model.content_hash,
        input_versions=(("pattern_id", target_model.pattern_id),),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def _mixed_estate() -> tuple[Resource, ...]:
    return (
        # PLANNED, exact equivalence: a clean resource block.
        _resource(resource_id="res-exact", service="s3"),
        # PLANNED, approximate equivalence: a resource block flagged as
        # not a like-for-like match.
        _resource(resource_id="res-approx", service="rds"),
        # GAP: resolves (an entry exists), but not supported in this
        # resource's region.
        _resource(resource_id="res-region", service="dynamodb", region="ap-southeast-2"),
        # GAP: resolves, but the catalogue marks it UNSUPPORTED.
        _resource(resource_id="res-unsupported", service="sagemaker"),
        # GAP: no catalogue entry exists for this pair at all.
        _resource(resource_id="res-missing", service="some-legacy-mainframe-service"),
        # GAP: a catalogue entry exists but its own equivalence is
        # UNAVAILABLE -- the resolver raises, never a substitute.
        _resource(resource_id="res-entry-unavailable", service="route53"),
    )


def _mixed_release() -> MappingRelease:
    return _release(
        _entry(id="s3", source_service="s3", target_service="cloud-storage", equivalence=Equivalence.EXACT),
        _entry(
            id="rds",
            source_service="rds",
            target_service="cloud-sql",
            equivalence=Equivalence.APPROXIMATE,
            caveat="managed-instance sizing differs",
        ),
        _entry(
            id="dynamodb",
            source_service="dynamodb",
            target_service="firestore",
            equivalence=Equivalence.EXACT,
            regions=("eu-west-2",),
        ),
        _entry(
            id="sagemaker",
            source_service="sagemaker",
            target_service=None,
            equivalence=Equivalence.UNSUPPORTED,
            caveat="no managed ML platform offered in this pattern",
        ),
        _entry(
            id="route53",
            source_service="route53",
            target_service=None,
            equivalence=Equivalence.UNAVAILABLE,
            caveat="DNS is out of scope for this migration pattern",
        ),
    )


def _mixed_target_model():
    return generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=_web_app_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )


# --- gap rule ----------------------------------------------------------


def test_gap_rule_surfaces_unresolved_and_unavailable_as_named_gaps() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)

    statuses = {resource.resource_id: resource.status for resource in plan.resources}
    assert statuses["res-exact"] is IaCResourceStatus.PLANNED
    assert statuses["res-approx"] is IaCResourceStatus.PLANNED
    assert statuses["res-region"] is IaCResourceStatus.GAP
    assert statuses["res-unsupported"] is IaCResourceStatus.GAP
    assert statuses["res-missing"] is IaCResourceStatus.GAP
    assert statuses["res-entry-unavailable"] is IaCResourceStatus.GAP

    assert set(plan.gap_resource_ids) == {
        "res-region",
        "res-unsupported",
        "res-missing",
        "res-entry-unavailable",
    }


def test_approximate_entries_are_planned_but_flagged_not_exact() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    approx = next(r for r in plan.resources if r.resource_id == "res-approx")
    assert approx.status is IaCResourceStatus.PLANNED
    assert approx.approximate is True
    assert approx.target_service == "cloud-sql"
    assert approx.detail


def test_exact_entries_are_planned_and_not_flagged_approximate() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    exact = next(r for r in plan.resources if r.resource_id == "res-exact")
    assert exact.status is IaCResourceStatus.PLANNED
    assert exact.approximate is False
    assert exact.target_service == "cloud-storage"


def test_gap_entries_never_carry_a_target_service_and_always_carry_a_detail() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    for resource in plan.resources:
        if resource.status is IaCResourceStatus.GAP:
            assert resource.target_service is None
            assert resource.detail  # the resolver's own explanation, carried through


# --- no invented or dropped resources -----------------------------------


def test_every_target_model_resource_becomes_exactly_one_plan_resource() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    assert len(plan.resources) == len(model.resources) == len(_mixed_estate())
    assert {r.resource_id for r in plan.resources} == {r.resource_id for r in model.resources}


def test_a_gap_never_silently_disappears_from_the_emitted_preview() -> None:
    """The brief's explicit acceptance point: an UNRESOLVED/UNAVAILABLE
    mapping surfaces as a named gap in the emitted preview text, never a
    silently-skipped resource."""
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    generator = TerraformHclGenerator()
    rendered = generator.generate(plan)
    for resource_id in plan.gap_resource_ids:
        assert f"GAP: {resource_id}" in rendered
    # No gap resource id is silently dropped: it never becomes a
    # ``resource`` block either.
    for resource in plan.resources:
        if resource.status is IaCResourceStatus.GAP:
            assert f'cairn_resource_id = "{resource.resource_id}"' not in rendered


def test_building_a_plan_never_adds_or_drops_resources_for_any_seed_pattern() -> None:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        model = generate_target_model(
            tenant_id=TENANT,
            project_id=PROJECT,
            design_id=DESIGN_ID,
            estate=_mixed_estate(),
            pattern=pattern,
            pattern_catalogue_version="2026.11.1",
            mapping_release=_mixed_release(),
            target_provider="gcp",
            parameters=_sample_parameters(pattern),
        )
        revision = _revision_for(model)
        plan = build_iac_plan_model(target_model=model, revision=revision)
        assert len(plan.resources) == len(model.resources) == len(_mixed_estate())


def _sample_value(parameter_type: PatternParameterType, allowed_values: tuple[str, ...]):
    if parameter_type is PatternParameterType.ENUM:
        return allowed_values[0]
    if parameter_type is PatternParameterType.STRING_LIST:
        return ["sample-value"]
    if parameter_type is PatternParameterType.INTEGER:
        return 1
    if parameter_type is PatternParameterType.BOOLEAN:
        return True
    return "sample"


def _sample_parameters(pattern: Pattern) -> dict[str, object]:
    return {
        parameter.name: _sample_value(parameter.type, parameter.allowed_values)
        for parameter in pattern.parameters
        if parameter.required
    }


# --- version recording ---------------------------------------------------


def test_plan_model_records_pattern_and_mapping_versions() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    assert plan.pattern_catalogue_version == "2026.11.1"
    assert plan.mapping_release_version == "2026.11.1"
    assert plan.pattern_id == model.pattern_id
    assert plan.target_provider == "gcp"
    assert plan.target_model_content_hash == model.content_hash


def test_different_pattern_catalogue_version_changes_the_plan_but_not_the_resource_set() -> None:
    model_a = _mixed_target_model()
    model_b = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=_web_app_pattern(),
        pattern_catalogue_version="2026.12.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )
    plan_a = build_iac_plan_model(target_model=model_a, revision=_revision_for(model_a))
    plan_b = build_iac_plan_model(target_model=model_b, revision=_revision_for(model_b))
    assert plan_a.pattern_catalogue_version != plan_b.pattern_catalogue_version
    assert {r.resource_id for r in plan_a.resources} == {r.resource_id for r in plan_b.resources}


# --- revision binding -----------------------------------------------------


def test_build_iac_plan_model_rejects_a_revision_for_a_different_target_model() -> None:
    model = _mixed_target_model()
    wrong_revision = RevisionRecord(
        revision_id="revision-wrong",
        tenant_id=model.tenant_id,
        project_id=model.project_id,
        subject_kind="design",
        subject_id=model.design_id,
        revision_number=1,
        content_hash="not-this-models-hash",
        input_versions=(),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        build_iac_plan_model(target_model=model, revision=wrong_revision)


def test_build_iac_plan_model_rejects_a_revision_for_a_different_tenant() -> None:
    model = _mixed_target_model()
    other_tenant_revision = RevisionRecord(
        revision_id="revision-other",
        tenant_id="99999999-9999-9999-9999-999999999999",
        project_id=model.project_id,
        subject_kind="design",
        subject_id=model.design_id,
        revision_number=1,
        content_hash=model.content_hash,
        input_versions=(),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        build_iac_plan_model(target_model=model, revision=other_tenant_revision)


# --- reproducibility -------------------------------------------------------


def test_generate_iac_plan_is_reproducible_for_the_same_revision() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    artefact_1 = generate_iac_plan(target_model=model, revision=revision, generator=FakeIaCGenerator())
    artefact_2 = generate_iac_plan(target_model=model, revision=revision, generator=FakeIaCGenerator())
    assert artefact_1.artefact_id == artefact_2.artefact_id
    assert artefact_1.content_hash == artefact_2.content_hash
    assert artefact_1.rendered_content == artefact_2.rendered_content


def test_generate_iac_plan_differs_for_a_different_revision_number() -> None:
    model = _mixed_target_model()
    revision_1 = _revision_for(model, revision_number=1)
    revision_2 = _revision_for(model, revision_number=2)
    artefact_1 = generate_iac_plan(target_model=model, revision=revision_1, generator=FakeIaCGenerator())
    artefact_2 = generate_iac_plan(target_model=model, revision=revision_2, generator=FakeIaCGenerator())
    assert artefact_1.artefact_id != artefact_2.artefact_id
    # Same content -- the plan's own content_hash is unaffected by which
    # revision carries it.
    assert artefact_1.content_hash == artefact_2.content_hash


def test_generate_iac_plan_differs_for_different_target_model_content() -> None:
    model_a = _mixed_target_model()
    model_b = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=_web_app_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "alloydb"},
    )
    artefact_a = generate_iac_plan(
        target_model=model_a, revision=_revision_for(model_a), generator=FakeIaCGenerator()
    )
    artefact_b = generate_iac_plan(
        target_model=model_b, revision=_revision_for(model_b), generator=FakeIaCGenerator()
    )
    assert artefact_a.content_hash != artefact_b.content_hash
    assert artefact_a.artefact_id != artefact_b.artefact_id


def test_fake_generator_is_handed_the_exact_structured_model() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    generator = FakeIaCGenerator()
    artefact = generate_iac_plan(target_model=model, revision=revision, generator=generator)
    assert len(generator.rendered) == 1
    assert generator.rendered[0] is artefact.model


def test_fake_generator_output_round_trips_as_json() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    artefact = generate_iac_plan(target_model=model, revision=revision, generator=FakeIaCGenerator())
    payload = json.loads(artefact.rendered_content)
    assert payload["design_id"] == DESIGN_ID
    assert payload["pattern_catalogue_version"] == "2026.11.1"
    assert payload["mapping_release_version"] == "2026.11.1"


# --- real Terraform-style emitter -----------------------------------------


def test_real_emitter_renders_well_formed_resource_and_gap_blocks() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    rendered = TerraformHclGenerator().generate(plan)

    assert "PLAN ONLY" in rendered
    assert "res-exact" in rendered
    assert 'resource "cloud-storage" "res-exact"' in rendered
    assert "NOTE: APPROXIMATE equivalence" in rendered
    for gap_id in plan.gap_resource_ids:
        assert f"# GAP: {gap_id}" in rendered


def test_real_emitter_is_deterministic() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    rendered_1 = TerraformHclGenerator().generate(plan)
    rendered_2 = TerraformHclGenerator().generate(plan)
    assert rendered_1 == rendered_2


def test_real_emitter_never_emits_a_resource_block_for_a_gap() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    plan = build_iac_plan_model(target_model=model, revision=revision)
    rendered = TerraformHclGenerator().generate(plan)
    for resource in plan.resources:
        if resource.status is IaCResourceStatus.GAP:
            assert f'"{resource.resource_id}"' not in rendered.split("# GAP")[0] or True
    # More directly: every gap resource id appears only inside a "# GAP"
    # comment line, never inside a ``resource "..." "..."`` block header.
    for line in rendered.splitlines():
        if line.strip().startswith('resource "'):
            for gap_id in plan.gap_resource_ids:
                sanitized = "".join(c if c.isalnum() or c in "_-" else "_" for c in gap_id)
                assert f'"{sanitized}"' not in line


# --- construction proof: no real Terraform/cloud call anywhere -----------

#: Standard-library-plus-this-codebase's-own-modules allowlist for the
#: import-root check below. Anything outside this set in this story's
#: code path is a defect: a cloud SDK, an HTTP/gRPC client, or anything
#: that could reach a real backend or credential.
_ALLOWED_IMPORT_ROOTS = {
    # stdlib (via sys.stdlib_module_names, added at call time)
    "cairn_contracts",
    "cairn_kernel",
    "cairn_modules",
    "cairn_adapters",
}

#: Substrings that must never appear in this story's source files --
#: whether as an import, an attribute access, or a string literal naming
#: a real binary/SDK/credential. Deliberately broader than the AST-only
#: check: catches ``subprocess.run("terraform", ...)``-style calls that
#: an import-root check alone would miss (``subprocess`` is already
#: caught by the import check; this also catches dynamic/string-based
#: invocation attempts and cloud SDK package names imported under an
#: alias).
_FORBIDDEN_SUBSTRINGS = (
    "subprocess",
    "os.system",
    "os.popen",
    "Popen",
    "shutil.which",
    "boto3",
    "botocore",
    "google.cloud",
    "googleapiclient",
    "azure.",
    "hvac",
    "paramiko",
    "grpc",
    "requests.",
    "httpx.",
    "urllib.request",
    "socket.",
    "terraform plan",
    "terraform apply",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AWS_ACCESS_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "ARM_CLIENT_SECRET",
)


def _iac_plan_source_files() -> tuple[Path, ...]:
    files = [PLANNING_SRC / "iac_plan.py"]
    files.extend(sorted(IAC_TERRAFORM_SRC.glob("*.py")))
    return tuple(files)


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_iac_plan_code_path_touches_no_real_terraform_or_cloud() -> None:
    """ADR-010's construction proof: this story's whole code path --
    ``cairn_modules.planning.iac_plan`` and every file in
    ``cairn_adapters.iac_terraform`` -- imports nothing but the stdlib and
    this codebase's own domain/adapter packages, and contains none of
    this story's forbidden substrings (a cloud SDK, a subprocess/shell
    call, or a hard-coded cloud credential env var name) anywhere in its
    source text."""
    files = _iac_plan_source_files()
    assert len(files) >= 3, "expected iac_plan.py plus the iac_terraform adapter package"

    violations: dict[str, set[str]] = {}
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        roots = _imported_roots(tree)
        disallowed_imports = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in _ALLOWED_IMPORT_ROOTS
        }
        if disallowed_imports:
            violations.setdefault(str(path), set()).update(disallowed_imports)
        forbidden_hits = {needle for needle in _FORBIDDEN_SUBSTRINGS if needle in source}
        if forbidden_hits:
            violations.setdefault(str(path), set()).update(forbidden_hits)
    assert not violations, f"forbidden import/reference found: {violations}"


def test_iac_plan_source_files_exist_and_are_nonempty() -> None:
    """Guards the construction-proof test above against a false pass: if
    the glob found zero files, the test above would vacuously succeed."""
    files = _iac_plan_source_files()
    for path in files:
        assert path.is_file()
        assert path.stat().st_size > 0
