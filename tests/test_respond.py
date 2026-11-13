"""`respond` end to end, with a stand-in for qretools and a local model server."""

import json
from pathlib import Path
from typing import Any

import pytest
from fake import Fake, Server, working

from qretools_harness.cli import main
from qretools_harness.qretools import Completed

CONFIG = """
[model]
endpoint = "{endpoint}"
name = "asked-model"
timeout = 5
[generation]
seed = 10
[run]
mode = "interview"
respondents = 2
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


def next_of(stdin: str) -> Completed:
    """qretools next for a one-question instrument."""
    state: dict[str, Any] = json.loads(stdin)
    return Completed(0, json.dumps(END if state["answers"] else ASK))


def files(tmp_path: Path, s: Server) -> tuple[Path, Path]:
    endpoint = f"http://127.0.0.1:{s.server_address[1]}/v1"
    config = tmp_path / "config.toml"
    config.write_text(CONFIG.format(endpoint=endpoint))
    ddi = tmp_path / "instrument.json"
    ddi.write_text(json.dumps({"QuestionItem": {"k": {"ID": "tenure"}}}))
    return config, ddi


def qretools(tmp_path: Path) -> Fake:
    fake = working(tmp_path)
    exec = fake.answers.pop("mise exec")
    fake.answers[
        "mise exec -- "
        + str(tmp_path / "npm-qretools/node_modules/.bin/qretools")
        + " next"
    ] = next_of
    fake.answers["mise exec"] = exec
    return fake


def test_respond_writes_the_run_folder(
    tmp_path: Path,
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QRETOOLS_HARNESS_QRETOOLS", raising=False)
    server.body = json.dumps(
        {
            "choices": [{"message": {"content": "2"}}],
            "model": "served",
            "system_fingerprint": "b1",
        }
    ).encode()
    config, ddi = files(tmp_path, server)
    out = tmp_path / "runs" / "try-1"
    fake = qretools(tmp_path)
    assert main(["respond", str(config), str(ddi), "-o", str(out)], fake) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "answers.csv",
        "config.toml",
        "ddi.json",
        "run.json",
        "traces.jsonl",
    ]  # provenance.json is the fake's to write, and it writes nothing
    assert (out / "answers.csv").read_text() == (
        "respondent,variable,row,value\n1,urn:v:tenure,,2\n2,urn:v:tenure,,2\n"
    )
    assert (out / "config.toml").read_bytes() == config.read_bytes()
    run = json.loads((out / "run.json").read_text())
    assert run["respondent"] == "synthetic"
    assert run["runtime"] == {"name": "served", "version": "b1"}
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    assert traces[0]["kind"] == "start" and traces[0]["qretools"] == "2.0.0-alpha.10"
    # Each respondent its own seed, from the config's.
    assert [b.get("seed") for _, b in server.received if isinstance(b, dict)] == [
        10,
        11,
    ]
    argv, _, _ = fake.calls[-1]
    assert argv[-2:] == ["provenance", str(out.resolve())]


def test_respond_refuses_a_folder_that_isnt_empty(
    tmp_path: Path, server: Server
) -> None:
    config, ddi = files(tmp_path, server)
    out = tmp_path / "run1"
    out.mkdir()
    (out / "answers.csv").touch()
    assert main(["respond", str(config), str(ddi), "-o", str(out)], Fake({})) == 1


def test_respond_needs_a_seed(
    tmp_path: Path, server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    config, ddi = files(tmp_path, server)
    config.write_text(config.read_text().replace("seed = 10", ""))
    assert (
        main(["respond", str(config), str(ddi), "-o", str(tmp_path / "r")], Fake({}))
        == 1
    )
    assert "generation.seed" in capsys.readouterr().err


def test_respond_refuses_a_folder_name_qretools_cant_use(
    tmp_path: Path, server: Server
) -> None:
    config, ddi = files(tmp_path, server)
    assert (
        main(["respond", str(config), str(ddi), "-o", str(tmp_path / "a.b")], Fake({}))
        == 1
    )
