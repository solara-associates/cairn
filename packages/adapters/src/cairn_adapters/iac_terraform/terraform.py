"""R2-07: the real ``IaCGeneratorPort`` adapter -- a deterministic
Terraform-style HCL plan-preview text emitter.

Spec §5.4: ``IaCGeneratorPort | planning | Terraform emitter, fake``.
This is the "Terraform emitter" half; ``cairn_adapters.iac_terraform.fake``
is the "fake" half.

This is a **preview**, not an executor. ADR-010 makes this load-bearing,
not a convenience: this module never shells out to anything, invokes no
Terraform binary, no cloud SDK and no cloud credential of any kind -- it
is a pure function of ``cairn_modules.planning.iac_plan.IaCPlanModel``
that returns a ``str``.
Nothing here is, or could become, a real `plan`/`apply` run: there is
no provider block pointing at a real backend, no state
file, and no network call. This also means this emitter shares nothing
-- no binary, no backend, no state, no credential -- with
``infra/terraform/`` (CAIRN's own infrastructure, applied by a human
maintainer running a real ``terraform`` binary by hand or in CI); this
story's output is Terraform-shaped *text* describing the customer's
future environment, for a human to read, never something CAIRN itself
runs.

The emitter is a pure function of the structured model -- no timestamps,
no randomness, no non-deterministic ordering (the model's resources are
already sorted by ``resource_id`` by the generator). Two calls with the
same model always produce byte-identical text. A ``GAP`` entry never
becomes a ``resource`` block; it is rendered as its own clearly labelled
comment block instead, carrying the resolver's own explanation -- never
silently dropped from the preview.
"""

from __future__ import annotations

from cairn_modules.planning.iac_plan import (
    IAC_PLAN_DISCLAIMER,
    IaCPlanModel,
    IaCResourcePlan,
    IaCResourceStatus,
)

_INDENT = "  "


def _sanitize_identifier(value: str) -> str:
    """Terraform identifiers are restricted to letters, digits, ``_`` and
    ``-``; a resource id may contain other characters (e.g. ``:``,
    ``/``), so this maps every other character to ``_`` -- deterministic,
    one-way, never ambiguous between two distinct inputs that already
    differ only in an allowed character."""
    return "".join(character if character.isalnum() or character in "_-" else "_" for character in value)


def _resource_block(resource: IaCResourcePlan) -> str:
    local_name = _sanitize_identifier(resource.resource_id)
    resource_type = _sanitize_identifier(resource.target_service or "unknown_resource")
    source_comment = (
        f"# source: {resource.source_provider}:{resource.source_service}"
        f" (resource_id={resource.resource_id})"
    )
    lines = [source_comment]
    if resource.approximate:
        lines.append("# NOTE: APPROXIMATE equivalence -- not a like-for-like match.")
    if resource.detail:
        lines.append(f"# detail: {resource.detail}")
    lines.append(f'resource "{resource_type}" "{local_name}" {{')
    lines.append(f'{_INDENT}# target_provider = "{resource.target_provider}"')
    lines.append(f'{_INDENT}# cairn_resource_id = "{resource.resource_id}"')
    lines.append("}")
    return "\n".join(lines)


def _gap_block(resource: IaCResourcePlan) -> str:
    gap_comment = (
        f"# GAP: {resource.resource_id} ({resource.source_provider}:{resource.source_service})"
        " -- no resource block emitted."
    )
    return "\n".join([gap_comment, f"# reason: {resource.detail}"])


def _block_for(resource: IaCResourcePlan) -> str:
    if resource.status is IaCResourceStatus.GAP:
        return _gap_block(resource)
    return _resource_block(resource)


def _header(model: IaCPlanModel) -> str:
    return "\n".join(
        [
            f"# {IAC_PLAN_DISCLAIMER}",
            f"# design_id = {model.design_id}",
            f"# revision_id = {model.revision_id}",
            f"# revision_number = {model.revision_number}",
            f"# pattern_id = {model.pattern_id}",
            f"# pattern_catalogue_version = {model.pattern_catalogue_version}",
            f"# mapping_release_version = {model.mapping_release_version}",
            f"# target_provider = {model.target_provider}",
            f"# gap_count = {len(model.gap_resource_ids)}",
        ]
    )


class TerraformHclGenerator:
    """The real ``IaCGeneratorPort`` adapter: deterministic Terraform-
    style HCL plan-preview text."""

    def generate(self, plan: IaCPlanModel) -> str:
        blocks = [_header(plan)]
        blocks.extend(_block_for(resource) for resource in plan.resources)
        return "\n\n".join(blocks) + "\n"


__all__ = ["TerraformHclGenerator"]
