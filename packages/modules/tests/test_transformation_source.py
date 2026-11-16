"""Tests for the R3-01 ``RepositorySourcePort`` protocol shape.

Spec §16's R3-01 row: "Reads ref; no write-back". This port must have
exactly one method, and it must be a read -- not merely a convention a
caller follows, but a fact about the protocol's own shape, so nothing
behind this port can be asked to write back to a customer's source
repository through the port's own interface.
"""

from __future__ import annotations

from cairn_contracts.transformation import GitRepositoryRef, SourceFile, SourceLanguage
from cairn_modules.transformation.source import RepositorySourcePort


class _FetchOnlyAdapter:
    def fetch(self, ref: GitRepositoryRef) -> tuple[SourceFile, ...]:
        return (SourceFile(path="main.tf", content="", language=SourceLanguage.TERRAFORM),)


def test_the_port_has_exactly_one_method_and_it_is_fetch() -> None:
    public_members = {
        name
        for name in vars(RepositorySourcePort)
        if not name.startswith("_") and callable(getattr(RepositorySourcePort, name))
    }
    assert public_members == {"fetch"}


def test_the_port_declares_no_write_method_by_any_common_name() -> None:
    forbidden_names = {
        "write",
        "push",
        "commit",
        "save",
        "store",
        "update",
        "delete",
        "put",
        "upload",
        "apply",
    }
    declared = {name for name in vars(RepositorySourcePort) if not name.startswith("_")}
    assert declared.isdisjoint(forbidden_names)


def test_a_conforming_adapter_satisfies_the_protocol_structurally() -> None:
    adapter: RepositorySourcePort = _FetchOnlyAdapter()
    ref = GitRepositoryRef(url="https://example.invalid/repo.git", ref="main")
    files = adapter.fetch(ref)
    assert files[0].path == "main.tf"
