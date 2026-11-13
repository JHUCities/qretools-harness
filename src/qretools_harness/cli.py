"""The command line. Exit codes: 0 done, 1 refused or failed, 2 usage."""

import argparse
import csv
import io
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from qretools_harness import chat, config, interview, qretools

# The names qretools provenance takes for a run folder: every ID it writes is made from it.
FOLDER_NAME = re.compile(r"[A-Za-z0-9*@$_-]+")


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
    respond = commands.add_parser(
        "respond",
        help="interview a model through an instrument; write a run folder",
        description="Interview a model through an instrument and write a run folder."
        " qretools is the version that mise pins in the current directory.",
    )
    respond.add_argument("config", type=Path, help="the config (TOML)")
    respond.add_argument(
        "ddi", type=Path, help="the instrument's DDI (dist/instruments/<name>.json)"
    )
    respond.add_argument(
        "-o", "--outdir", type=Path, required=True, help="the run folder (runs/<id>)"
    )
    return top


def checked(config_path: Path, ddi_path: Path) -> config.Config | qretools.Refused:
    """The config, if it reads and every prompt matches the DDI."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return qretools.Refused(f"Can't read {config_path}: {error}.")
    parsed = config.parse(text)
    if isinstance(parsed, qretools.Refused):
        return qretools.Refused(f"{config_path}: {parsed.reason}")
    try:
        ddi = json.loads(ddi_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return qretools.Refused(f"Can't read {ddi_path}: {error}.")
    except ValueError:
        return qretools.Refused(f"{ddi_path} isn't JSON.")
    return config.stale(parsed, ddi) or parsed


def check_config(config_path: Path, ddi_path: Path) -> int:
    parsed = checked(config_path, ddi_path)
    if isinstance(parsed, qretools.Refused):
        return refuse(parsed)
    print(f"{config_path} matches {ddi_path}: {len(parsed.prompts)} prompt(s) checked.")
    return 0


def answers_csv(answers: Mapping[str, interview.State]) -> str:
    """Each respondent's final answers as long CSV, as `qretools responses` writes it."""
    out = io.StringIO()
    rows = csv.writer(out, lineterminator="\n")
    rows.writerow(["respondent", "variable", "row", "value"])
    for respondent, state in answers.items():
        for a in state["answers"]:
            rows.writerow([respondent, a["variable"], a.get("row", ""), a["value"]])
    return out.getvalue()


def run_json(
    traces: Sequence[interview.Trace], name: str, start: str, end: str
) -> dict[str, object]:
    """run.json: what no file says. The runtime is the model the server says it served,
    and its build if every reply gives the same one."""
    calls = [t for t in traces if t.get("kind") == "call"]
    models = {t["model"] for t in calls if t.get("model")}
    builds = {t.get("fingerprint") for t in calls}
    runtime: dict[str, object] = {
        "name": str(models.pop()) if len(models) == 1 else name
    }
    if len(builds) == 1 and None not in builds:
        runtime["version"] = str(builds.pop())
    return {"respondent": "synthetic", "runtime": runtime, "start": start, "end": end}


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def respond(
    config_path: Path,
    ddi_path: Path,
    out: Path,
    run: qretools.Run,
    complete: interview.Complete | None = None,
) -> int:
    cfg = checked(config_path, ddi_path)
    if isinstance(cfg, qretools.Refused):
        return refuse(cfg)
    seed = cfg.generation.get("seed")
    if not isinstance(seed, int):
        return refuse(
            qretools.Refused(
                f"{config_path}: `respond` needs `generation.seed`: each respondent's"
                " seed is made from it, so that a run can be made again."
            )
        )
    out = out.resolve()
    if not FOLDER_NAME.fullmatch(out.name):
        return refuse(
            qretools.Refused(
                f"The run folder's name {out.name} must be letters, digits, - and _ only:"
                " qretools makes the IDs of the provenance from it."
            )
        )
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        return refuse(qretools.Refused(f"{out} isn't an empty folder."))
    q = qretools.resolve(Path.cwd(), run)
    if isinstance(q, qretools.Refused):
        return refuse(q)

    def ask_model(
        messages: Sequence[interview.Message], seed: int
    ) -> chat.Reply | qretools.Refused:
        return chat.complete(cfg.model, {**cfg.generation, "seed": seed}, messages)

    out.mkdir(parents=True, exist_ok=True)
    (out / "config.toml").write_bytes(config_path.read_bytes())
    (out / "ddi.json").write_bytes(ddi_path.read_bytes())
    traces: list[interview.Trace] = []
    finals: dict[str, interview.State] = {}
    start = now()
    with (out / "traces.jsonl").open("a", encoding="utf-8") as file:

        def record(trace: interview.Trace) -> None:
            traces.append(trace)
            file.write(json.dumps(trace, ensure_ascii=False) + "\n")
            file.flush()

        # qretools provenance doesn't record its own version yet; the traces do.
        record(
            {
                "kind": "start",
                "qretools": q.version,
                "qretools-harness": version("qretools-harness"),
            }
        )
        for i in range(1, cfg.respondents + 1):
            respondent = str(i)
            state = interview.interview(
                respondent,
                seed + i - 1,
                cfg,
                lambda s: qretools.next_step(q, out / "ddi.json", s, run),
                complete or ask_model,
                record,
            )
            if isinstance(state, qretools.Refused):
                return refuse(
                    qretools.Refused(
                        f"{state.reason}\nThe run stopped. {out / 'traces.jsonl'}"
                        " holds what happened; the folder has no answers.csv."
                    )
                )
            finals[respondent] = state
    (out / "answers.csv").write_text(answers_csv(finals), encoding="utf-8")
    facts = run_json(traces, cfg.model.name, start, now())
    (out / "run.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    for name in sorted(
        {str(t["input"]) for t in traces if t.get("how") == "not in the config"}
    ):
        print(
            f"qretools-harness: the input {name} isn't in the config;"
            " it was sent as not known (null).",
            file=sys.stderr,
        )
    calls = sum(1 for t in traces if t.get("kind") == "call")
    failed = sum(1 for t in traces if "failure" in t)
    gave_up = sum(1 for t in traces if t.get("kind") == "no_answer")
    # How near the model's context the conversation came: it grows with each question.
    largest = max(
        (
            int(u.get("prompt_tokens", 0))
            for t in traces
            if isinstance(u := t.get("usage"), dict)
        ),
        default=0,
    )
    print(
        f"{cfg.respondents} respondent(s), {calls} model call(s), {failed} reply(ies)"
        f" not allowed, {gave_up} `no_answer` code(s) recorded; the largest prompt"
        f" had {largest} tokens."
    )
    written = qretools.provenance(q, out, run)
    if isinstance(written, qretools.Refused):
        return refuse(written)
    print(f"Run folder {out} written, with {written.name} (qretools {q.version}).")
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
        case "respond":
            return respond(args.config, args.ddi, args.outdir, run)
    return 2  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
