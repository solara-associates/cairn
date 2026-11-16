"""R3-01: ``RepositorySourcePort`` adapters (spec §5.4) -- a real
read-only Git adapter, a real read-only upload adapter, and a
deterministic fake for tests. No adapter here writes back to the
source it reads (ADR-010; spec §16's R3-01 row: "Reads ref; no
write-back")."""

from cairn_adapters.source_git.dispatch import CompositeSourceAdapter
from cairn_adapters.source_git.fake import FakeRepositorySource
from cairn_adapters.source_git.git_adapter import GitSourceAdapter
from cairn_adapters.source_git.upload_adapter import ArchiveLoader, UploadSourceAdapter

__all__ = [
    "ArchiveLoader",
    "CompositeSourceAdapter",
    "FakeRepositorySource",
    "GitSourceAdapter",
    "UploadSourceAdapter",
]
