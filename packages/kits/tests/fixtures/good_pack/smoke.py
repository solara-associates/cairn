def run_smoke_test() -> None:
    """The minimal smoke test a conformant pack must provide."""
    from good_pack.manifest import MANIFEST

    assert MANIFEST.pack_id == "good-pack"
