from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cairn_contracts.posture import ControlCatalogueRelease, ReleaseStatus
from cairn_kernel.errors import ControlUnavailableError, ValidationError

from cairn_modules.posture.seed import load_control_catalogue_release


class InMemoryControlCatalogue:
    def __init__(self, releases: Iterable[ControlCatalogueRelease] = ()) -> None:
        self._releases: dict[str, ControlCatalogueRelease] = {}
        for release in releases:
            self.publish(release)

    def publish(self, release: ControlCatalogueRelease) -> None:
        if release.status is not ReleaseStatus.PUBLISHED:
            raise ValidationError(
                f"control catalogue release {release.version} must be PUBLISHED before it can be loaded"
            )

        existing = self._releases.get(release.version)
        if existing is None:
            self._releases[release.version] = release
            return
        if existing.content_hash != release.content_hash:
            raise ValidationError(
                f"control catalogue release {release.version} is immutable; publish a new version"
            )

    def load(self, path: Path | str) -> ControlCatalogueRelease:
        release = load_control_catalogue_release(path)
        self.publish(release)
        return release

    def get(self, version: str) -> ControlCatalogueRelease:
        try:
            return self._releases[version]
        except KeyError as exc:
            raise ControlUnavailableError(
                f"control catalogue release {version} is not available"
            ) from exc

    def get_control(self, version: str, control_id: str):
        release = self.get(version)
        for control in release.controls:
            if control.id == control_id:
                return control
        raise ControlUnavailableError(
            f"control {control_id} is not present in release {version}"
        )

    def versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._releases))

    def __len__(self) -> int:
        return len(self._releases)


__all__ = ["InMemoryControlCatalogue"]
