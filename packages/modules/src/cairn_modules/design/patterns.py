"""R2-03: the ``design`` module's ``PatternRepository`` port (spec 5.4:
``PatternRepository | design | Postgres/YAML, fake``) and the YAML seed
loader for the pattern catalogue under ``patterns/`` at the repo root.

Patterns are versioned and immutable once published (spec 7.3's general
registry rule), but -- unlike R2-01's ``MappingRepository`` -- carry no
ADR-004 propose/review/approve workflow; see
``cairn_contracts.mapping.pattern``'s module docstring for why. So this
repository only needs ``load``/``publish``/``get``/``list_releases``, the
same shape R0-14's pre-workflow ``InMemoryMappingRegistry`` had before
R2-01 replaced it with the full workflow -- that shape is exactly what
spec 5.4's ``PatternRepository`` row and the R2-03 backlog row ask for,
nothing more.

Only an in-memory (fake) adapter and a YAML-file loader are implemented
here, matching R2-03's size (``L``, schema and static seed content, not a
service) and spec 5.4's v0 adapters column ("Postgres/YAML, fake"): a
Postgres adapter is not part of this story's acceptance criteria and
would be speculative ahead of a story that actually calls for it.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml
from cairn_contracts.mapping.pattern import Pattern, PatternCatalogueRelease, PatternReleaseStatus
from cairn_kernel.errors import NotFoundError, ValidationError
from pydantic import ValidationError as PydanticValidationError


class InMemoryPatternRepository:
    """Thread-safe, process-local ``PatternRepository`` adapter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._releases: dict[str, PatternCatalogueRelease] = {}

    def load(self, release: PatternCatalogueRelease) -> PatternCatalogueRelease:
        """Add or replace a release.

        A release already PUBLISHED under this version may only be
        reloaded with byte-identical content -- corrections must create a
        new version (spec 7.3).
        """
        with self._lock:
            existing = self._releases.get(release.version)
            if (
                existing is not None
                and existing.is_published
                and release.content_hash != existing.content_hash
            ):
                raise ValidationError(
                    f"pattern catalogue release {release.version} is immutable once "
                    "published; publish a new version"
                )
            self._releases[release.version] = release
            return release

    def publish(self, version: str, *, content_hash: str) -> PatternCatalogueRelease:
        """Transition a DRAFT release to PUBLISHED, or confirm a no-op
        republish of an already-PUBLISHED release with the same content.
        """
        with self._lock:
            release = self._require(version)
            if release.is_published:
                if content_hash != release.content_hash:
                    raise ValidationError(
                        f"pattern catalogue release {version} is immutable; publish a new version"
                    )
                return release
            if content_hash != release.content_hash:
                raise ValidationError(
                    f"pattern catalogue release {version} content_hash does not match its content"
                )
            published = release.model_copy(update={"status": PatternReleaseStatus.PUBLISHED})
            self._releases[version] = published
            return published

    def retire(self, version: str) -> PatternCatalogueRelease:
        with self._lock:
            release = self._require(version)
            if release.status is not PatternReleaseStatus.PUBLISHED:
                raise ValidationError(
                    f"pattern catalogue release {version} is {release.status.value}, "
                    "not PUBLISHED"
                )
            retired = release.model_copy(update={"status": PatternReleaseStatus.RETIRED})
            self._releases[version] = retired
            return retired

    def get(self, version: str) -> PatternCatalogueRelease:
        return self._require(version)

    def get_published(self, version: str) -> PatternCatalogueRelease:
        release = self._require(version)
        if not release.is_published:
            raise NotFoundError(f"pattern catalogue release {version} is not published")
        return release

    def list_releases(self) -> tuple[PatternCatalogueRelease, ...]:
        return tuple(self._releases[version] for version in sorted(self._releases))

    def _require(self, version: str) -> PatternCatalogueRelease:
        release = self._releases.get(version)
        if release is None:
            raise NotFoundError(f"pattern catalogue release {version} is not available")
        return release


def load_pattern(path: Path | str) -> Pattern:
    """Load a single seed pattern YAML file into a ``Pattern``.

    One file under ``patterns/`` holds one pattern (spec 7.4: "7
    patterns"), not a whole release -- distinct from ``mappings/seed.py``'s
    ``load_mapping_release``, where one file is a whole release of entries.
    """
    pattern_path = Path(path)
    payload = _read_yaml_mapping(pattern_path, kind="pattern")
    try:
        return Pattern.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid pattern {pattern_path}: {exc}") from exc


def load_pattern_catalogue(
    directory: Path | str,
    *,
    version: str,
    released_at: Any,
    status: PatternReleaseStatus = PatternReleaseStatus.DRAFT,
) -> PatternCatalogueRelease:
    """Load every ``*.yaml`` pattern file in ``directory`` into one release.

    Files are read in sorted filename order so a release's pattern order
    -- and therefore its content hash -- is deterministic.
    """
    directory_path = Path(directory)
    if not directory_path.is_dir():
        raise ValidationError(f"pattern catalogue directory {directory_path} does not exist")

    pattern_files = sorted(directory_path.glob("*.yaml"))
    if not pattern_files:
        raise ValidationError(f"pattern catalogue directory {directory_path} has no *.yaml files")

    patterns = tuple(load_pattern(path) for path in pattern_files)
    try:
        return PatternCatalogueRelease.model_validate(
            {
                "version": version,
                "released_at": released_at,
                "status": status,
                "patterns": patterns,
            }
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid pattern catalogue release {version}: {exc}") from exc


def _read_yaml_mapping(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {kind} {path}: {exc}") from exc

    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid YAML in {kind} {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError(f"{kind} {path} must be a YAML mapping")
    return payload


__all__ = [
    "InMemoryPatternRepository",
    "load_pattern",
    "load_pattern_catalogue",
]
