"""R3-08: ``cairn_adapters.sandbox_runner`` -- resource/time limits and
no network egress by default, for 729's "tests" validation adapter.

Every assertion below observes a real effect of a real OS mechanism against
a fixture process that actually tried the thing being bounded -- never an
assertion that a config flag was merely set:

- CPU limit: a fixture that busy-loops burning CPU is killed by
  ``RLIMIT_CPU``/``SIGXCPU`` long before it would finish on its own.
- Wall-clock limit: a fixture that sleeps (not CPU-bound, so the CPU limit
  above would never fire) is killed by the wall-clock bound instead.
- Network egress: a fixture that actually calls ``socket.create_connection``
  against a real external address is observed to fail under the sandbox,
  and -- as a negative control proving this is the sandbox's own doing,
  not some surrounding network outage -- the identical fixture is observed
  to *succeed* when run the same way but without the sandbox's environment
  injected.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest
from cairn_adapters.sandbox_runner import run_sandboxed
from cairn_modules.transformation.sandbox import SandboxLimits

pytestmark = pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="POSIX-only sandbox mechanism"
)


def _external_reachability_or_skip() -> None:
    """The negative control below needs a real, reachable external address
    to prove the sandbox -- not an ambient firewall or an offline CI
    runner -- is what blocked the sandboxed attempt. Skipped, never
    xfailed, when this environment has no outbound network at all (that
    is a property of the environment, not of this unit's code)."""

    try:
        with socket.create_connection(("1.1.1.1", 80), timeout=3):
            return
    except OSError:
        pytest.skip("no outbound network reachable from this test environment at all")


# --- Resource limit: CPU -----------------------------------------------


def test_a_cpu_bound_fixture_exceeding_the_limit_is_killed_not_run_unbounded(tmp_path: Path) -> None:
    # Deliberately tries to burn CPU for ~30s of real busy work -- far
    # longer than the 1s CPU limit below -- so a pass here can only mean
    # the limit actually fired, not that the fixture happened to finish
    # quickly on its own.
    fixture = tmp_path / "burn_cpu.py"
    fixture.write_text(
        "import time\n"
        "deadline = time.time() + 30\n"
        "x = 0\n"
        "while time.time() < deadline:\n"
        "    x = (x * 1103515245 + 12345) % 2**32\n"
        "print('finished without being killed', x)\n",
        encoding="utf-8",
    )

    limits = SandboxLimits(cpu_seconds=1, memory_bytes=256 * 1024 * 1024, wall_clock_seconds=20)
    started = time.monotonic()
    result = run_sandboxed((sys.executable, str(fixture)), cwd=tmp_path, limits=limits)
    elapsed = time.monotonic() - started

    assert "finished without being killed" not in result.stdout, (
        "the CPU-bound fixture ran to completion -- the CPU limit did not bound it"
    )
    # Killed by RLIMIT_CPU well before the 20s wall-clock backstop would
    # ever have to step in, and nowhere near the 30s the fixture itself
    # asked to run for.
    assert elapsed < 10, f"fixture took {elapsed:.1f}s -- far longer than a 1s CPU limit allows"
    assert result.returncode != 0
    assert not result.timed_out, "killed by the CPU limit, not the separate wall-clock backstop"


# --- Resource limit: wall clock ------------------------------------------


def test_a_non_cpu_bound_fixture_exceeding_wall_clock_is_killed(tmp_path: Path) -> None:
    # Sleeping consumes ~no CPU time, so RLIMIT_CPU above would never
    # fire for this fixture -- it is the wall-clock bound, specifically,
    # that this test proves.
    fixture = tmp_path / "sleep_forever.py"
    fixture.write_text(
        "import time\n"
        "time.sleep(30)\n"
        "print('finished without being killed')\n",
        encoding="utf-8",
    )

    limits = SandboxLimits(cpu_seconds=60, memory_bytes=256 * 1024 * 1024, wall_clock_seconds=1.5)
    started = time.monotonic()
    result = run_sandboxed((sys.executable, str(fixture)), cwd=tmp_path, limits=limits)
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert "finished without being killed" not in result.stdout
    assert elapsed < 15, f"fixture took {elapsed:.1f}s -- far longer than a 1.5s wall-clock limit allows"


# --- Network egress -------------------------------------------------------


_CONNECT_FIXTURE = (
    "import socket\n"
    "import sys\n"
    "try:\n"
    "    with socket.create_connection(('1.1.1.1', 80), timeout=5):\n"
    "        print('CONNECTED')\n"
    "except OSError as exc:\n"
    "    print('BLOCKED', exc)\n"
    "    sys.exit(0)\n"
)


def test_network_egress_is_blocked_inside_the_sandbox(tmp_path: Path) -> None:
    _external_reachability_or_skip()

    fixture = tmp_path / "attempt_connect.py"
    fixture.write_text(_CONNECT_FIXTURE, encoding="utf-8")

    result = run_sandboxed((sys.executable, str(fixture)), cwd=tmp_path, limits=SandboxLimits())

    assert "CONNECTED" not in result.stdout, (
        "the fixture's outbound connection attempt succeeded -- the sandbox did not "
        f"block egress (stdout={result.stdout!r} stderr={result.stderr!r})"
    )
    assert "BLOCKED" in result.stdout, result.stdout


def test_negative_control_the_same_fixture_connects_when_not_sandboxed(tmp_path: Path) -> None:
    """Proves the block above is this sandbox's own doing, not an
    environmental coincidence (an offline runner, an ambient firewall):
    the identical fixture, run the identical way, but without the
    sandbox's env injected, is observed to actually connect."""

    _external_reachability_or_skip()

    import subprocess

    fixture = tmp_path / "attempt_connect.py"
    fixture.write_text(_CONNECT_FIXTURE, encoding="utf-8")

    completed = subprocess.run(
        (sys.executable, str(fixture)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert "CONNECTED" in completed.stdout, (
        "the un-sandboxed baseline did not connect either -- this environment has no "
        f"outbound network, which invalidates the sandboxed test's conclusion above "
        f"(stdout={completed.stdout!r} stderr={completed.stderr!r})"
    )


def test_loopback_is_still_allowed_inside_the_sandbox(tmp_path: Path) -> None:
    """The sandbox blocks egress, not all networking -- a sandboxed
    process can still talk to a server on loopback (e.g. a local test
    fixture server), proving the block is address-based, not a blanket
    "no sockets at all"."""

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    fixture = tmp_path / "attempt_loopback.py"
    fixture.write_text(
        "import socket\n"
        f"with socket.create_connection(('127.0.0.1', {port}), timeout=5):\n"
        "    print('LOOPBACK_CONNECTED')\n",
        encoding="utf-8",
    )

    try:
        result = run_sandboxed((sys.executable, str(fixture)), cwd=tmp_path, limits=SandboxLimits())
        server.settimeout(5)
        try:
            conn, _ = server.accept()
            conn.close()
        except OSError:
            pass
    finally:
        server.close()

    assert "LOOPBACK_CONNECTED" in result.stdout, (
        f"loopback connection was blocked too (stdout={result.stdout!r} stderr={result.stderr!r})"
    )
