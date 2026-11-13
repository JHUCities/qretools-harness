"""The command line. Exit codes: 0 done, 1 refused or failed, 2 usage."""

import argparse
import csv
import hashlib
import io
import json
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from qretools_harness import chat, config, interview, qretools


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
    respond = commands.add_parser(
        "respond",
        help="interview a model through the config's instrument; write a dataset",
        description="Interview a model through the instrument that the config names,"
        " write the answers and traces into a run folder, and make the dataset with"
        f" `{qretools.QRETOOLS} responses`.",
    )
    respond.add_argument("config", type=Path, help="the config (TOML)")
    respond.add_argument(
        "-n", type=positive, required=True, help="the number of respondents"
    )
    respond.add_argument(
        "-o", "--outdir", type=Path, required=True, help="the run folder: new or empty"
    )
    return top


def positive(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError("must be a whole number, 1 or more")
    return int(text)


Get = Callable[[str], bytes | qretools.Refused]  # the bytes at an https URL


def checked(
    config_path: Path, get: Get = chat.read_url
) -> tuple[config.Config, bytes] | qretools.Refused:
    """The config, if it reads and every prompt matches its instrument's DDI; and the
    bytes of that DDI as the harness read them."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return qretools.Refused(f"Can't read {config_path}: {error}.")
    parsed = config.parse(text, config_path.parent.absolute())
    if isinstance(parsed, qretools.Refused):
        return qretools.Refused(f"{config_path}: {parsed.reason}")
    if isinstance(parsed.instrument, str):
        raw = get(parsed.instrument)
        if isinstance(raw, qretools.Refused):
            return raw
    else:
        try:
            raw = parsed.instrument.read_bytes()
        except OSError as error:
            return qretools.Refused(
                f"Can't read the instrument {parsed.instrument}: {error}."
            )
    try:
        ddi = json.loads(raw)
    except ValueError:  # UnicodeDecodeError is a ValueError
        return qretools.Refused(f"The instrument {parsed.instrument} isn't JSON.")
    return config.rosters(ddi) or config.stale(parsed, ddi) or (parsed, raw)


def check_config(config_path: Path, get: Get = chat.read_url) -> int:
    done = checked(config_path, get)
    if isinstance(done, qretools.Refused):
        return refuse(done)
    parsed, _ = done
    print(
        f"{config_path} matches {parsed.instrument}:"
        f" {len(parsed.prompts)} prompt(s) checked."
    )
    return 0


Interview = tuple[
    int, str, str, list[interview.Answer]
]  # respondent, start, end, values


def answers_csv(interviews: Sequence[Interview]) -> str:
    """The long CSV that `qretools responses` reads: each finished respondent's start
    time, values and end time. A respondent who didn't finish has no lines."""
    out = io.StringIO()
    rows = csv.writer(out, lineterminator="\n")
    rows.writerow(["respondent", "variable", "row", "value"])
    for i, start, end, values in interviews:
        rows.writerow([i, "start", "", start])
        for a in values:
            rows.writerow([i, a["variable"], a.get("row", ""), a["value"]])
        rows.writerow([i, "end", "", end])
    return out.getvalue()


def runtime_of(
    traces: Sequence[interview.Trace], info: Mapping[str, object]
) -> tuple[str, str | None]:
    """The server's software and its build: from the replies if they all agree, else
    from what the server said about itself before the run. The model and its settings
    are not the runtime: the cited config pins them."""

    def agreed(key: str) -> str | None:
        found = {t.get(key) for t in traces if t.get("kind") == "call"}
        return str(found.pop()) if len(found) == 1 and None not in found else None

    props = info.get("props")
    build = props.get("build_info") if isinstance(props, dict) else None
    server = info.get("server")
    return (
        agreed("server") or (str(server) if server else "unknown"),
        agreed("fingerprint") or (str(build) if build else None),
    )


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def respond(
    config_path: Path,
    respondents: int,
    out: Path,
    run: qretools.Run,
    complete: interview.Complete | None = None,
    clock: Callable[[], str] = now,
    command: Sequence[str] = (),
    info: Callable[[config.Model], dict[str, object]] = chat.server_info,
    get: Get = chat.read_url,
) -> int:
    done = checked(config_path, get)
    if isinstance(done, qretools.Refused):
        return refuse(done)
    cfg, raw = done
    seed = cfg.generation.get("seed")
    if not isinstance(seed, int):
        return refuse(
            qretools.Refused(
                f"{config_path}: `respond` needs `generation.seed`: each respondent's"
                " seed is made from it, so that a run can be made again."
            )
        )
    out = out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        return refuse(qretools.Refused(f"{out} isn't an empty folder."))
    q = qretools.harness(out)
    if isinstance(q, qretools.Refused):
        return refuse(q)
    # A URL goes to qretools as written: qretools reads it again at each step, and
    # `responses` reads it once more (the owner chose this over a copy in the run
    # folder). So the digest in the trace is of what check-config read here only.
    instrument = (
        cfg.instrument if isinstance(cfg.instrument, str) else cfg.instrument.resolve()
    )

    def ask_model(
        messages: Sequence[interview.Message], seed: int
    ) -> chat.Reply | qretools.Refused:
        return chat.complete(cfg.model, {**cfg.generation, "seed": seed}, messages)

    out.mkdir(parents=True, exist_ok=True)
    (out / "config.toml").write_bytes(config_path.read_bytes())
    server = info(cfg.model)
    traces: list[interview.Trace] = []
    interviews: list[Interview] = []
    stopped: list[str] = []
    with (out / "traces.jsonl").open("a", encoding="utf-8") as file:

        def record(trace: interview.Trace) -> None:
            traces.append(trace)
            file.write(json.dumps(trace, ensure_ascii=False) + "\n")
            file.flush()

        # Every parameter that can change the run's outcome: the dataset cites this file.
        record(
            {
                "kind": "start",
                "command": list(command),
                "respondents": respondents,
                "outdir": str(out),
                "seeds": [seed + i - 1 for i in range(1, respondents + 1)],
                "config": config.effective(cfg),
                "instrument": {
                    "url" if isinstance(instrument, str) else "path": str(instrument),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                "qretools": {"version": q.version, "command": list(q.command)},
                "qretools-harness": version("qretools-harness"),
                "server": server,
            }
        )
        for i in range(1, respondents + 1):
            start = clock()
            values = interview.interview(
                str(i),
                seed + i - 1,
                cfg,
                lambda s: qretools.next_step(q, instrument, s, run),
                complete or ask_model,
                record,
            )
            if isinstance(values, qretools.Refused):
                record({"kind": "stopped", "respondent": str(i), "why": values.reason})
                stopped.append(f"respondent {i} stopped: {values.reason}")
                if isinstance(values, chat.Unreachable):
                    # Every later respondent would wait and fail the same way.
                    stopped.append("The run stopped: the model server gave no answer.")
                    break
                continue
            interviews.append((i, start, clock(), values))
    for name in sorted(
        {str(t["input"]) for t in traces if t.get("how") == "not in the config"}
    ):
        print(
            f"qretools-harness: the input {name} isn't in the config;"
            " it was sent as not known (null).",
            file=sys.stderr,
        )
    print(summary(traces, respondents))
    if not interviews:
        return refuse(
            qretools.Refused(
                "\n".join(stopped)
                + f"\nNo respondent finished, so there is no dataset. {out / 'traces.jsonl'}"
                " holds what happened."
            )
        )
    (out / "answers.csv").write_text(answers_csv(interviews), encoding="utf-8")
    name, build = runtime_of(traces, server)
    args = [
        "answers.csv",
        "--ddi",
        str(instrument),
        "--synthetic",
        "--runtime",
        name,
        *(["--runtime-version", build] if build else []),
        "--file",
        "traces.jsonl",
        "--file",
        "config.toml",
        "-o",
        "dataset.json",
    ]
    made = qretools.responses(q, args, run)
    if made is not None:
        stopped.append(
            f"{made.reason}\nThe answers are in {out}. To try again:\n"
            f"cd {shlex.quote(str(out))} && {shlex.join(q.argv('responses', *args))}"
        )
    else:
        print(f"Dataset {out / 'dataset.json'} written (qretools {q.version}).")
    if stopped:
        return refuse(qretools.Refused("\n".join(stopped)))
    return 0


def summary(traces: Sequence[Mapping[str, object]], respondents: int) -> str:
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
    return (
        f"{respondents} respondent(s), {calls} model call(s), {failed} reply(ies)"
        f" not allowed, {gave_up} `no_answer` code(s) recorded; the largest prompt"
        f" had {largest} tokens."
    )


def refuse(refused: qretools.Refused) -> int:
    print(f"qretools-harness: {refused.reason}", file=sys.stderr)
    return 1


def main(
    argv: Sequence[str] | None = None,
    run: qretools.Run = qretools.run_process,
    get: Get = chat.read_url,
) -> int:
    args = parser().parse_args(argv)
    match args.command:
        case "check-config":
            return check_config(args.config, get)
        case "respond":
            return respond(
                args.config,
                args.n,
                args.outdir,
                run,
                command=["qretools-harness", *(sys.argv[1:] if argv is None else argv)],
                get=get,
            )
    return 2  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
