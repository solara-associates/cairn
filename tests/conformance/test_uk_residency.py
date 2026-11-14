"""R0-20 gate 11: UK data, backup, key and support-access residency.

Allan's decision (2026-11-14, recorded in
``docs/residency/uk-residency-matrix.md``):

1. Customer data and backups stay in the UK only -- primary and backups
   in ``europe-west2`` (London), multi-zone, with no copy outside the UK.
   GCP has a single UK region, so region-level disaster recovery inside
   the UK is not available; resilience is multi-zone within London.
2. Encryption keys stay in the UK only.
3. Support access to customer data is not restricted by location -- any
   authorised staff member may access it from anywhere -- but every
   access must be logged, approved and auditable.

(1) and (2) are checked here against the actual Terraform, not just
read back from a comment. (3) has no location restriction to check, so
it is checked as a negative-space guard instead: no human or group
principal may be granted IAM access to a data-holding resource directly.
Today no such grant exists anywhere in ``infra/terraform`` -- the moment
one is added, this test fails until it goes through an audited,
approved support-access path (not yet built; flagged in the residency
matrix for a future story, since none of R0-R5's stories in
``CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md`` owns building that path).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
TERRAFORM_ROOT = REPO_ROOT / "infra" / "terraform"

_HUMAN_PRINCIPAL = re.compile(r'"(?:user|group|domain):')


def _tf_files() -> list[Path]:
    return sorted(TERRAFORM_ROOT.rglob("*.tf"))


def test_cloudsql_backups_are_pinned_to_the_instance_region() -> None:
    """Backup/PITR storage must not fall back to Cloud SQL's unpinned
    default -- it must read the same ``var.region`` the instance itself
    uses, so backup storage can never silently land outside the UK.
    """
    main_tf = (TERRAFORM_ROOT / "modules" / "cairn-data" / "main.tf").read_text()
    backup_block = re.search(r"backup_configuration\s*\{([^}]*)\}", main_tf, re.DOTALL)
    assert backup_block is not None, "google_sql_database_instance.cairn must declare backup_configuration"
    assert "location" in backup_block.group(1), (
        "backup_configuration must pin `location` explicitly -- "
        "Cloud SQL's unpinned default is not a UK residency guarantee"
    )
    assert "var.region" in backup_block.group(1), (
        "backup_configuration.location must reference var.region, the same "
        "declaration the instance and every other UK-pinned resource use"
    )


def test_evidence_signing_key_is_pinned_to_the_uk_region_with_no_export_grant() -> None:
    """The KMS key ring/key must resolve to ``var.region``, and no IAM
    binding on the key may grant an export-capable role.
    """
    main_tf = (TERRAFORM_ROOT / "modules" / "cairn-evidence" / "main.tf").read_text()

    # Non-greedy up to a closing brace on its own line -- a plain "[^}]*"
    # would stop early at the "}" inside "${var.environment}" instead.
    key_ring_block = re.search(r'resource "google_kms_key_ring" "evidence" \{(.*?)\n\}', main_tf, re.DOTALL)
    assert key_ring_block is not None
    assert "location = var.region" in key_ring_block.group(1)

    for role_match in re.finditer(r'role\s*=\s*"([^"]+)"', main_tf):
        role = role_match.group(1)
        assert "kms" not in role.lower() or role == "roles/cloudkms.signerVerifier", (
            f"unexpected KMS role grant {role!r} on the evidence key -- only "
            "signerVerifier is permitted; nothing may grant export"
        )


def test_no_human_or_group_principal_is_granted_direct_data_access() -> None:
    """No IAM binding anywhere in Terraform may grant a human or group
    principal (as opposed to a service account) access to anything --
    support access must go through an audited, approved path, which does
    not exist in this repo yet. This is deliberately broad: it is a
    negative-space guard against an ungated support-access grant being
    added quietly, not a scoped check on one resource.
    """
    offending: list[str] = []
    for path in _tf_files():
        text = path.read_text()
        if _HUMAN_PRINCIPAL.search(text):
            offending.append(str(path.relative_to(REPO_ROOT)))

    assert not offending, (
        "human/group IAM principal found in Terraform (support access must be "
        "logged, approved and auditable -- no such path exists yet, so no "
        "direct grant is permitted): " + ", ".join(offending)
    )
