"""The command line. Exit codes: 0 done, 1 refused or failed, 2 usage."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from qretools_harness import qretools


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="qretools-harness",
        description="Runs qretools instruments and reads answer sets, keyed by DDI variable.",
    )
    commands = top.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build", help="build a workspace's versioned DDI with qretools"
    )
    build.add_argument("workspace", type=Path, help="the qretools workspace")
    build.add_argument(
        "-o", "--outdir", type=Path, help="where to write (default: <workspace>/dist)"
    )
    return top


def build(workspace: Path, outdir: Path | None, run: qretools.Run) -> int:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        return refuse(qretools.Refused(f"{workspace} isn't a directory."))
    # Relative to where the command was typed, never to the workspace.
    out = (outdir or workspace / "dist").resolve()
    q = qretools.resolve(workspace, run)
    if isinstance(q, qretools.Refused):
        return refuse(q)
    built = qretools.build(q, out, run)
    if isinstance(built, qretools.Refused):
        return refuse(built)
    print(f"DDI written to {built.ddi} (qretools {q.version})")
    return 0


def refuse(refused: qretools.Refused) -> int:
    print(f"qretools-harness: {refused.reason}", file=sys.stderr)
    return 1


def main(
    argv: Sequence[str] | None = None, run: qretools.Run = qretools.run_process
) -> int:
    args = parser().parse_args(argv)
    match args.command:
        case "build":
            return build(args.workspace, args.outdir, run)
    return 2  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
