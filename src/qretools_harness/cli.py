"""The command line. Exit codes: 0 done, 1 refused or failed, 2 usage."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from qretools_harness import config, qretools


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
    check = commands.add_parser(
        "check-config", help="check a config against an instrument's DDI"
    )
    check.add_argument("config", type=Path, help="the config (TOML)")
    check.add_argument("ddi", type=Path, help="the instrument's ddi.json")
    return top


def check_config(config_path: Path, ddi_path: Path) -> int:
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return refuse(qretools.Refused(f"Can't read {config_path}: {error}."))
    parsed = config.parse(text)
    if isinstance(parsed, qretools.Refused):
        return refuse(qretools.Refused(f"{config_path}: {parsed.reason}"))
    try:
        ddi = json.loads(ddi_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return refuse(qretools.Refused(f"Can't read {ddi_path}: {error}."))
    except ValueError:
        return refuse(qretools.Refused(f"{ddi_path} isn't JSON."))
    problem = config.stale(parsed, ddi)
    if problem is not None:
        return refuse(problem)
    print(f"{config_path} matches {ddi_path}: {len(parsed.prompts)} prompt(s) checked.")
    return 0


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
        case "check-config":
            return check_config(args.config, args.ddi)
    return 2  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
