"""Deliberately broken variant of the real UK public sector pack.

Reuses 822's own fixture-pack break style
(``packages/kits/tests/fixtures/bad_pack_violation``): a valid-looking
manifest and a passing smoke test, but a direct adapter import elsewhere in
the package -- the domain-purity violation under test. This proves the
harness's acceptance criteria extend to rejecting a *realistic* broken
variant of a real pack, not just its own synthetic fixtures.
"""
