"""The only module that runs the qretools CLI.

Two qretools versions are used, and a qretools found on PATH is never used:

- `build` runs the version that the workspace's mise.toml pins. This module asks mise
  where that version is installed, and runs that file by its absolute path, through
  `mise exec` so that node is the workspace's too.
- Every other command runs QRETOOLS, the version this harness is written for, through
  `npx`, which runs exactly that version from npm. OVERRIDE, for development only,
  names a qretools build to run with node in its place.

Every function returns a value. Nothing here raises for a refusal or a failed command.
"""

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

TOOL = "npm:qretools"
# The qretools that the harness calls, except for `build`. Change it only here.
QRETOOLS = "qretools@2.0.0-alpha.12"
# For development only: the path of a qretools build (its JS file) to run in its place.
OVERRIDE = "QRETOOLS_HARNESS_QRETOOLS"


@dataclass(frozen=True)
class Completed:
    """A command that ran. `stdout` and `stderr` are empty when they were not captured."""

    code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class Refused:
    """Why nothing ran, or why a command failed, as a sentence for a person."""

    reason: str


@dataclass(frozen=True)
class Qretools:
    """A qretools ready to run: in `workspace` (the folder it runs in), with `command`."""

    workspace: Path
    command: tuple[str, ...]
    version: str  # the version, or the digest of a development build

    def argv(self, *args: str) -> list[str]:
        """The command line that runs qretools with `args`."""
        return [*self.command, *args]


@dataclass(frozen=True)
class Built:
    ddi: Path


class Run(Protocol):
    """Runs argv in a directory. With capture false, output goes straight to the terminal.
    `stdin` is the text the command reads, if any."""

    def __call__(
        self, argv: Sequence[str], cwd: Path, capture: bool, stdin: str | None = None
    ) -> Completed | Refused: ...


def run_process(
    argv: Sequence[str], cwd: Path, capture: bool, stdin: str | None = None
) -> Completed | Refused:
    try:
        # A captured call without input gets no stdin, so a prompt fails at once, never
        # waits unseen.
        no_input = subprocess.DEVNULL if capture else None
        done = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin,
            stdin=None if stdin is not None else no_input,
            capture_output=capture,
            text=True,
            check=False,
        )
    except OSError as error:
        return Refused(
            f"Can't run {argv[0]}: {error.strerror or error}. Is it installed?"
        )
    return Completed(done.returncode, done.stdout or "", done.stderr or "")


def pin_of(ls_json: str, workspace: Path) -> tuple[str, Path] | Refused:
    """The version and install path from `mise ls --current --json npm:qretools`."""
    try:
        pins = json.loads(ls_json)
        # A tool pinned to several versions uses the first, as mise does.
        pin = pins[0] if pins else None
        if pin is None:
            return Refused(
                f"{workspace} pins no qretools. Add {TOOL} to its mise.toml."
            )
        if not pin["installed"]:
            return Refused(
                f"qretools {pin['version']} isn't installed. Run `mise install` in {workspace}."
            )
        return str(pin["version"]), Path(pin["install_path"])
    except (ValueError, LookupError, TypeError):
        return Refused("Can't read what mise says about qretools. Is mise up to date?")


def binary_of(bin_paths: str, install: Path) -> Path | Refused:
    """The qretools file inside the pinned install, from `mise bin-paths npm:qretools`."""
    for line in bin_paths.splitlines():
        binary = Path(line.strip(), "qretools")
        if binary.is_relative_to(install) and binary.is_file():
            return binary
    return Refused(f"mise gives no qretools file inside {install}. Run `mise install`.")


def failed(what: str, done: Completed) -> Refused:
    detail = done.stderr.strip()
    return Refused(
        f"{what} failed (exit {done.code})." + (f"\n{detail}" if detail else "")
    )


def resolve(workspace: Path, run: Run = run_process) -> Qretools | Refused:
    """The qretools that `workspace` pins, or why there is none."""
    listed = run(["mise", "ls", "--current", "--json", TOOL], workspace, True)
    if isinstance(listed, Refused):
        return listed
    if listed.code != 0:
        return failed("mise ls", listed)
    pin = pin_of(listed.stdout, workspace)
    if isinstance(pin, Refused):
        return pin
    version, install = pin
    paths = run(["mise", "bin-paths", TOOL], workspace, True)
    if isinstance(paths, Refused):
        return paths
    if paths.code != 0:
        return failed("mise bin-paths", paths)
    binary = binary_of(paths.stdout, install)
    if isinstance(binary, Refused):
        return binary
    return Qretools(workspace, ("mise", "exec", "--", str(binary)), version)


def harness(cwd: Path) -> Qretools | Refused:
    """QRETOOLS through npx, run in `cwd`; or the development build OVERRIDE names."""
    override = os.environ.get(OVERRIDE)
    if not override:
        return Qretools(cwd, ("npx", "-y", QRETOOLS), QRETOOLS.partition("@")[2])
    binary = Path(override).resolve()
    try:
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    except OSError as error:
        return Refused(f"{OVERRIDE} names {binary}, which can't be read: {error}.")
    # A development build has no release to name, so its digest is its version.
    return Qretools(cwd, ("node", str(binary)), f"development build sha256:{digest}")


def build(q: Qretools, outdir: Path, run: Run = run_process) -> Built | Refused:
    """`qretools build`: the workspace's versioned DDI, written to `outdir/ddi.json`.

    qretools prints its own findings and refusals; they go straight to the terminal.
    """
    done = run(q.argv("build", ".", "-o", str(outdir)), q.workspace, False)
    if isinstance(done, Refused):
        return done
    if done.code != 0:
        return Refused(f"qretools build refused or failed (exit {done.code}).")
    return Built(outdir / "ddi.json")


def next_step(
    q: Qretools, instrument: Path, state: object, run: Run = run_process
) -> Mapping[str, Any] | Refused:
    """`qretools next`: the next step of an interview, as the JSON qretools replies.

    Exit 1 means the state can't belong to the instrument: a bug here, or a DDI that
    changed during the run.
    """
    done = run(
        q.argv("next", str(instrument), "-"), q.workspace, True, json.dumps(state)
    )
    if isinstance(done, Refused):
        return done
    if done.code != 0:
        return failed("qretools next", done)
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        return Refused("qretools next didn't reply with a JSON object.")
    return reply


def responses(
    q: Qretools, args: Sequence[str], run: Run = run_process
) -> Refused | None:
    """`qretools responses` with `args`, in the run folder. qretools prints its own
    findings; they go straight to the terminal."""
    done = run(q.argv("responses", *args), q.workspace, False)
    if isinstance(done, Refused):
        return done
    if done.code != 0:
        return Refused(f"qretools responses refused or failed (exit {done.code}).")
    return None
