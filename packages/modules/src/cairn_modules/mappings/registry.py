from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import MappingUnavailableError, ValidationError

from cairn_modules.mappings.seed import load_mapping_release


class InMemoryMappingRegistry:
    def __init__(self, releases: Iterable[MappingRelease] = ()) -> None:
        self._releases: dict[str, MappingRelease] = {}
        for release in releases:
            self.publish(release)

    def publish(self, release: MappingRelease) -> None:
        if release.status is not ReleaseStatus.PUBLISHED:
            raise ValidationError(
                f"mapping release {release.version} must be PUBLISHED before it can be loaded"
            )

        existing = self._releases.get(release.version)
        if existing is None:
            self._releases[release.version] = release
            return
        if existing.content_hash != release.content_hash:
            raise ValidationError(
                f"mapping release {release.version} is immutable; publish a new version"
            )

    def load(self, path: Path | str) -> MappingRelease:
        release = load_mapping_release(path)
        self.publish(release)
        return release

    def get(self, version: str) -> MappingRelease:
        try:
            return self._releases[version]
        except KeyError as exc:
            raise MappingUnavailableError(
                f"mapping release {version} is not available"
            ) from exc

    def versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._releases))

    def __len__(self) -> int:
        return len(self._releases)


__all__ = ["InMemoryMappingRegistry"]
