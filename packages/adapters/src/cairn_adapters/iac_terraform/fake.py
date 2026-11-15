"""R2-07: the fake/deterministic-test ``IaCGeneratorPort`` adapter.

Spec §5.4: ``IaCGeneratorPort | planning | Terraform emitter, fake``.
This is the "fake" half. Tests assert on the structured pre-emission
``IaCPlanModel`` the generator built (``cairn_modules.planning.
iac_plan``), never on this adapter's output bytes or the real emitter's
HCL text, both of which would be brittle. This adapter exists so
``generate_iac_plan`` has a generator to call in tests without depending
on text formatting at all; its output is a plain, deterministic
canonical-JSON projection of the model, useful for asserting "the
generator was in fact called with this exact model" and for the
reproducibility test (same model -> byte-identical rendered content).
Like the real emitter, this adapter touches no Terraform binary, no
cloud SDK and no cloud credential -- it is a pure in-process function.
"""

from __future__ import annotations

import json

from cairn_modules.planning.iac_plan import IaCPlanModel, IaCResourcePlan


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


class FakeIaCGenerator:
    """Deterministic ``IaCGeneratorPort`` for tests: records every
    ``IaCPlanModel`` it was asked to render, and returns a stable
    canonical-JSON string for it -- the same model always renders to the
    identical string."""

    def __init__(self) -> None:
        self.rendered: list[IaCPlanModel] = []

    def generate(self, plan: IaCPlanModel) -> str:
        self.rendered.append(plan)
        payload = {
            "design_id": plan.design_id,
            "revision_id": plan.revision_id,
            "revision_number": plan.revision_number,
            "pattern_id": plan.pattern_id,
            "pattern_catalogue_version": plan.pattern_catalogue_version,
            "mapping_release_version": plan.mapping_release_version,
            "target_provider": plan.target_provider,
            "target_model_content_hash": plan.target_model_content_hash,
            "resources": [_resource_to_jsonable(resource) for resource in plan.resources],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = ["FakeIaCGenerator"]
