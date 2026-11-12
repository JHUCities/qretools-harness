"""A stand-in for running processes: answers by the command's first words, and records calls."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from qretools_harness.qretools import Completed, Refused


def pinned(install: Path, installed: bool = True) -> Completed:
    pin = {
        "version": "2.0.0-alpha.10",
        "install_path": str(install),
        "installed": installed,
    }
    return Completed(0, json.dumps([pin]))


@dataclass
class Fake:
    answers: dict[str, Completed | Refused]
    calls: list[tuple[list[str], Path, bool]] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, capture: bool
    ) -> Completed | Refused:
        self.calls.append((list(argv), cwd, capture))
        for prefix, answer in self.answers.items():
            if " ".join(argv).startswith(prefix):
                return answer
        raise AssertionError(f"unexpected command: {argv}")


def installed(root: Path) -> Path:
    """A pinned install under `root`, holding a qretools file as mise's npm backend lays it out."""
    install = root / "npm-qretools"
    (install / "node_modules/.bin").mkdir(parents=True, exist_ok=True)
    (install / "node_modules/.bin/qretools").touch()
    return install


def working(root: Path, code: int = 0) -> Fake:
    """mise with qretools pinned and installed under `root`; the build exits with `code`."""
    install = installed(root)
    return Fake(
        {
            "mise ls": pinned(install),
            "mise bin-paths": Completed(0, f"{install}/node_modules/.bin\n"),
            "mise exec": Completed(code),
        }
    )
