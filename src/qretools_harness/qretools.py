"""The only module that runs the qretools CLI.

The harness runs one qretools version, QRETOOLS, through `npx`, which runs exactly that
version from npm, never a qretools found on PATH. OVERRIDE, for development only, names
a qretools build to run with node in its place.

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

# The qretools that the harness calls. Change it only here.
QRETOOLS = "qretools@2.0.0-alpha.13"
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
    """A qretools ready to run: in `cwd`, with `command`."""

    cwd: Path
    command: tuple[str, ...]
    version: str  # the version, or the digest of a development build

    def argv(self, *args: str) -> list[str]:
        """The command line that runs qretools with `args`."""
        return [*self.command, *args]


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


def failed(what: str, done: Completed) -> Refused:
    detail = done.stderr.strip()
    return Refused(
        f"{what} failed (exit {done.code})." + (f"\n{detail}" if detail else "")
    )


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


def next_step(
    q: Qretools, instrument: Path | str, state: object, run: Run = run_process
) -> Mapping[str, Any] | Refused:
    """`qretools next`: the next step of an interview, as the JSON qretools replies.

    `instrument` is a path or an https URL, which qretools reads at each call.

    Exit 1 means the state can't belong to the instrument: a bug here, or a DDI that
    changed during the run.
    """
    done = run(q.argv("next", str(instrument), "-"), q.cwd, True, json.dumps(state))
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
    done = run(q.argv("responses", *args), q.cwd, False)
    if isinstance(done, Refused):
        return done
    if done.code != 0:
        return Refused(f"qretools responses refused or failed (exit {done.code}).")
    return None
