"""R2-07: smoke tests for the real Terraform-style HCL plan-preview
emitter.

Deliberately does not pin exact HCL bytes beyond what the acceptance
text itself requires (a disclaimer banner, a visible gap marker, no
resource block for a gap) -- the structured-model-level acceptance tests
(gap rule, no-invented/dropped resources, reproducibility, version
recording) live in ``packages/modules/tests/test_iac_plan.py`` against
the fake adapter, per this story's own "never assert on the real
emitter's exact bytes" instruction (the same discipline 704's
``test_diagram_drawio.py`` follows).
"""

from __future__ import annotations

from cairn_adapters.iac_terraform import FakeIaCGenerator, TerraformHclGenerator
from cairn_modules.planning.iac_plan import IaCPlanModel, IaCResourcePlan, IaCResourceStatus


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
        "target_model_content_hash": "abc123",
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


def test_renders_a_plan_only_disclaimer() -> None:
    renderer = TerraformHclGenerator()
    text = renderer.generate(_model())
    assert "PLAN ONLY" in text
    assert "Not executed" in text
    assert "Not applied" in text


def test_renders_a_resource_block_for_a_planned_entry() -> None:
    renderer = TerraformHclGenerator()
    text = renderer.generate(_model())
    assert 'resource "cloud-storage" "res-1"' in text
    assert 'cairn_resource_id = "res-1"' in text


def test_renders_a_named_gap_for_a_gap_entry_with_no_resource_block() -> None:
    renderer = TerraformHclGenerator()
    text = renderer.generate(_model())
    assert "# GAP: res-2" in text
    assert "no mapping entry" in text
    assert 'cairn_resource_id = "res-2"' not in text


def test_rendering_is_a_pure_function_of_the_model() -> None:
    renderer = TerraformHclGenerator()
    model = _model()
    assert renderer.generate(model) == renderer.generate(model)


def test_no_invented_or_dropped_resources_in_the_rendered_text() -> None:
    model = _model()
    renderer = TerraformHclGenerator()
    text = renderer.generate(model)
    for resource in model.resources:
        assert resource.resource_id in text


def test_fake_generator_records_the_exact_model_handed_to_it() -> None:
    model = _model()
    generator = FakeIaCGenerator()
    generator.generate(model)
    assert generator.rendered == [model]


def test_fake_generator_output_is_deterministic() -> None:
    model = _model()
    generator = FakeIaCGenerator()
    assert generator.generate(model) == generator.generate(model)
