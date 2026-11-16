"""R3-01 outbound port: spec §5.4's ``RepositorySourcePort``.

Spec §16's R3-01 row: "Reads ref; no write-back". ADR-010 makes this
load-bearing: R0/R1/R2/R3 permit no Class C operation against a customer
environment, and a customer's source repository is a customer
environment. The port is deliberately shaped so that "no write-back" is
not a convention a careful caller happens to follow -- it is a fact about
the port's type. There is exactly one method, and it is a read. No
adapter behind this port can expose a write/push capability through the
port's own interface, because the interface has no such method at all;
an adapter module that also offers an un-called write method would still
satisfy this protocol, but writing one is not this story's job and the
construction-proof test in ``cairn_adapters.source_git`` is evidence that
the real Git adapter does not build one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from cairn_contracts.transformation import RepositoryRef, SourceFile
from cairn_kernel.hex import Port


class RepositorySourcePort(Port, Protocol):
    """Fetch every readable file at ``ref`` -- a Git ref or an uploaded
    archive -- as an ordered sequence of ``SourceFile``. Never mutates
    the source it reads from; there is no corresponding write method."""

    def fetch(self, ref: RepositoryRef) -> Sequence[SourceFile]: ...


__all__ = ["RepositorySourcePort"]
