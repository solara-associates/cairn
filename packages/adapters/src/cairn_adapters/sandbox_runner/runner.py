"""R3-08: the sandboxed-execution primitive 731's brief asks for -- spec
§16's R3-08 row ("Resource and time limits enforced; egress blocked"). This
is the one place in the codebase that actually spawns a customer's declared
test command (``cairn_adapters.validation_tests.real.
TestSuiteValidationAdapter`` -- see that module's docstring and
``cairn_modules.transformation.sandbox``'s for exactly why only that
adapter needs this).

Two bounds, enforced by two different OS-level mechanisms, both proven in
``packages/adapters/tests/test_sandbox_runner.py`` by actually exceeding
them, never by asserting a config value:

- **CPU time** (``SandboxLimits.cpu_seconds``): ``resource.setrlimit(
  RLIMIT_CPU, ...)`` in a ``preexec_fn``, run in the child after ``fork()``
  and before ``exec()``. This is the one resource-limit mechanism already
  proven portable across this estate's two real platforms (dev: macOS;
  CI: Linux) -- macOS's kernel does not support ``RLIMIT_AS``/
  ``RLIMIT_DATA`` (``setrlimit`` raises ``ValueError`` there even when
  raising the limit, confirmed interactively before writing this), so a
  memory ceiling cannot be the one *relied-on* bound without the test
  suite failing to even start on the dev machine. ``RLIMIT_AS`` is still
  attempted below, best-effort, for the platforms (Linux, including this
  project's own CI) that do enforce it -- it is just not the bound this
  unit's own resource-limit test depends on, since that test must pass on
  both platforms.
- **Wall clock** (``SandboxLimits.wall_clock_seconds``): reuses the one
  timeout convention already used everywhere else in this codebase for a
  subprocess call (``subprocess.run(..., timeout=...)`` in
  ``cairn_adapters.transform_core.subprocess_adapter``/
  ``cairn_adapters.validation_static.subprocess_adapter``) rather than
  inventing a second one -- a backstop for a process that is not CPU-bound
  (e.g. it is merely sleeping, or blocked waiting on a network call this
  module is about to make impossible anyway).

Egress: see ``connect_block.c`` alongside this module for the mechanism
and its honestly-documented platform gap. ``run_sandboxed`` below compiles
it once per process (cached) and injects it into the child's environment
only -- ``LD_PRELOAD`` on Linux, ``DYLD_INSERT_LIBRARIES`` +
``DYLD_FORCE_FLAT_NAMESPACE`` on macOS -- never into this process's own
environment.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from cairn_modules.transformation.sandbox import DEFAULT_SANDBOX_LIMITS, SandboxLimits

_SHIM_SOURCE = Path(__file__).parent / "connect_block.c"

_build_lock = threading.Lock()
_cached_shim_path: Path | None = None


class SandboxBuildError(RuntimeError):
    """The egress-blocking shim could not be compiled. Raised, never
    silently skipped -- running the sandboxed command without it would
    mean "no network egress by default" quietly stops being true."""


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """The outcome of one ``run_sandboxed`` call."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def _compiled_shim_path() -> Path:
    """Build ``connect_block.c`` once and reuse it for every sandboxed
    call in this process. Compiled fresh into a private temp directory
    rather than shipped prebuilt, so the shim is always built for the
    exact platform/architecture ``run_sandboxed`` is actually running on
    (dev machine or CI runner), never a stale cross-platform binary
    checked into the repo.
    """

    global _cached_shim_path
    with _build_lock:
        if _cached_shim_path is not None and _cached_shim_path.exists():
            return _cached_shim_path

        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if compiler is None:
            raise SandboxBuildError(
                "no C compiler (cc/gcc/clang) available to build the egress-blocking "
                "sandbox shim; refusing to run a sandboxed command without it rather "
                "than silently allowing network egress"
            )

        out_dir = Path(tempfile.mkdtemp(prefix="cairn-sandbox-shim-"))
        if sys.platform == "darwin":
            out_path = out_dir / "cairn_sandbox_block_net.dylib"
            cmd = [compiler, "-dynamiclib", "-O2", str(_SHIM_SOURCE), "-o", str(out_path)]
        else:
            out_path = out_dir / "cairn_sandbox_block_net.so"
            cmd = [
                compiler,
                "-shared",
                "-fPIC",
                "-O2",
                str(_SHIM_SOURCE),
                "-o",
                str(out_path),
                "-ldl",
            ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise SandboxBuildError(
                f"failed to compile the egress-blocking sandbox shim: {completed.stderr}"
            )

        _cached_shim_path = out_path
        return out_path


def _preexec_fn(limits: SandboxLimits):
    """Returns the ``preexec_fn`` ``subprocess.Popen`` runs in the child,
    after ``fork()``, before ``exec()``. Never raises past this point on
    an unsupported limit -- a platform that cannot enforce ``RLIMIT_AS``
    (macOS) still gets the CPU and wall-clock bounds, which is strictly
    better than refusing to run the sandbox at all on that platform.
    """

    import resource

    def _apply() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        except (ValueError, OSError):
            pass
        # No ``os.setsid()`` here: ``run_sandboxed`` already passes
        # ``start_new_session=True`` to ``subprocess.Popen``, which calls
        # ``setsid()`` in the child itself before this ``preexec_fn`` runs
        # -- calling it a second time here raises (the child is already a
        # session leader), which previously surfaced as an opaque
        # "Exception occurred in preexec_fn" from every sandboxed call.

    return _apply


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_sandboxed(
    command: tuple[str, ...],
    *,
    cwd: Path,
    limits: SandboxLimits = DEFAULT_SANDBOX_LIMITS,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    """Run ``command`` in ``cwd`` under ``limits``, with no network egress
    by default. The one function ``cairn_adapters.validation_tests.real.
    TestSuiteValidationAdapter`` calls instead of a bare ``subprocess.run``
    to execute the customer's own declared test command.
    """

    shim = _compiled_shim_path()
    child_env = dict(env if env is not None else os.environ)
    if sys.platform == "darwin":
        child_env["DYLD_INSERT_LIBRARIES"] = str(shim)
        child_env["DYLD_FORCE_FLAT_NAMESPACE"] = "1"
    else:
        existing = child_env.get("LD_PRELOAD", "")
        child_env["LD_PRELOAD"] = f"{shim}:{existing}" if existing else str(shim)

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=_preexec_fn(limits),  # noqa: PLW1509 -- the only way to set rlimits before exec()
            start_new_session=True,
        )
    except OSError as exc:
        return SandboxResult(returncode=-1, stdout="", stderr=str(exc), timed_out=False)

    try:
        stdout, stderr = process.communicate(timeout=limits.wall_clock_seconds)
        returncode = process.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_group(process.pid)
        stdout, stderr = process.communicate()
        returncode = process.returncode if process.returncode is not None else -1
        timed_out = True

    return SandboxResult(returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out)


__all__ = ["SandboxBuildError", "SandboxResult", "run_sandboxed"]
