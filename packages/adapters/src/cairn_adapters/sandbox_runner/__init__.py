"""R3-08: sandboxed execution for 729's "tests" validation adapter --
resource/time limits and no network egress by default. See ``runner.py``
and ``connect_block.c`` alongside this file for the mechanism."""

from cairn_adapters.sandbox_runner.runner import (
    SandboxBuildError,
    SandboxResult,
    run_sandboxed,
)

__all__ = ["SandboxBuildError", "SandboxResult", "run_sandboxed"]
