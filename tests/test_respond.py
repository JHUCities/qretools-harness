"""`respond` end to end, with stand-ins for qretools and for the model."""

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fake import Fake

from qretools_harness.chat import Reply
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
    """Replies "2"; the served model and build are given per call, in turn."""

    def __init__(self, *served: tuple[str | None, str | None]) -> None:
        self.served = list(served)
        self.seeds: list[int] = []

    def __call__(self, messages: Sequence[Mapping[str, str]], seed: int) -> Reply:
        self.seeds.append(seed)
        model, build = self.served.pop(0) if self.served else ("served", "b1")
        return Reply("2", "stop", model, build, {}, {})


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
    assert respond(config, 2, out, fake, model, lambda: next(times)) == 0
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
    traces = [json.loads(t) for t in (out / "traces.jsonl").read_text().splitlines()]
    assert traces[0]["kind"] == "start"
    assert traces[0]["qretools"] == QRETOOLS.partition("@")[2]
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
        "served",
        "--runtime-version",
        "b1",
        "--file",
        "traces.jsonl",
        "--file",
        "config.toml",
        "-o",
        "dataset.json",
    ]


def test_the_runtime_is_the_asked_model_when_the_server_doesnt_say_one(
    tmp_path: Path,
) -> None:
    fake = qretools()
    model = Model(("a", "b1"), ("b", None))
    assert respond(files(tmp_path), 2, tmp_path / "r", fake, model) == 0
    argv, _, _ = fake.calls[-1]
    assert argv[argv.index("--runtime") + 1] == "asked-model"
    assert "--runtime-version" not in argv


def test_a_failure_midway_leaves_the_traces_and_no_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = 0

    def flaky(messages: Sequence[Mapping[str, str]], seed: int) -> Reply | Refused:
        nonlocal calls
        calls += 1
        return Model()(messages, seed) if calls == 1 else Refused("Server down.")

    fake, out = qretools(), tmp_path / "r"
    assert respond(files(tmp_path), 2, out, fake, flaky) == 1
    assert sorted(p.name for p in out.iterdir()) == ["config.toml", "traces.jsonl"]
    assert not any("responses" in argv for argv, _, _ in fake.calls)
    assert "respondent 2" in capsys.readouterr().err


def test_respond_refuses_a_folder_that_isnt_empty(tmp_path: Path) -> None:
    out = tmp_path / "run1"
    out.mkdir()
    (out / "answers.csv").touch()
    assert respond(files(tmp_path), 1, out, Fake({}), Model()) == 1


def test_respond_needs_a_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = files(tmp_path)
    config.write_text(CONFIG.replace("seed = 10", ""))
    assert respond(config, 1, tmp_path / "r", Fake({}), Model()) == 1
    assert "generation.seed" in capsys.readouterr().err


@pytest.mark.parametrize("n", ["0", "-1", "x"])
def test_the_number_of_respondents_is_one_or_more(n: str) -> None:
    with pytest.raises(SystemExit) as exit:
        main(["respond", "config.toml", "-n", n, "-o", "r"], Fake({}))
    assert exit.value.code == 2


HOUSEHOLDS = Path(__file__).parent / "fixtures/households.json"


@pytest.mark.skipif(
    not shutil.which("npx") and not os.environ.get("QRETOOLS_HARNESS_QRETOOLS"),
    reason="needs npx (or QRETOOLS_HARNESS_QRETOOLS and node)",
)
def test_respond_with_real_qretools(tmp_path: Path) -> None:
    """The households fixture (qretools' own, exported with `instrument export`), with
    the pinned qretools and a model that always answers 2: it declines the interview,
    so the route reaches the end before the roster, which a dataset can't hold yet.
    qretools takes every value, the drawn input's too, into a dataset."""

    def two(messages: Sequence[Mapping[str, str]], seed: int) -> Reply:
        return Reply("2", "stop", "m", None, {}, {})

    config = tmp_path / "config.toml"
    config.write_text(
        f'instrument = "{HOUSEHOLDS}"\n'
        '[model]\nendpoint = "http://127.0.0.1:1/v1"\nname = "m"\ntimeout = 5\n'
        '[generation]\nseed = 1\n[run]\nsystem = "Answer."\nno_answer = "-9"\n'
        'draw = ["county"]\n'
    )
    out = tmp_path / "run1"
    assert respond(config, 2, out, run_process, two) == 0
    assert json.loads((out / "dataset.json").read_text())
    answers = (out / "answers.csv").read_text()
    assert answers.count("var-county:1,,") == 2
    assert answers.count("var-consent:1,,2\n") == 2


def test_a_refused_dataset_says_how_to_make_it_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake({NEXT: next_of, RESPONSES: Completed(1)})
    out = tmp_path / "a run"
    assert respond(files(tmp_path), 1, out, fake, Model()) == 1
    assert (out / "answers.csv").exists()
    assert f"cd '{out.resolve()}' && npx -y {QRETOOLS} responses answers.csv" in (
        capsys.readouterr().err
    )
