"""Stand-ins: for running processes (answers by the command's first words, and records
calls), and for a model server."""

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    """An answer is a result, or a function of the command's stdin (for `next`)."""

    answers: dict[str, Completed | Refused | Callable[[str], Completed | Refused]]
    calls: list[tuple[list[str], Path, bool]] = field(default_factory=list)
    stdins: list[str | None] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, capture: bool, stdin: str | None = None
    ) -> Completed | Refused:
        self.calls.append((list(argv), cwd, capture))
        self.stdins.append(stdin)
        for prefix, answer in self.answers.items():
            if " ".join(argv).startswith(prefix):
                return answer(stdin or "") if callable(answer) else answer
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


GOOD = {
    "choices": [{"index": 0, "finish_reason": "length", "message": {"content": "Yes"}}],
    "model": "served-model",
    "system_fingerprint": "b12110-cd959bae9",
    "usage": {"prompt_tokens": 13, "completion_tokens": 1},
}


class Server(ThreadingHTTPServer):
    status = 200
    body: bytes = json.dumps(GOOD).encode()
    delay = 0.0
    received: list[tuple[str, object]]


class Handler(BaseHTTPRequestHandler):
    server: Server

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        self.server.received.append((self.path, json.loads(self.rfile.read(length))))
        if self.server.delay:
            threading.Event().wait(self.server.delay)
        self.send_response(self.server.status)
        self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *args: object) -> None:
        pass
