"""`respond` end to end, with stand-ins for qretools and for the model."""

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fake import Fake

from qretools_harness.chat import Reply, Unreachable
from qretools_harness.cli import main, respond
from qretools_harness.qretools import QRETOOLS, Completed, Refused, run_process

CONFIG = """
instrument = "instrument.json"
[model]
endpoint = "http://127.0.0.1:1/v1"
name = "asked-model"
timeout = 5
[generation]
seed = 10
[run]
system = "Answer."
no_answer = "N"
"""
MISSING = [{"code": "N", "label": "No answer"}]
ASK = {
    "kind": "ask",
    "step": "urn:step:tenure",
    "question": "tenure",
    "questionUrn": "urn:ddi:a:tenure:1",
    "text": "Own, or rent?",
    "instructions": [],
    "domain": {
        "kind": "choice",
        "variable": "urn:v:tenure",
        "name": "tenure",
        "missing": MISSING,
        "choices": [{"code": "1", "label": "Own"}, {"code": "2", "label": "Rent"}],
    },
    "statements": [],
    "notes": [],
}
END = {"kind": "end", "how": "end", "statements": [], "notes": []}
NEXT = f"npx -y {QRETOOLS} next"
RESPONSES = f"npx -y {QRETOOLS} responses"


def next_of(stdin: str) -> Completed:
    """qretools next for a one-question instrument."""
    state: dict[str, Any] = json.loads(stdin)
    return Completed(0, json.dumps(END if state["answers"] else ASK))


def qretools() -> Fake:
    return Fake({NEXT: next_of, RESPONSES: Completed(0)})


class Model:
    """Replies "2"; the server software and build are given per call, in turn."""

    def __init__(self, *served: tuple[str | None, str | None]) -> None:
        self.served = list(served)
        self.seeds: list[int] = []

    def __call__(self, messages: Sequence[Mapping[str, str]], seed: int) -> Reply:
        self.seeds.append(seed)
        server, build = self.served.pop(0) if self.served else ("llama.cpp", "b1")
        return Reply("2", "stop", "served", build, {}, {}, server)


SERVER: dict[str, object] = {
    "server": "llama.cpp",
    "props": {"build_info": "b0", "default_generation_settings": {"n_ctx": 8192}},
}


def info(model: object) -> dict[str, object]:
    return SERVER


def files(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(CONFIG)
    (tmp_path / "instrument.json").write_text(
        json.dumps({"QuestionItem": {"k": {"ID": "tenure"}}})
    )
    return config


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QRETOOLS_HARNESS_QRETOOLS", raising=False)


def test_respond_writes_the_run_folder_and_makes_the_dataset(tmp_path: Path) -> None:
    config = files(tmp_path)
    out = tmp_path / "runs" / "try-1"
    fake, model = qretools(), Model()
    times = iter(["T1", "T2", "T3", "T4"])
    assert respond(config, 2, out, fake, model, lambda: next(times), info=info) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "answers.csv",
        "config.toml",
        "traces.jsonl",
    ]  # dataset.json is the fake's to write, and it writes nothing
    assert (out / "answers.csv").read_text() == (
        "respondent,variable,row,value\n"
        "1,start,,T1\n1,urn:v:tenure,,2\n1,end,,T2\n"
        "2,start,,T3\n2,urn:v:tenure,,2\n2,end,,T4\n"
    )
    assert (out / "config.toml").read_bytes() == config.read_bytes()
    assert model.seeds == [10, 11]  # each respondent its own seed
    argv, cwd, _ = fake.calls[-1]
    assert cwd == out.resolve()
    assert argv[3:] == [
        "responses",
        "answers.csv",
        "--ddi",
        str((tmp_path / "instrument.json").resolve()),
        "--synthetic",
        "--runtime",
        "llama.cpp",
        "--runtime-version",
        "b1",
        "--file",
        "traces.jsonl",
        "--file",
        "config.toml",
        "-o",
        "dataset.json",
    ]


def test_the_first_trace_records_every_parameter_of_the_run(tmp_path: Path) -> None:
    config, out = files(tmp_path), tmp_path / "r"
    command = ["qretools-harness", "respond", str(config), "-n", "2", "-o", str(out)]
    assert respond(config, 2, out, qretools(), Model(), info=info, command=command) == 0
    start = json.loads((out / "traces.jsonl").read_text().splitlines()[0])
    assert start["kind"] == "start"
    assert start["command"] == command
    assert start["respondents"] == 2
    assert start["outdir"] == str(out.resolve())
    assert start["seeds"] == [10, 11]
    assert start["config"] == {
        "instrument": str(tmp_path / "instrument.json"),
        "model": {
            "endpoint": "http://127.0.0.1:1/v1",
            "name": "asked-model",
            "timeout": 5,
        },
        "generation": {"seed": 10},
        "system": "Answer.",
        "missing": [],
        "no_answer": "N",
        "draw": [],
        "inputs": {},
        "prompts": {},
    }
    assert start["instrument"]["sha256"]
    assert start["qretools"] == {
        "version": QRETOOLS.partition("@")[2],
        "command": ["npx", "-y", QRETOOLS],
    }
    assert start["server"] == SERVER


@pytest.mark.parametrize(
    ("served", "server", "runtime", "build"),
    [
        (
            [("a", "b1"), ("b", "b1")],
            {"server": "s", "props": {"build_info": "b0"}},
            "s",
            "b1",
        ),
        ([(None, None), (None, None)], {"props": {}}, "unknown", None),
        (
            [(None, "b1"), (None, "b2")],
            {"props": {"build_info": "b0"}},
            "unknown",
            "b0",
        ),
    ],
)
def test_the_runtime_is_the_server_software_and_its_build(
    tmp_path: Path,
    served: list[tuple[str | None, str | None]],
    server: dict[str, object],
    runtime: str,
    build: str | None,
) -> None:
    fake = qretools()
    model = Model(*served)
    out = tmp_path / "r"
    assert respond(files(tmp_path), 2, out, fake, model, info=lambda m: server) == 0
    argv, _, _ = fake.calls[-1]
    assert argv[argv.index("--runtime") + 1] == runtime
    if build:
        assert argv[argv.index("--runtime-version") + 1] == build
    else:
        assert "--runtime-version" not in argv


def failing(
    *bad: int, error: type[Refused] = Refused
) -> Callable[..., Reply | Refused]:
    """A model whose replies fail for the respondents (by seed - 9) in `bad`."""

    def reply(messages: Sequence[Mapping[str, str]], seed: int) -> Reply | Refused:
        if seed - 9 in bad:
            return error("The model server answered 400. Context too long.")
        return Model()(messages, seed)

    return reply


def test_a_respondent_who_fails_is_left_out_and_the_others_are_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, out = qretools(), tmp_path / "r"
    assert respond(files(tmp_path), 3, out, fake, failing(2), info=info) == 1
    answers = (out / "answers.csv").read_text()
    assert [line.split(",")[0] for line in answers.splitlines()[1:]] == ["1"] * 3 + [
        "3"
    ] * 3
    traces = [json.loads(t) for t in (out / "traces.jsonl").read_text().splitlines()]
    stopped = [t for t in traces if t["kind"] == "stopped"]
    assert [t["respondent"] for t in stopped] == ["2"]
    assert "Context too long" in stopped[0]["why"]
    assert any("responses" in argv for argv, _, _ in fake.calls)  # the dataset is made
    err = capsys.readouterr().err
    assert "respondent 2 stopped" in err and "Context too long" in err


def test_no_dataset_when_no_respondent_finishes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, out = qretools(), tmp_path / "r"
    assert respond(files(tmp_path), 2, out, fake, failing(1, 2), info=info) == 1
    assert sorted(p.name for p in out.iterdir()) == ["config.toml", "traces.jsonl"]
    assert not any("responses" in argv for argv, _, _ in fake.calls)
    assert "No respondent finished" in capsys.readouterr().err


def test_a_server_that_cant_be_reached_stops_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, out = qretools(), tmp_path / "r"
    model = failing(2, 3, error=Unreachable)
    assert respond(files(tmp_path), 3, out, fake, model, info=info) == 1
    traces = [json.loads(t) for t in (out / "traces.jsonl").read_text().splitlines()]
    assert [t["respondent"] for t in traces if t["kind"] == "stopped"] == ["2"]
    assert "The run stopped" in capsys.readouterr().err
    assert (out / "answers.csv").read_text().count(",start,") == 1


def test_respond_refuses_a_folder_that_isnt_empty(tmp_path: Path) -> None:
    out = tmp_path / "run1"
    out.mkdir()
    (out / "answers.csv").touch()
    assert respond(files(tmp_path), 1, out, Fake({}), Model(), info=info) == 1


def test_respond_needs_a_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = files(tmp_path)
    config.write_text(CONFIG.replace("seed = 10", ""))
    assert respond(config, 1, tmp_path / "r", Fake({}), Model(), info=info) == 1
    assert "generation.seed" in capsys.readouterr().err


@pytest.mark.parametrize("n", ["0", "-1", "x"])
def test_the_number_of_respondents_is_one_or_more(n: str) -> None:
    with pytest.raises(SystemExit) as exit:
        main(["respond", "config.toml", "-n", n, "-o", "r"], Fake({}))
    assert exit.value.code == 2


FIXTURES = Path(__file__).parent / "fixtures"


def test_respond_refuses_an_instrument_with_a_roster(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = files(tmp_path)
    config.write_text(
        CONFIG.replace("instrument.json", str(FIXTURES / "households.json"))
    )
    assert respond(config, 1, tmp_path / "r", Fake({}), Model(), info=info) == 1
    assert "rosters (members, vehicles)" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()


@pytest.mark.skipif(
    not shutil.which("npx") and not os.environ.get("QRETOOLS_HARNESS_QRETOOLS"),
    reason="needs npx (or QRETOOLS_HARNESS_QRETOOLS and node)",
)
def test_respond_with_real_qretools(tmp_path: Path) -> None:
    """The flat fixture (qretools' households questions with no roster, exported with
    `instrument export`), with the pinned qretools and a model that always answers 2:
    qretools takes every value, the drawn input's too, into a dataset."""

    def two(messages: Sequence[Mapping[str, str]], seed: int) -> Reply:
        return Reply("2", "stop", "m", None, {}, {})

    config = tmp_path / "config.toml"
    config.write_text(
        f'instrument = "{FIXTURES / "flat.json"}"\n'
        '[model]\nendpoint = "http://127.0.0.1:1/v1"\nname = "m"\ntimeout = 5\n'
        '[generation]\nseed = 1\n[run]\nsystem = "Answer."\nno_answer = "-9"\n'
        'draw = ["county"]\n'
    )
    out = tmp_path / "run1"
    assert respond(config, 2, out, run_process, two) == 0
    assert json.loads((out / "dataset.json").read_text())
    answers = (out / "answers.csv").read_text()
    assert answers.count("var-county:1,,") == 2
    assert answers.count("var-consent:1,,2\n") == 2  # 2 declines: the interview ends


def test_a_refused_dataset_says_how_to_make_it_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake({NEXT: next_of, RESPONSES: Completed(1)})
    out = tmp_path / "a run"
    assert respond(files(tmp_path), 1, out, fake, Model(), info=info) == 1
    assert (out / "answers.csv").exists()
    assert f"cd '{out.resolve()}' && npx -y {QRETOOLS} responses answers.csv" in (
        capsys.readouterr().err
    )
