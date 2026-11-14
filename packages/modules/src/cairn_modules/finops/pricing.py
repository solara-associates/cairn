"""R1-13: in-memory registry for versioned, immutable price-list releases.

Exactly R0-14's `InMemoryMappingRegistry` mechanism (see
`cairn_modules.mappings.registry`), reused rather than reinvented: a
release is published once; a later publish of the same version with
different content is rejected, since the release is immutable.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cairn_contracts.finops import PriceListRelease, ReleaseStatus
from cairn_kernel.errors import PriceListUnavailableError, ValidationError

from cairn_modules.finops.seed import load_price_list_release


class InMemoryPriceList:
    def __init__(self, releases: Iterable[PriceListRelease] = ()) -> None:
        self._releases: dict[str, PriceListRelease] = {}
        for release in releases:
            self.publish(release)

    def publish(self, release: PriceListRelease) -> None:
        if release.status is not ReleaseStatus.PUBLISHED:
            raise ValidationError(
                f"price list release {release.version} must be PUBLISHED before it can be loaded"
            )

        existing = self._releases.get(release.version)
        if existing is None:
            self._releases[release.version] = release
            return
        if existing.content_hash != release.content_hash:
            raise ValidationError(
                f"price list release {release.version} is immutable; publish a new version"
            )

    def load(self, path: Path | str) -> PriceListRelease:
        release = load_price_list_release(path)
        self.publish(release)
        return release

    def get(self, version: str) -> PriceListRelease:
        try:
            return self._releases[version]
        except KeyError as exc:
            raise PriceListUnavailableError(
                f"price list release {version} is not available"
            ) from exc

    def versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._releases))

    def __len__(self) -> int:
        return len(self._releases)


__all__ = ["InMemoryPriceList"]
