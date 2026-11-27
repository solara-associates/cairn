"""R6-01: prompts as versioned artefacts (ADR-019 §9, A6.prompts).

A prompt is a file with a declared id and version, diffable in review
and referenced by id at the call site -- never a string literal at a
model call. ``PromptRegistry`` loads the ``prompts/`` tree once at
startup and validates every reference an ``AgentSpec`` names resolves,
so a missing prompt fails the process rather than the first run that
needs it.

Front matter is two ``---`` lines bracketing ``key: value`` pairs, kept
deliberately minimal (no YAML dependency) because the only fields this
unit needs are ``id`` and ``version``. The file's path is part of the
contract too: ``prompts/<agent>/<name>.v<version>.md`` must agree with
the front matter it declares, so a copy-pasted file with a stale id
cannot silently shadow the one its path implies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cairn_kernel.errors import MissingDependencyError, NotFoundError, ValidationError

_FRONT_MATTER_DELIMITER = "---"


@dataclass(frozen=True, slots=True)
class PromptArtifact:
    """One loaded prompt file: its declared identity, its path and its
    body text (the part after the front matter block)."""

    prompt_id: str
    version: int
    path: Path
    body: str

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ValidationError(f"prompt at {self.path} declares a blank id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version <= 0:
            raise ValidationError(f"prompt at {self.path} declares a non-positive version")


def _parse_front_matter(path: Path, text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise ValidationError(f"prompt at {path} has no front matter block")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == _FRONT_MATTER_DELIMITER
        )
    except StopIteration:
        raise ValidationError(f"prompt at {path} has an unterminated front matter block") from None

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValidationError(f"prompt at {path} has a malformed front matter line: {line!r}")
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    body = "\n".join(lines[end + 1 :]).strip()
    return fields, body


def _expected_identity(path: Path) -> tuple[str, int]:
    stem = path.stem  # e.g. "explain-disposition.v1"
    name, sep, version_text = stem.rpartition(".v")
    if not sep or not version_text.isdigit():
        raise ValidationError(f"prompt file name {path.name!r} must end in '.v<version>.md'")
    return f"{path.parent.name}/{name}", int(version_text)


def _load_one(path: Path) -> PromptArtifact:
    fields, body = _parse_front_matter(path, path.read_text(encoding="utf-8"))
    missing = {"id", "version"} - fields.keys()
    if missing:
        raise ValidationError(f"prompt at {path} is missing front matter field(s): {sorted(missing)}")

    declared_id = fields["id"]
    version_text = fields["version"]
    if not version_text.isdigit():
        raise ValidationError(f"prompt at {path} declares a non-integer version: {version_text!r}")
    declared_version = int(version_text)

    expected_id, expected_version = _expected_identity(path)
    if (declared_id, declared_version) != (expected_id, expected_version):
        raise ValidationError(
            f"prompt at {path} declares ({declared_id!r}, {declared_version}) but its path implies "
            f"({expected_id!r}, {expected_version})"
        )

    return PromptArtifact(prompt_id=declared_id, version=declared_version, path=path, body=body)


class PromptRegistry:
    """Loads every prompt under a directory once and resolves them by
    ``(prompt_id, version)``. A duplicate id/version pair is a defect in
    the ``prompts/`` tree, not something later writer wins over."""

    def __init__(self, artifacts: Iterable[PromptArtifact]) -> None:
        self._artifacts: dict[tuple[str, int], PromptArtifact] = {}
        for artifact in artifacts:
            key = (artifact.prompt_id, artifact.version)
            if key in self._artifacts:
                raise ValidationError(
                    f"duplicate prompt id/version {key}: {self._artifacts[key].path} and {artifact.path}"
                )
            self._artifacts[key] = artifact

    @classmethod
    def load(cls, directory: Path) -> PromptRegistry:
        paths = sorted(directory.rglob("*.md"))
        return cls(_load_one(path) for path in paths)

    def get(self, prompt_id: str, version: int) -> PromptArtifact:
        try:
            return self._artifacts[(prompt_id, version)]
        except KeyError:
            raise NotFoundError(f"no prompt registered for ({prompt_id!r}, {version})") from None

    def validate_references(self, references: Iterable[tuple[str, int]]) -> None:
        """Startup validation (A5.13): every reference an ``AgentSpec``
        names must resolve now, not at the first call that needs it."""

        missing = sorted({ref for ref in references if ref not in self._artifacts})
        if missing:
            raise MissingDependencyError(f"unresolved prompt reference(s): {missing}")

    def __len__(self) -> int:
        return len(self._artifacts)


__all__ = ["PromptArtifact", "PromptRegistry"]
