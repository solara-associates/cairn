from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.mapping.pattern import Pattern, PatternCategory, PatternReleaseStatus
from cairn_kernel.errors import NotFoundError, ValidationError
from cairn_modules.design import InMemoryPatternRepository, load_pattern, load_pattern_catalogue

REPO_ROOT = Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"
SEED_VERSION = "2026.11.1"
SEED_RELEASED_AT = datetime(2026, 11, 15, tzinfo=UTC)


def _seed_pattern_files() -> list[Path]:
    return sorted(PATTERNS_DIR.glob("*.yaml"))


def _seed_release(status: PatternReleaseStatus = PatternReleaseStatus.DRAFT):
    return load_pattern_catalogue(
        PATTERNS_DIR, version=SEED_VERSION, released_at=SEED_RELEASED_AT, status=status
    )


# ---------------------------------------------------------------------------
# Loader round-trip: every seed file under patterns/ loads as a valid Pattern.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pattern_path", _seed_pattern_files(), ids=lambda p: p.stem)
def test_loader_round_trips_every_seed_file(pattern_path: Path) -> None:
    pattern = load_pattern(pattern_path)

    reloaded = Pattern.model_validate_json(pattern.model_dump_json())
    assert reloaded == pattern

    # The acceptance criteria themselves: a real schema, not placeholder text.
    assert pattern.parameters
    assert pattern.preconditions
    assert pattern.outputs
    assert pattern.validation_rules
    assert pattern.evidence


def test_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read"):
        load_pattern(tmp_path / "missing.yaml")


def test_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("id: [unterminated", encoding="utf-8")
    with pytest.raises(ValidationError, match="invalid YAML"):
        load_pattern(path)


def test_loader_rejects_non_mapping_document(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- id\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="must be a YAML mapping"):
        load_pattern(path)


def test_loader_wraps_schema_errors(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("id: only-an-id\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="invalid pattern"):
        load_pattern(path)


def test_load_pattern_catalogue_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="no \\*.yaml files"):
        load_pattern_catalogue(tmp_path, version=SEED_VERSION, released_at=SEED_RELEASED_AT)


def test_load_pattern_catalogue_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        load_pattern_catalogue(
            tmp_path / "nope", version=SEED_VERSION, released_at=SEED_RELEASED_AT
        )


# ---------------------------------------------------------------------------
# Catalogue-wide: at least 7 distinct patterns with non-overlapping ids,
# one per named category (spec 7.4).
# ---------------------------------------------------------------------------


def test_seed_catalogue_has_at_least_seven_distinct_patterns() -> None:
    release = _seed_release()

    assert len(release.patterns) >= 7

    ids = [pattern.id for pattern in release.patterns]
    assert len(set(ids)) == len(ids), "pattern ids must be non-overlapping"
    assert len(set(ids)) >= 7


def test_seed_catalogue_covers_every_named_category_exactly_once() -> None:
    release = _seed_release()

    categories = [pattern.category for pattern in release.patterns]
    assert len(set(categories)) == len(categories), "each category should be distinct"
    assert set(categories) == set(PatternCategory)


def test_seed_catalogue_parameter_schemas_do_not_overlap() -> None:
    """Non-overlapping in substance, not just in id: no two seed patterns
    declare the identical parameter-name set, which would signal a
    near-duplicate pattern padded in to hit a count."""
    release = _seed_release()

    parameter_name_sets = [
        frozenset(parameter.name for parameter in pattern.parameters)
        for pattern in release.patterns
    ]
    assert len(set(parameter_name_sets)) == len(parameter_name_sets)


# ---------------------------------------------------------------------------
# Immutability once published (spec 7.3), no ADR-004 workflow required.
# ---------------------------------------------------------------------------


def test_repository_publishes_a_draft_release() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)

    published = repo.publish(release.version, content_hash=release.content_hash)

    assert published.is_published
    assert repo.get_published(release.version) == published


def test_repository_rejects_publish_with_wrong_content_hash() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)

    with pytest.raises(ValidationError, match="content_hash does not match"):
        repo.publish(release.version, content_hash="not-the-real-hash")


def test_repository_republish_with_same_hash_is_a_noop() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)
    first = repo.publish(release.version, content_hash=release.content_hash)

    second = repo.publish(release.version, content_hash=release.content_hash)

    assert second == first


def test_repository_rejects_republish_with_different_content_hash() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)
    repo.publish(release.version, content_hash=release.content_hash)

    with pytest.raises(ValidationError, match="immutable"):
        repo.publish(release.version, content_hash="a-different-hash")


def test_repository_rejects_reloading_published_release_with_different_content() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)
    published = repo.publish(release.version, content_hash=release.content_hash)

    mutated_patterns = tuple(published.patterns[:-1]) + (
        published.patterns[-1].model_copy(update={"name": "a different name"}),
    )
    mutated = published.model_copy(update={"patterns": mutated_patterns})

    with pytest.raises(ValidationError, match="immutable once published"):
        repo.load(mutated)


def test_repository_allows_reloading_published_release_with_identical_content() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)
    published = repo.publish(release.version, content_hash=release.content_hash)

    reloaded = repo.load(published)

    assert reloaded.content_hash == published.content_hash


def test_get_published_rejects_a_draft_release() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)

    with pytest.raises(NotFoundError):
        repo.get_published(release.version)


def test_get_rejects_unknown_version() -> None:
    repo = InMemoryPatternRepository()

    with pytest.raises(NotFoundError):
        repo.get("9999.01.1")


def test_retire_requires_published_release() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)

    with pytest.raises(ValidationError, match="not PUBLISHED"):
        repo.retire(release.version)


def test_retire_transitions_a_published_release() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)
    repo.publish(release.version, content_hash=release.content_hash)

    retired = repo.retire(release.version)

    assert retired.status is PatternReleaseStatus.RETIRED
    with pytest.raises(NotFoundError):
        repo.get_published(release.version)


def test_list_releases_is_sorted_by_version() -> None:
    repo = InMemoryPatternRepository()
    release = _seed_release(status=PatternReleaseStatus.DRAFT)
    repo.load(release)

    releases = repo.list_releases()

    assert releases == (release,)
