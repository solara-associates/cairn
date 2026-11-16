"""R3-01: contracts for the transformation module's repository source.

Spec §5.4: ``RepositorySourcePort | transformation | Git/upload, fake``.
Spec §16's R3-01 row: "Reads ref; no write-back". ADR-010 makes the
"no write-back" half load-bearing, not a convenience: R3 as a whole must
never be able to mutate a customer's source repository, by construction.
These two models are the shape every adapter behind that port (and the
port protocol itself, in ``cairn_modules.transformation.source``) speaks.

``RepositoryRef`` is a tagged union, not two unrelated types: a caller
asks for either a Git ref or an uploaded archive, never both, and the
``kind`` discriminator lets a single ``RepositoryRef`` annotation carry
either shape through the port without the caller needing to know which
one it is ahead of inspecting it.

ADR-015 scopes this release's transformation engine to Terraform/HCL and
Python source. A file in neither language is still a readable
``SourceFile`` -- it is never silently dropped from a fetch result -- it
just carries ``SourceLanguage.UNSUPPORTED`` rather than a detected
language.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceLanguage(str, Enum):
    """ADR-015's R3 scope, plus the explicit "readable but out of scope"
    case. A file is never dropped from a fetch result for having a
    language this release does not transform -- it is labelled
    ``UNSUPPORTED`` instead."""

    TERRAFORM = "TERRAFORM"
    PYTHON = "PYTHON"
    UNSUPPORTED = "UNSUPPORTED"


class GitRepositoryRef(BaseModel):
    """A Git source: a URL plus the ref to read -- a branch, tag, or
    commit SHA. ``ref`` is read-only input to ``fetch``; nothing in this
    model, or in any adapter that consumes it, ever writes back to
    ``url``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["GIT"] = "GIT"
    url: RequiredText
    ref: RequiredText


class UploadRepositoryRef(BaseModel):
    """An uploaded-archive source: an opaque id a prior upload step
    issued for the archive's stored bytes. This model carries no bytes
    itself -- the adapter behind ``RepositorySourcePort`` resolves
    ``archive_id`` to content; this contract only names which archive to
    read."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["UPLOAD"] = "UPLOAD"
    archive_id: RequiredText


RepositoryRef = Annotated[
    GitRepositoryRef | UploadRepositoryRef,
    Field(discriminator="kind"),
]


class SourceFile(BaseModel):
    """One file read from a fetched repository or archive.

    ``path`` is the file's path relative to the repository/archive root,
    using forward slashes regardless of host platform, so it is a stable
    key across a Git checkout and an unpacked archive alike. ``content``
    is the file's decoded text. ``language`` is this release's detected
    language for the file (or ``UNSUPPORTED``) -- 722/723's parser work
    reads this field to decide whether a file is in scope for parsing.
    """

    model_config = ConfigDict(frozen=True)

    path: RequiredText
    content: str
    language: SourceLanguage


__all__ = [
    "GitRepositoryRef",
    "RepositoryRef",
    "SourceFile",
    "SourceLanguage",
    "UploadRepositoryRef",
]
