from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import ValidationError
from cairn_modules.mappings import load_mapping_release
from pydantic import ValidationError as PydanticValidationError

REPO_ROOT = Path(__file__).parents[3]
SEED_PATH = REPO_ROOT / "mappings" / "service-map.yaml"


def _payload() -> dict[str, Any]:
    return {
        "version": "2026.11.1",
        "released_at": "2026-11-09T00:00:00Z",
        "status": "PUBLISHED",
        "entries": [
            {
                "id": "s3-to-gcs",
                "source_provider": "aws",
                "source_service": "s3",
                "target_provider": "gcp",
                "target_service": "cloud-storage",
                "equivalence": "APPROXIMATE",
                "caveat": "Consistency semantics differ",
                "regions": ["europe-west2"],
                "evidence": "public documentation",
            }
        ],
    }


def _release(payload: dict[str, Any] | None = None) -> MappingRelease:
    return MappingRelease.model_validate(payload or _payload())


def test_seed_release_loads() -> None:
    release = load_mapping_release(SEED_PATH)

    assert release.version == "2026.11.2"
    # R2-02: this is the real top-40-per-pilot-pair candidate content,
    # proposed via MappingRepository.propose and currently IN_REVIEW
    # (docs/specs/mapping-seed-review.md). MappingRelease.content_hash is
    # computed assuming ``status=DRAFT`` always (see
    # cairn_modules.mappings.domain's module docstring), which is also the
    # only legal status a release may carry when passed to ``propose()`` --
    # so the committed seed file's own top-level ``status`` field is DRAFT,
    # not a claim about the real release's current ADR-004 workflow status.
    assert release.status is ReleaseStatus.DRAFT
    assert len(release.entries) >= 40
    s3 = next(entry for entry in release.entries if entry.id == "s3-to-gcs")
    assert s3.equivalence is Equivalence.APPROXIMATE
    assert s3.caveat
    assert s3.regions == ("europe-west2", "us-central1", "asia-south1")


def test_content_hash_is_stable_across_round_trip() -> None:
    release = _release()

    reparsed = MappingRelease.model_validate_json(release.model_dump_json())

    assert reparsed.content_hash == release.content_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": "2026-11.1"},
        {"released_at": "2026-11-09T00:00:00"},
        {"status": "UNKNOWN"},
        {"entries": []},
    ],
)
def test_release_rejects_invalid_top_level_fields(overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload.update(overrides)

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


@pytest.mark.parametrize(
    "entry_overrides",
    [
        {"caveat": None},
        {"target_service": None},
        {"evidence": "  "},
        {"regions": ["europe-west2", "europe-west2"]},
        {"source_provider": ""},
    ],
)
def test_entry_rejects_invalid_fields(entry_overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload["entries"][0].update(entry_overrides)

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_entry_requires_target_service_for_exact_mapping() -> None:
    payload = _payload()
    payload["entries"][0].update(
        {"equivalence": "EXACT", "target_service": None, "caveat": None}
    )

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_release_rejects_duplicate_entry_ids() -> None:
    payload = _payload()
    payload["entries"].append(deepcopy(payload["entries"][0]))

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read"):
        load_mapping_release(tmp_path / "missing.yaml")


def test_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("version: [unterminated", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid YAML"):
        load_mapping_release(path)


def test_loader_rejects_non_mapping_document(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="must be a YAML mapping"):
        load_mapping_release(path)


def test_loader_wraps_schema_errors(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("version: not-a-version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid mapping release"):
        load_mapping_release(path)


# --- R2-02: coverage/schema checks on the real seed candidate ---------------
#
# These assert properties of the real `mappings/service-map.yaml` content
# that aren't already implied by `test_seed_release_loads` succeeding at all
# (which already proves "every entry valid" via `MappingEntry`'s own
# validators, including "every non-exact entry has a caveat" --
# `MappingEntry._validate_equivalence` raises otherwise). ADR-017's
# clean-room rule is the one property the schema itself cannot check: no
# `evidence` string may name a reference-portfolio repository, since that
# would cite a non-public, non-citable source for a judgement this story
# must ground in public vendor documentation only.

# Every repository named in CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md section
# 17's source analysis and in `docs/specs/reference-register.md` --
# ADR-017: "design evidence only... nothing is pasted into CAIRN," which
# this story's own brief extends to citation: a reference-portfolio
# repository is never a citable public source for an `evidence` string.
REFERENCE_PORTFOLIO_REPOSITORIES: tuple[str, ...] = (
    "gcp-cost-posture-foundation",
    "Meridian",
    "infracc",
    "aws_to_gcp_cost",
    "cloud-cost-genius-convert",
    "autoinfra_aws",
    "autoinfra",
    "vuln-reduction-platform",
    "consent-ledger-compliance-poc",
    "nelc",
    "cloudshift_v2",
    "cloudshift",
    "refactor2",
    "refactor",
    "newrefactor",
    "anytoany",
    "agent-assess",
    "drawio-gen",
    "uk-landing-zone-accelerator",
    "mlops-aws",
    "mlops",
    "llmops",
    "cockpit",
    "byomcp",
    "nexus-agentic",
    "martech",
    "punjab",
    "prism",
    "planetpayment",
    "mmopt2",
    "mmopt3",
    "atttick",
    "feedback",
    "aival2",
    "leadforge",
    "coderev",
    "barq",
    "core_banking_ldm_accelerator",
    "fhir-omop",
    "taa",
    "raas",
)


def test_seed_entry_count_reaches_the_adr_004_top_40_floor() -> None:
    release = load_mapping_release(SEED_PATH)

    assert len(release.entries) >= 40


def test_seed_every_non_exact_entry_has_a_caveat() -> None:
    # Belt-and-braces alongside the schema-level guarantee: makes the
    # ADR-004 requirement an explicit, separately readable assertion about
    # the real candidate content rather than only an implication of
    # `test_seed_release_loads` not raising.
    release = load_mapping_release(SEED_PATH)

    for entry in release.entries:
        if entry.equivalence is not Equivalence.EXACT:
            assert entry.caveat, f"{entry.id}: non-exact entry must carry a caveat"


def test_seed_no_evidence_string_names_a_reference_portfolio_repository() -> None:
    release = load_mapping_release(SEED_PATH)

    for entry in release.entries:
        lowered = entry.evidence.lower()
        for repo in REFERENCE_PORTFOLIO_REPOSITORIES:
            assert repo.lower() not in lowered, (
                f"{entry.id}: evidence {entry.evidence!r} names reference repository {repo!r}"
                " -- ADR-017 forbids citing a reference-portfolio repository as a source;"
                " evidence must name public vendor documentation only"
            )


def test_seed_gap_entries_are_unresolved_not_guessed() -> None:
    # ADR-004: "gaps are labelled UNRESOLVED; gaps, not guessed." The
    # shipped `Equivalence` enum (cairn_contracts.estate.model) has no
    # `UNRESOLVED` member -- it has `UNSUPPORTED`, which this story uses as
    # that same concept (see docs/specs/mapping-seed-review.md). An honest
    # gap entry never names a guessed `target_service`.
    release = load_mapping_release(SEED_PATH)

    gaps = [entry for entry in release.entries if entry.equivalence is Equivalence.UNSUPPORTED]
    assert len(gaps) >= 1
    for entry in gaps:
        assert entry.target_service is None, f"{entry.id}: an unresolved gap must not guess a target_service"
        assert entry.caveat


def test_seed_covers_both_assumed_pilot_provider_pairs() -> None:
    # docs/pilot/, docs/residency/uk-residency-matrix.md and spec section
    # 7.2's own illustrative examples already assume AWS->GCP and
    # Azure->GCP; this story replaces the illustrative file's content, not
    # which pairs it targets.
    release = load_mapping_release(SEED_PATH)

    pairs = {(entry.source_provider, entry.target_provider) for entry in release.entries}
    assert ("aws", "gcp") in pairs
    assert ("azure", "gcp") in pairs
