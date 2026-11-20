"""Demo pack companion script for use case 1 (landing zone deployment).

Runs the real R2 design pipeline (target-model generation against the
published pattern catalogue and mapping release, then the real
`TerraformHclGenerator`) for the `landing-zone` pattern, and prints the
resulting Terraform plan *preview* -- never a `terraform plan`/`apply`
run, never a cloud SDK call or credential (ADR-010; see
`cairn_modules.planning.iac_plan`'s own module docstring for the
construction proof).

Honest limit, found while building this pack and stated here because the
demo pack says to state it plainly: this script does **not** reuse the
use-case-3 demo's uploaded RVTools/HVTools estate. Doing so was tried
first -- every one of those four on-prem VM resources comes back
`UNRESOLVED` (a real, correctly-reported `GAP`, not a bug): the
published mapping release (`mappings/service-map.yaml`) only covers
cloud-to-cloud service equivalences (AWS/Azure -> GCP), not an on-prem
inventory format, so there is nothing in today's catalogue for an
RVTools/HVTools-derived resource to resolve against. Rather than present
an all-GAP landing-zone demo (technically real, but not what "landing
zone deployment" should look like to an audience), this script instead
synthesizes a small, explicitly-named demo estate of two typical
landing-zone candidate workloads (one S3 bucket, one DynamoDB table) that
*do* have real entries in the published mapping release, so the audience
sees actual resolved Terraform resource blocks, not an all-gap screen.
Say this plainly if asked why the demo estate differs from use case 3's.

Run: uv run python docs/demo/uc1_verify_iac_plan.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from cairn_adapters.iac_terraform.terraform import TerraformHclGenerator
from cairn_contracts.estate import FactStatus, Resource
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.patterns import load_pattern_catalogue
from cairn_modules.design.target_model import generate_target_model
from cairn_modules.mappings import load_mapping_release
from cairn_modules.planning.iac_plan import generate_iac_plan

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERN_CATALOGUE_DIR = REPO_ROOT / "patterns"
MAPPING_RELEASE_PATH = REPO_ROOT / "mappings" / "service-map.yaml"

TENANT = "demo-tenant"
PROJECT = "uc1-landing-zone-demo"
MOMENT = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)


def _resource(
    resource_id: str,
    provider: str,
    service: str,
    region: str,
    resource_type: str,
    native_id: str,
    name: str,
) -> Resource:
    return Resource(
        resource_id=resource_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        provider=provider,
        account_id="demo-aws-acct",
        region=region,
        service=service,
        resource_type=resource_type,
        native_id=native_id,
        name=name,
        tags={"env": "prod"},
        facts={},
        provenance=(),
        status=FactStatus.OBSERVED,
    )


# Named, synthetic demo estate -- see the module docstring for why this
# isn't the use-case-3 fixture estate.
DEMO_ESTATE = (
    _resource(
        "res-1",
        "aws",
        "s3",
        "europe-west2",
        "bucket",
        "arn:aws:s3:::demo-app-data",
        "demo-app-data",
    ),
    _resource(
        "res-2",
        "aws",
        "dynamodb",
        "europe-west2",
        "table",
        "arn:aws:dynamodb:eu-west-2:111111111111:table/demo-sessions",
        "demo-sessions",
    ),
)


def main() -> None:
    catalogue = load_pattern_catalogue(
        PATTERN_CATALOGUE_DIR, version="2026.11.1", released_at=MOMENT
    )
    pattern = next(p for p in catalogue.patterns if p.id == "landing-zone")
    mapping_release = load_mapping_release(MAPPING_RELEASE_PATH)

    target_model = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id="uc1-design-1",
        estate=DEMO_ESTATE,
        pattern=pattern,
        pattern_catalogue_version=catalogue.version,
        mapping_release=mapping_release,
        target_provider="gcp",
        parameters={
            "allowed_regions": ["europe-west2"],
            "environments": ["dev", "prod"],
            "residency_sweep_on_apply": True,
            "network_topology": "hub_spoke",
        },
    )
    print(f"pattern: {pattern.id} ({pattern.name})")
    print("target model resources:")
    for entry in target_model.resources:
        print(
            f"  {entry.resource_id}: {entry.status.value}"
            + (f" -- {entry.reason}" if entry.reason else "")
        )

    revision = RevisionRecord(
        revision_id=str(uuid.uuid4()),
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind="design",
        subject_id="uc1-design-1",
        revision_number=1,
        content_hash=target_model.content_hash,
        input_versions=(
            ("pattern_id", target_model.pattern_id),
            ("pattern_catalogue_version", catalogue.version),
            ("mapping_release_version", mapping_release.version),
        ),
        created_by="demo",
        created_at=MOMENT,
    )
    artefact = generate_iac_plan(
        target_model=target_model, revision=revision, generator=TerraformHclGenerator()
    )
    assert "GAP" not in artefact.rendered_content.split("gap_count = ")[1][:2], (
        "expected zero gaps for the demo estate"
    )
    print("\n--- rendered Terraform plan preview (PLAN ONLY -- not applied) ---")
    print(artefact.rendered_content)


if __name__ == "__main__":
    main()
