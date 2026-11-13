from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import MappingUnavailableError, ValidationError
from cairn_modules.mappings import InMemoryMappingRegistry, load_mapping_release
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

    assert release.version == "2026.11.1"
    assert release.status is ReleaseStatus.PUBLISHED
    assert len(release.entries) == 8
    s3 = next(entry for entry in release.entries if entry.id == "s3-to-gcs")
    assert s3.equivalence is Equivalence.APPROXIMATE
    assert s3.caveat
    assert s3.regions == ("europe-west2", "us-central1", "asia-south1")


def test_registry_loads_seed_and_retrieves_release() -> None:
    registry = InMemoryMappingRegistry()

    release = registry.load(SEED_PATH)

    assert registry.versions() == ("2026.11.1",)
    assert registry.get("2026.11.1") is release
    assert len(registry) == 1


def test_unknown_release_is_unavailable() -> None:
    registry = InMemoryMappingRegistry()

    with pytest.raises(MappingUnavailableError):
        registry.get("2026.12.1")


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


def test_published_release_is_immutable() -> None:
    registry = InMemoryMappingRegistry()
    registry.publish(_release())
    changed = _payload()
    changed["entries"][0]["caveat"] = "A different caveat"

    with pytest.raises(ValidationError, match="immutable"):
        registry.publish(_release(changed))

    assert registry.get("2026.11.1").entries[0].caveat == "Consistency semantics differ"


def test_identical_republish_is_idempotent() -> None:
    registry = InMemoryMappingRegistry()
    release = _release()

    registry.publish(release)
    registry.publish(_release())

    assert registry.versions() == ("2026.11.1",)
    assert registry.get("2026.11.1").content_hash == release.content_hash


def test_correction_requires_new_version() -> None:
    registry = InMemoryMappingRegistry()
    registry.publish(_release())
    corrected = _payload()
    corrected["version"] = "2026.11.2"
    corrected["entries"][0]["caveat"] = "A corrected caveat"

    registry.publish(_release(corrected))

    assert registry.versions() == ("2026.11.1", "2026.11.2")


def test_unpublished_release_cannot_be_loaded() -> None:
    registry = InMemoryMappingRegistry()
    draft = _payload()
    draft["status"] = "DRAFT"

    with pytest.raises(ValidationError, match="PUBLISHED"):
        registry.publish(_release(draft))


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
