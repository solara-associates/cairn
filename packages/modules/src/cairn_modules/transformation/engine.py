"""R3-03b outbound port: spec §5.4's ``TransformationPort | transformation |
Rust core, fake``, and the transformation manifest ADR-015 requires.

ADR-015: "Record detector and pattern versions, applied/skipped/
unsupported outcomes and reasons in the transformation manifest." This is
the unit where that manifest is actually built. It is assembled from
725's Rust ``ChangeSet`` (one ``ChangeEntry`` per detection/skipped
candidate) -- carried across the subprocess boundary 726 builds (see
``cairn_adapters.transform_core``) as the raw JSON
``cairn-transform-cli`` writes to stdout -- without re-deriving or
re-judging anything the Rust pipeline already decided. This module never
calls the Rust binary itself; that is the adapter's job. ``build_manifest``
here is pure data-shaping, shared by both the real subprocess adapter and
the fake, so the two can never drift silently (see
``cairn_adapters.transform_core``'s shared contract test).

Field-naming discipline: this codebase's existing convention for a
recorded version is a ``<thing>_version`` string field (707's
``DesignReportVersions.pattern_catalogue_version``/``mapping_release_
version``, R2-04's ``TargetModel.pattern_catalogue_version``, 724's own
``DETECTOR_VERSION``/``detector_version``). This manifest follows the
same style:

- ``detector_version`` -- verbatim from the ``Detection``/
  ``SkippedCandidate`` the entry traces back to (724's
  ``cairn-detector/0.1.0``-shaped string).
- ``pattern_version`` -- ADR-015 asks for "detector *and pattern*
  versions" as two distinct things. No type anywhere in this corpus
  (721/722/723/724/725) defines a field literally named ``pattern_
  version`` -- there is no third, independent "pattern" version a
  detection carries beyond which language grammar recognized the shape
  it matched. The most honest non-invented reading, confirmed by reading
  722/723/724/725's actual Rust types rather than guessing: the "pattern"
  ADR-015 means is the parse pattern/grammar that produced the AST the
  detector matched against -- i.e. 722/723's ``parser_version``
  (``cairn-hcl-parser/0.1.0`` or ``cairn-python-parser/0.1.0``). This
  module records that value under the ``pattern_version`` name ADR-015
  uses, rather than inventing a second, redundant version string with no
  independent source of truth. This is a deliberate judgement call, named
  explicitly here (and in ``~/solara/lz2026/s726-handover.md``) rather
  than silently assumed.
- ``patcher_version`` -- verbatim from the ``ChangeEntry`` (725's
  ``cairn-transform-patcher/0.1.0``-shaped string). Not named in ADR-015's
  sentence, but it is exactly the same kind of fact (which engine version
  produced this outcome) and 725's handover explicitly expected 726 to
  carry it through.
- ``mapping_release_version`` -- R2-01's mapping release version, when an
  entry's rewrite needed one. 725's handover confirmed, by reading the
  Rust patcher's actual source (not assuming it), that neither rule in
  today's corpus (``tf-s3-bucket-inline-acl-deprecated``,
  ``py-import-imp-deprecated``) is a mapping/equivalence judgement -- both
  are same-provider/same-language successor renames, so no code path in
  this unit ever calls R2-01's resolver, and this field is ``None`` on
  every entry in the current rule set. It exists now, rather than being
  added later, so 728/729/730 never have to widen this model's shape to
  add it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from cairn_contracts.transformation import SourceFile
from cairn_kernel.hex import Port


class ManifestOutcome(str, Enum):
    """Mirrors 725's Rust ``ChangeOutcome`` exactly -- same three values,
    same ``SCREAMING_SNAKE_CASE`` strings, so a raw CLI JSON payload's
    ``outcome`` field round-trips into this enum with no translation
    table to keep in sync by hand."""

    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class ManifestEdit:
    """One byte-precise text replacement, mirroring 725's Rust
    ``TextEdit`` (span flattened to its four fields -- this manifest
    never needs the nested ``Span`` object as a type of its own)."""

    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    replacement: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One manifest line: one detection or skipped candidate, its
    outcome, its reason (``None`` iff ``outcome`` is ``APPLIED``, mirroring
    725's own invariant verbatim), and the exact versions that produced
    it (ADR-015)."""

    source_file_id: str
    rule_id: str
    outcome: ManifestOutcome
    reason: str | None
    edits: tuple[ManifestEdit, ...]
    detector_version: str
    pattern_version: str
    patcher_version: str
    mapping_release_version: str | None = None


@dataclass(frozen=True, slots=True)
class TransformationManifest:
    """The full manifest for one transformation run: every entry across
    every source file the run was given, in the order the files were
    given and -- within a file -- 725's own ``ChangeSet.entries`` order
    (``detections`` then ``skipped``, never reordered or grouped by this
    module)."""

    source_file_ids: tuple[str, ...]
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


class TransformationPort(Port, Protocol):
    """Spec §5.4's ``TransformationPort``. One method: run the full
    parse -> detect -> patch pipeline over every given source file and
    return the one manifest covering all of them. No write-back of any
    kind -- this port only ever reads ``SourceFile.content`` and returns
    a manifest; applying an edit to a real file is a later unit's job
    (728's diff artefact), not this port's."""

    def transform(self, files: Sequence[SourceFile]) -> TransformationManifest: ...


def _edit_from_raw(raw_edit: Mapping[str, Any]) -> ManifestEdit:
    span = raw_edit["span"]
    return ManifestEdit(
        start_byte=span["start_byte"],
        end_byte=span["end_byte"],
        start_line=span["start_line"],
        end_line=span["end_line"],
        replacement=raw_edit["replacement"],
    )


PARSE_INCOMPLETE_RULE_ID = "cairn-transform-core/parse-incomplete"
"""Unit 727's sentinel ``rule_id`` for a synthesized manifest entry (see
``_parse_failure_entry`` below). Never a real detector rule id (724's
``rule_ids`` module), so a reader of the manifest can always tell this
entry apart from an actual detection/skipped-candidate outcome -- it
records a parse-stage failure, not a rule judgement."""


def _parse_failure_entry(
    *, source_file_id: str, pattern_version: str, raw_output: Mapping[str, Any]
) -> ManifestEntry | None:
    """Unit 727's fix for a real gap its end-to-end golden-corpus pass
    found: 722's ``ParseOutput::Error`` cases (e.g. an unterminated HCL
    block) and 723's ``ParseOutput::Unsupported`` cases (e.g. an
    f-string) both produce an empty ``DetectionSet`` (724's own
    documented behaviour), so ``change_set.entries`` is empty -- with
    nothing else recorded, that file's manifest line was indistinguishable
    from a file that parsed cleanly and had nothing to flag, exactly the
    "swallowed by a later stage" failure mode ADR-015's manifest exists
    to prevent.

    Unit 726's Rust CLI did not carry the parse stage's own outcome
    anywhere a Python-side manifest could read it. Unit 727 added
    ``CliOutput.parse_status`` (``packages/transform-core/cli/src/
    main.rs``) for exactly this. ``raw_output.get("parse_status")`` is
    read defensively (``.get``, not ``[...]``) rather than required, so
    the pre-existing hand-written fixtures in
    ``packages/adapters/tests/test_transform_core_contract.py`` (which
    predate this field and never set it) keep working unmodified -- a
    missing ``parse_status`` is read as the implicit ``"PARSED"`` status
    those fixtures always represent, not a new required field every
    caller must now populate.

    Returns ``None`` when the parse succeeded (status ``"PARSED"``) --
    there is nothing to synthesize; the real ``change_set.entries`` (if
    any) carry the whole story for that file.
    """

    parse_status = raw_output.get("parse_status", {"status": "PARSED", "reason": None})
    status = parse_status.get("status", "PARSED")
    if status == "PARSED":
        return None

    reason = parse_status.get("reason") or "no reason recorded"
    stage_label = "parse error" if status == "ERROR" else "parse declined (unsupported construct)"
    return ManifestEntry(
        source_file_id=source_file_id,
        rule_id=PARSE_INCOMPLETE_RULE_ID,
        outcome=ManifestOutcome.UNSUPPORTED,
        reason=f"{stage_label}: {reason}",
        edits=(),
        detector_version=raw_output["detector_version"],
        pattern_version=pattern_version,
        patcher_version=raw_output["patcher_version"],
        mapping_release_version=None,
    )


def _entry_from_raw_change_entry(
    *, source_file_id: str, pattern_version: str, raw_entry: Mapping[str, Any]
) -> ManifestEntry:
    """Build one ``ManifestEntry`` from one raw ``ChangeEntry`` object, in
    the exact JSON shape 725's Rust ``ChangeSet`` serializes (``{"origin":
    {"origin": "DETECTION"|"SKIPPED_CANDIDATE", "rule_id": ..., "detector_
    version": ..., ...}, "outcome": ..., "edits": [...], "reason": ...,
    "patcher_version": ...}``). Shared by the real subprocess adapter and
    the fake (see ``cairn_adapters.transform_core``) so neither can drift
    from this one reading of the contract.
    """

    origin = raw_entry["origin"]
    return ManifestEntry(
        source_file_id=source_file_id,
        rule_id=origin["rule_id"],
        outcome=ManifestOutcome(raw_entry["outcome"]),
        reason=raw_entry["reason"],
        edits=tuple(_edit_from_raw(edit) for edit in raw_entry["edits"]),
        detector_version=origin["detector_version"],
        pattern_version=pattern_version,
        patcher_version=raw_entry["patcher_version"],
        mapping_release_version=None,
    )


def build_manifest(cli_outputs: Sequence[tuple[str, Mapping[str, Any]]]) -> TransformationManifest:
    """Assemble a ``TransformationManifest`` from one raw ``CliOutput``
    payload per source file -- exactly the JSON object
    ``cairn-transform-cli`` (726's Rust subprocess binary) writes to
    stdout for one ``ParseInput``, or the fake adapter's canned
    equivalent of it. ``cli_outputs`` is ``(source_file_id, raw_cli_
    output)`` pairs in the order the files were given to ``transform``.

    This is the one place both the real and fake ``TransformationPort``
    adapters route through, so a shared contract test can run both
    against the same fixtures and assert their manifests are identical
    -- any drift between the fake's canned output and the real binary's
    actual output shows up here, not inside either adapter separately.
    """

    source_file_ids: list[str] = []
    entries: list[ManifestEntry] = []
    for source_file_id, raw_output in cli_outputs:
        source_file_ids.append(source_file_id)
        pattern_version = raw_output["parser_version"]
        for raw_entry in raw_output["change_set"]["entries"]:
            entries.append(
                _entry_from_raw_change_entry(
                    source_file_id=source_file_id,
                    pattern_version=pattern_version,
                    raw_entry=raw_entry,
                )
            )
        parse_failure_entry = _parse_failure_entry(
            source_file_id=source_file_id,
            pattern_version=pattern_version,
            raw_output=raw_output,
        )
        if parse_failure_entry is not None:
            entries.append(parse_failure_entry)
    return TransformationManifest(
        source_file_ids=tuple(source_file_ids),
        entries=tuple(entries),
    )


__all__ = [
    "PARSE_INCOMPLETE_RULE_ID",
    "ManifestEdit",
    "ManifestEntry",
    "ManifestOutcome",
    "TransformationManifest",
    "TransformationPort",
    "build_manifest",
]
