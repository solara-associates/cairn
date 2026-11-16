"""R3-01: the real ``RepositorySourcePort`` adapter for an uploaded
archive.

Spec §5.4: ``RepositorySourcePort | transformation | Git/upload, fake``.
This is the "upload" half; ``cairn_adapters.source_git.git_adapter`` is
the "Git" half. Unpacks a previously uploaded zip archive, read-only:
this adapter never writes to the archive it was handed, and the
directory it extracts into is a temporary one removed before ``fetch``
returns. Resolving ``archive_id`` to the archive's bytes is injected
(``archive_loader``), the same pattern R1-04's ``run_or_resume`` uses for
``load_content`` -- this adapter does not define or depend on where
uploaded archives are stored.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from cairn_contracts.transformation import SourceFile, UploadRepositoryRef
from cairn_kernel.errors import ProviderUnavailableError, ValidationError

from cairn_adapters.source_git.language import detect_language

ArchiveLoader = Callable[[str], bytes]


class UploadSourceAdapter:
    """The real ``RepositorySourcePort`` adapter for ``UploadRepositoryRef``.

    ``archive_loader(archive_id)`` must return the archive's raw zip
    bytes; this adapter only unpacks them, it never fetches or stores
    them itself.
    """

    def __init__(self, archive_loader: ArchiveLoader) -> None:
        self._archive_loader = archive_loader

    def fetch(self, ref: UploadRepositoryRef) -> tuple[SourceFile, ...]:
        raw = self._archive_loader(ref.archive_id)
        try:
            archive = zipfile.ZipFile(BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"archive {ref.archive_id!r} is not a valid zip file") from exc

        with tempfile.TemporaryDirectory(prefix="cairn-source-upload-") as tmp:
            extract_dir = Path(tmp)
            try:
                _safe_extract(archive, extract_dir)
            except ValidationError:
                raise
            except OSError as exc:
                raise ProviderUnavailableError(
                    f"could not extract archive {ref.archive_id!r}: {exc}"
                ) from exc

            files: list[SourceFile] = []
            for entry in sorted(extract_dir.rglob("*")):
                if not entry.is_file():
                    continue
                relative_path = entry.relative_to(extract_dir).as_posix()
                try:
                    content = entry.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                files.append(
                    SourceFile(
                        path=relative_path,
                        content=content,
                        language=detect_language(relative_path),
                    )
                )
            return tuple(files)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extracts every member of ``archive`` into ``destination``,
    refusing any member whose name would resolve outside ``destination``
    (a zip-slip path-traversal entry) before writing anything."""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if destination not in target.parents and target != destination:
            raise ValidationError(
                f"archive member {member.filename!r} resolves outside the extraction root"
            )
    archive.extractall(destination)


__all__ = ["ArchiveLoader", "UploadSourceAdapter"]
