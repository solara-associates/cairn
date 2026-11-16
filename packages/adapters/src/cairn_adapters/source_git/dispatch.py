"""781/R4-02: wires 721's two real ``RepositorySourcePort`` adapters
(``GitSourceAdapter``, ``UploadSourceAdapter``) into one adapter so a
single production wiring handles both ``GitRepositoryRef`` and
``UploadRepositoryRef``.

Spec §5.4's row names both halves behind the same port, and 728/R3-04's
route (``cairn_api.routes_transformations.create_transformation``)
already calls ``source_port.fetch(ref)`` generically over whichever
``RepositoryRef`` kind a caller sends -- ``CreateTransformationRequest.
repository_ref`` is the full discriminated union, not a Git-only shape.
The route was never the gap: the app's own default wiring
(``cairn_api.app.create_app``) previously built only a bare
``GitSourceAdapter`` as its ``RepositorySourcePort``, which has no
``url``/``ref`` to read off an ``UploadRepositoryRef`` and fails on one.
This adapter is the missing piece, dispatching each ``fetch`` to the
real adapter matching ``ref.kind`` -- never both, matching
``RepositoryRef``'s own tagged-union discipline.
"""

from __future__ import annotations

from collections.abc import Sequence

from cairn_contracts.transformation import RepositoryRef, SourceFile
from cairn_kernel.errors import ProviderUnavailableError

from cairn_adapters.source_git.git_adapter import GitSourceAdapter
from cairn_adapters.source_git.upload_adapter import UploadSourceAdapter


class CompositeSourceAdapter:
    """The real ``RepositorySourcePort`` for production use: a
    ``GitRepositoryRef`` always goes to a real ``GitSourceAdapter``; an
    ``UploadRepositoryRef`` goes to ``upload_adapter`` when one is
    configured.

    ``upload_adapter`` is optional because this release has no real
    archive-storage backend of its own (no cloud call is made from here,
    or from ``UploadSourceAdapter`` itself) -- a caller that has one
    (wiring ``UploadSourceAdapter(archive_loader)`` in) gets the real
    UPLOAD path end to end; without one, an ``UploadRepositoryRef``
    fails fast here with a clear ``ProviderUnavailableError`` rather
    than silently falling through to the Git adapter, which would raise
    an unrelated ``AttributeError`` trying to read ``ref.url``/``ref.ref``
    off a model that has neither field.
    """

    def __init__(
        self,
        *,
        git_adapter: GitSourceAdapter | None = None,
        upload_adapter: UploadSourceAdapter | None = None,
    ) -> None:
        self._git_adapter = git_adapter or GitSourceAdapter()
        self._upload_adapter = upload_adapter

    def fetch(self, ref: RepositoryRef) -> Sequence[SourceFile]:
        if ref.kind == "GIT":
            return self._git_adapter.fetch(ref)
        if self._upload_adapter is None:
            raise ProviderUnavailableError(
                "no upload source adapter configured: an UploadRepositoryRef "
                "requires cairn_adapters.source_git.CompositeSourceAdapter to "
                "be built with an UploadSourceAdapter(archive_loader=...)"
            )
        return self._upload_adapter.fetch(ref)


__all__ = ["CompositeSourceAdapter"]
