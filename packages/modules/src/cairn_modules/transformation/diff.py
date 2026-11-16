"""R3-04: the unified-diff artefact and its structured counterpart.

Spec §16's R3-04 row: "Diff retrievable; no source mutation". Spec §9's
``GET /v1/transformations/{run_id}/diff`` row is the API surface this
module exists to serve (``apps.api.routes_transformations`` is the
caller); this module itself knows nothing about HTTP.

This is a pure rendering step over data two prior units already
produced -- 721's ``SourceFile`` (the original text 726's engine was
given) and 726's ``TransformationManifest`` (the ``ManifestEntry``
records 725's Rust patcher decided, each carrying its own
``ManifestEdit`` byte spans when, and only when, ``outcome`` is
``APPLIED`` -- confirmed by reading ``packages/modules/tests/
test_transformation_engine.py``: a ``SKIPPED``/``UNSUPPORTED`` entry's
``edits`` tuple is always empty). This module never calls 726's
``TransformationPort``, never calls 725's Rust patcher again, and never
writes to any path on disk -- it only reads ``SourceFile.content``
(an in-memory string another unit already fetched) and a manifest
already computed, and renders both a unified-diff *text* artefact and a
structured, JSON-shaped form of the same information for a caller that
wants to walk entries programmatically rather than parse diff text
(732's console reads the structured form directly; the text form is for
display/export). Computing a diff is reading two already-produced
values and deriving a third; applying one is a write this module has no
method for, the same "the interface itself has no such method" shape
721's ``RepositorySourcePort`` and 726's ``TransformationPort`` already
use for their own "never writes back" guarantees.

Byte spans: 722/723's Rust parsers measure ``start_byte``/``end_byte``
over the file's UTF-8 byte representation (confirmed by reading 722's
``Span`` type and 724/725's own tests, which construct spans against
UTF-8 source text), not Python's native (UTF-16-ish) string indexing, so
every edit here is applied against ``SourceFile.content.encode("utf-8")``
and decoded back to ``str`` only after every edit for that file has been
applied -- never against ``str`` indices directly, which would silently
misplace a replacement in any file containing a multi-byte character
before an edit's span.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import dataclass

from cairn_contracts.transformation import SourceFile

from cairn_modules.transformation.engine import (
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)


@dataclass(frozen=True, slots=True)
class FileDiff:
    """One source file's diff artefact: the unified-diff text produced
    by applying every ``APPLIED`` entry's edits to the original content,
    plus the full structured manifest-entry list for this file
    (``APPLIED``, ``SKIPPED`` and ``UNSUPPORTED`` entries alike) for a
    caller that wants the "why", not just the "what changed" -- a
    unified diff alone cannot carry a skipped/unsupported reason, since
    nothing in the text changed for those entries.

    ``original_content``/``rendered_content`` are included verbatim
    (never re-derived by a caller re-running the edits) so a console can
    render a side-by-side view without re-implementing this module's own
    byte-offset arithmetic.
    """

    source_file_id: str
    original_content: str
    rendered_content: str
    unified_diff: str
    entries: tuple[ManifestEntry, ...]

    @property
    def applied_count(self) -> int:
        return sum(1 for entry in self.entries if entry.outcome is ManifestOutcome.APPLIED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for entry in self.entries if entry.outcome is ManifestOutcome.SKIPPED)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for entry in self.entries if entry.outcome is ManifestOutcome.UNSUPPORTED)

    @property
    def changed(self) -> bool:
        """``True`` iff this file's rendered content actually differs
        from its original content -- a file with only ``SKIPPED``/
        ``UNSUPPORTED`` entries (or none at all) is unchanged, even
        though it still carries entries worth showing a reviewer."""
        return self.original_content != self.rendered_content


@dataclass(frozen=True, slots=True)
class TransformationDiff:
    """The full diff artefact for one transformation run: one
    ``FileDiff`` per source file the run's manifest covers, in the same
    order ``TransformationManifest.source_file_ids`` lists them."""

    run_id: str
    source_file_ids: tuple[str, ...]
    files: tuple[FileDiff, ...]

    @property
    def applied_count(self) -> int:
        return sum(file_diff.applied_count for file_diff in self.files)

    @property
    def skipped_count(self) -> int:
        return sum(file_diff.skipped_count for file_diff in self.files)

    @property
    def unsupported_count(self) -> int:
        return sum(file_diff.unsupported_count for file_diff in self.files)


def _apply_edits(content: str, entries: Sequence[ManifestEntry]) -> str:
    """Apply every ``APPLIED`` entry's edits to ``content`` and return
    the resulting text. Never mutates ``content`` (a Python ``str`` is
    immutable, and this function only ever reads it) -- the caller's
    original ``SourceFile`` is untouched; this returns a brand-new
    string.

    Edits are applied back-to-front by ``start_byte`` so that an earlier
    edit's byte offsets are never invalidated by a later edit shifting
    the buffer -- 725's patcher already guarantees non-overlapping edits
    per file (two detections cannot both claim the same span), so
    ordering is the only concern here, not conflict resolution.
    """

    edits = [
        edit
        for entry in entries
        if entry.outcome is ManifestOutcome.APPLIED
        for edit in entry.edits
    ]
    edits.sort(key=lambda edit: edit.start_byte, reverse=True)
    buffer = bytearray(content.encode("utf-8"))
    for edit in edits:
        buffer[edit.start_byte : edit.end_byte] = edit.replacement.encode("utf-8")
    return bytes(buffer).decode("utf-8")


def _unified_diff_text(*, path: str, original: str, rendered: str) -> str:
    if original == rendered:
        return ""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def render_file_diff(source_file: SourceFile, manifest: TransformationManifest) -> FileDiff:
    """Render one file's ``FileDiff`` from its original content and
    every manifest entry recorded against it (matched by
    ``ManifestEntry.source_file_id == SourceFile.path``, the same
    identity 726's subprocess adapter already uses -- see
    ``cairn_adapters.transform_core.subprocess_adapter._parse_input_
    payload``, which sets ``source_file_id`` to ``source_file.path``
    verbatim)."""

    entries = tuple(
        entry for entry in manifest.entries if entry.source_file_id == source_file.path
    )
    rendered_content = _apply_edits(source_file.content, entries)
    unified_diff = _unified_diff_text(
        path=source_file.path,
        original=source_file.content,
        rendered=rendered_content,
    )
    return FileDiff(
        source_file_id=source_file.path,
        original_content=source_file.content,
        rendered_content=rendered_content,
        unified_diff=unified_diff,
        entries=entries,
    )


def render_transformation_diff(
    *,
    run_id: str,
    files: Sequence[SourceFile],
    manifest: TransformationManifest,
) -> TransformationDiff:
    """Render the full ``TransformationDiff`` for one run: one
    ``FileDiff`` per source file the manifest actually covers
    (``manifest.source_file_ids``), in that order. ``files`` is the
    exact ordered sequence 721's ``RepositorySourcePort.fetch`` returned
    for this run -- a file whose path is not in
    ``manifest.source_file_ids`` (an ``UNSUPPORTED``-language file never
    sent to 726's ``TransformationPort``) is not given a ``FileDiff``:
    there is nothing the manifest recorded about it, and inventing an
    empty one would misrepresent "covered, nothing changed" as "never
    considered".
    """

    files_by_path = {source_file.path: source_file for source_file in files}
    file_diffs: list[FileDiff] = []
    for source_file_id in manifest.source_file_ids:
        source_file = files_by_path.get(source_file_id)
        if source_file is None:
            # The manifest names a file this call was not given the
            # original content for -- never guessed or substituted; the
            # caller passed an incomplete ``files`` sequence for this
            # manifest, which is a caller error, not a silent gap.
            raise ValueError(
                f"manifest covers source file {source_file_id!r} but no matching "
                "SourceFile was given to render_transformation_diff"
            )
        file_diffs.append(render_file_diff(source_file, manifest))
    return TransformationDiff(
        run_id=run_id,
        source_file_ids=manifest.source_file_ids,
        files=tuple(file_diffs),
    )


__all__ = [
    "FileDiff",
    "TransformationDiff",
    "render_file_diff",
    "render_transformation_diff",
]
