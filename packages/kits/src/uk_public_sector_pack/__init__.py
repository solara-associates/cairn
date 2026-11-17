"""R5-06b: the UK public sector landing-zone vertical accelerator pack.

The first real pack built against the R5-06a conformance harness
(``cairn_kits.vertical_packs.harness``) -- the harness's own proof against
a non-synthetic pack, not a second abstraction layer on top of it.

This package is deliberately a standalone top-level package, not a
submodule of ``cairn_kits``, even though it physically lives under
``packages/kits/src``. The harness discovers any candidate pack by package
name plus a package root directory (exactly the shape its own
``good_pack``/``bad_pack_*`` fixtures already use), so a pack need not live
inside the ``cairn_kits`` import namespace to be discoverable. Keeping it a
sibling, rather than nesting it under ``cairn_kits.vertical_packs.packs``,
matters for a real reason: this pack genuinely uses R2-03's pattern
catalogue and R5-05b's residency sweep, both of which live in
``cairn_modules`` -- and the repo's root ``.importlinter`` has a
``kits-purity`` contract forbidding ``cairn_kits`` itself from importing
``cairn_modules``/``cairn_adapters``. Nesting this pack inside the
``cairn_kits`` package would make it a submodule of ``cairn_kits`` for
import-linter's purposes and trip that contract the moment it imports real
domain logic. The harness's own scoped domain-purity check (see
``cairn_kits.vertical_packs.import_purity.FORBIDDEN_MODULES``) deliberately
does *not* forbid a pack from importing ``cairn_modules`` -- packs are
accelerators built on top of the domain layer, not peers of it -- so this
pack is free to use ``cairn_modules`` for real, as long as it stays outside
the ``cairn_kits`` namespace itself.
"""
