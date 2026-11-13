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
    check = commands.add_parser(
        "check-config", help="check a config against the DDI of its instrument"
    )
    check.add_argument("config", type=Path, help="the config (TOML)")
    return top


def checked(config_path: Path) -> config.Config | qretools.Refused:
    """The config, if it reads and every prompt matches its instrument's DDI."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return qretools.Refused(f"Can't read {config_path}: {error}.")
    parsed = config.parse(text, config_path.parent.absolute())
    if isinstance(parsed, qretools.Refused):
        return qretools.Refused(f"{config_path}: {parsed.reason}")
    try:
        ddi = json.loads(parsed.instrument.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return qretools.Refused(
            f"Can't read the instrument {parsed.instrument}: {error}."
        )
    except ValueError:
        return qretools.Refused(f"The instrument {parsed.instrument} isn't JSON.")
    return config.rosters(ddi) or config.stale(parsed, ddi) or parsed


def check_config(config_path: Path) -> int:
    parsed = checked(config_path)
    if isinstance(parsed, qretools.Refused):
        return refuse(parsed)
    print(
        f"{config_path} matches {parsed.instrument}:"
        f" {len(parsed.prompts)} prompt(s) checked."
    )
    return 0


def refuse(refused: qretools.Refused) -> int:
    print(f"qretools-harness: {refused.reason}", file=sys.stderr)
    return 1


def main(
    argv: Sequence[str] | None = None, run: qretools.Run = qretools.run_process
) -> int:
    args = parser().parse_args(argv)
    match args.command:
        case "check-config":
            return check_config(args.config)
    return 2  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
