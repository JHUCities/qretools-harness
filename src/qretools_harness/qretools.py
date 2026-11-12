"""The only module that runs the qretools CLI.

qretools runs with the version that the workspace's mise.toml pins. A qretools found on
PATH is never used: a global one can shadow mise's. So this module asks mise where the
pinned version is installed, and runs that file by its absolute path, through
`mise exec` so that node is the workspace's too.

Every function returns a value. Nothing here raises for a refusal or a failed command.
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

TOOL = "npm:qretools"


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
    """The qretools that a workspace pins, ready to run."""

    workspace: Path
    binary: Path
    version: str


@dataclass(frozen=True)
class Built:
    ddi: Path


# Runs argv in a directory. With capture false, output goes straight to the terminal.
Run = Callable[[Sequence[str], Path, bool], Completed | Refused]


def run_process(argv: Sequence[str], cwd: Path, capture: bool) -> Completed | Refused:
    try:
        # A captured call gets no stdin, so a prompt from mise fails at once, never waits unseen.
        stdin = subprocess.DEVNULL if capture else None
        done = subprocess.run(
            argv, cwd=cwd, stdin=stdin, capture_output=capture, text=True, check=False
        )
    except OSError as error:
        return Refused(
            f"Can't run {argv[0]}: {error.strerror or error}. Is mise installed?"
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
    return Qretools(workspace, binary, version)


def build(q: Qretools, outdir: Path, run: Run = run_process) -> Built | Refused:
    """`qretools build`: the workspace's versioned DDI, written to `outdir/ddi.json`.

    qretools prints its own findings and refusals; they go straight to the terminal.
    """
    argv = ["mise", "exec", "--", str(q.binary), "build", ".", "-o", str(outdir)]
    done = run(argv, q.workspace, False)
    if isinstance(done, Refused):
        return done
    if done.code != 0:
        return Refused(f"qretools build refused or failed (exit {done.code}).")
    return Built(outdir / "ddi.json")
