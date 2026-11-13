from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cairn_contracts.posture import ControlCatalogueRelease, ReleaseStatus, Severity
from cairn_kernel.errors import ControlUnavailableError, ValidationError
from cairn_modules.posture import InMemoryControlCatalogue, load_control_catalogue_release
from pydantic import ValidationError as PydanticValidationError

REPO_ROOT = Path(__file__).parents[3]
SEED_PATH = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"


def _payload() -> dict[str, Any]:
    return {
        "version": "2026.11.1",
        "released_at": "2026-11-13T00:00:00Z",
        "status": "PUBLISHED",
        "controls": [
            {
                "id": "gcp-cis-1.1",
                "provider": "gcp",
                "benchmark": "CIS Google Cloud Platform Foundation Benchmark v2.0",
                "benchmark_section": "1.1",
                "category": "Identity and Access Management",
                "title": "Ensure that corporate login credentials are used instead of Gmail accounts",
                "description": "Project members should use managed identities.",
                "rationale": "Personal accounts cannot be centrally deprovisioned.",
                "remediation": "Migrate all members to Cloud Identity or federated SSO.",
                "severity": "HIGH",
                "automated": True,
            }
        ],
    }


def _release(payload: dict[str, Any] | None = None) -> ControlCatalogueRelease:
    return ControlCatalogueRelease.model_validate(payload or _payload())


def test_seed_release_loads() -> None:
    release = load_control_catalogue_release(SEED_PATH)

    assert release.version == "2026.11.1"
    assert release.status is ReleaseStatus.PUBLISHED
    assert len(release.controls) == 7
    ssh = next(control for control in release.controls if control.id == "gcp-cis-3.6")
    assert ssh.severity is Severity.CRITICAL
    assert ssh.category == "Networking"


def test_registry_loads_seed_and_retrieves_release() -> None:
    catalogue = InMemoryControlCatalogue()

    release = catalogue.load(SEED_PATH)

    assert catalogue.versions() == ("2026.11.1",)
    assert catalogue.get("2026.11.1") is release
    assert len(catalogue) == 1


def test_get_control_resolves_a_specific_version() -> None:
    catalogue = InMemoryControlCatalogue()
    catalogue.load(SEED_PATH)

    control = catalogue.get_control("2026.11.1", "gcp-cis-5.1")

    assert control.title.startswith("Ensure that Cloud Storage buckets")


def test_get_control_unknown_control_is_unavailable() -> None:
    catalogue = InMemoryControlCatalogue()
    catalogue.load(SEED_PATH)

    with pytest.raises(ControlUnavailableError):
        catalogue.get_control("2026.11.1", "does-not-exist")


def test_unknown_release_is_unavailable() -> None:
    catalogue = InMemoryControlCatalogue()

    with pytest.raises(ControlUnavailableError):
        catalogue.get("2026.12.1")


def test_content_hash_is_stable_across_round_trip() -> None:
    release = _release()

    reparsed = ControlCatalogueRelease.model_validate_json(release.model_dump_json())

    assert reparsed.content_hash == release.content_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": "2026-11.1"},
        {"released_at": "2026-11-13T00:00:00"},
        {"status": "UNKNOWN"},
        {"controls": []},
    ],
)
def test_release_rejects_invalid_top_level_fields(overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload.update(overrides)

    with pytest.raises(PydanticValidationError):
        ControlCatalogueRelease.model_validate(payload)


@pytest.mark.parametrize(
    "control_overrides",
    [
        {"title": ""},
        {"severity": "EXTREME"},
        {"provider": "  "},
        {"description": ""},
    ],
)
def test_control_rejects_invalid_fields(control_overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload["controls"][0].update(control_overrides)

    with pytest.raises(PydanticValidationError):
        ControlCatalogueRelease.model_validate(payload)


def test_release_rejects_duplicate_control_ids() -> None:
    payload = _payload()
    payload["controls"].append(deepcopy(payload["controls"][0]))

    with pytest.raises(PydanticValidationError):
        ControlCatalogueRelease.model_validate(payload)


def test_published_release_is_immutable() -> None:
    catalogue = InMemoryControlCatalogue()
    catalogue.publish(_release())
    changed = _payload()
    changed["controls"][0]["title"] = "A different title"

    with pytest.raises(ValidationError, match="immutable"):
        catalogue.publish(_release(changed))

    assert catalogue.get("2026.11.1").controls[0].title == _payload()["controls"][0]["title"]


def test_identical_republish_is_idempotent() -> None:
    catalogue = InMemoryControlCatalogue()
    release = _release()

    catalogue.publish(release)
    catalogue.publish(_release())

    assert catalogue.versions() == ("2026.11.1",)
    assert catalogue.get("2026.11.1").content_hash == release.content_hash


def test_correction_requires_new_version() -> None:
    catalogue = InMemoryControlCatalogue()
    catalogue.publish(_release())
    corrected = _payload()
    corrected["version"] = "2026.11.2"
    corrected["controls"][0]["title"] = "A corrected title"

    catalogue.publish(_release(corrected))

    assert catalogue.versions() == ("2026.11.1", "2026.11.2")


def test_unpublished_release_cannot_be_loaded() -> None:
    catalogue = InMemoryControlCatalogue()
    draft = _payload()
    draft["status"] = "DRAFT"

    with pytest.raises(ValidationError, match="PUBLISHED"):
        catalogue.publish(_release(draft))


def test_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read"):
        load_control_catalogue_release(tmp_path / "missing.yaml")


def test_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("version: [unterminated", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid YAML"):
        load_control_catalogue_release(path)


def test_loader_rejects_non_mapping_document(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="must be a YAML mapping"):
        load_control_catalogue_release(path)


def test_loader_wraps_schema_errors(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("version: not-a-version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid control catalogue release"):
        load_control_catalogue_release(path)
