"""Tests against real tools, each run only when asked.

The build runs when mise is installed and QRETOOLS_WORKSPACE names a workspace with its
full git history (qretools build refuses a shallow clone). The chat runs when
QRETOOLS_HARNESS_MODEL_URL gives a model server's base URL. `respond` runs against a
real qretools when QRETOOLS_HARNESS_QRETOOLS names a build that has `next`."""

import json
import os
import shutil
from pathlib import Path

import pytest
from fake import Server

from qretools_harness.chat import Reply, complete
from qretools_harness.cli import main
from qretools_harness.config import Model

WORKSPACE = os.environ.get("QRETOOLS_WORKSPACE")


@pytest.mark.skipif(
    not (WORKSPACE and shutil.which("mise")), reason="needs mise and QRETOOLS_WORKSPACE"
)
def test_builds_a_real_workspace(tmp_path: Path) -> None:
    assert WORKSPACE
    assert main(["build", WORKSPACE, "-o", str(tmp_path)]) == 0
    assert (tmp_path / "ddi.json").stat().st_size > 0


MODEL_URL = os.environ.get("QRETOOLS_HARNESS_MODEL_URL")
MODEL_NAME = os.environ.get("QRETOOLS_HARNESS_MODEL", "")


@pytest.mark.skipif(
    not MODEL_URL,
    reason="needs QRETOOLS_HARNESS_MODEL_URL (and QRETOOLS_HARNESS_MODEL)",
)
def test_a_live_server_replies() -> None:
    assert MODEL_URL
    model = Model(MODEL_URL.rstrip("/"), MODEL_NAME, 300)
    reply = complete(
        model, {"max_tokens": 8, "seed": 1}, [{"role": "user", "content": "Say yes."}]
    )
    assert isinstance(reply, Reply), reply
    assert reply.text


QRETOOLS_BUILD = os.environ.get("QRETOOLS_HARNESS_QRETOOLS")
HOUSEHOLDS = Path(__file__).parent / "fixtures/households.json"


@pytest.mark.skipif(
    not (QRETOOLS_BUILD and shutil.which("node")),
    reason="needs node and QRETOOLS_HARNESS_QRETOOLS (a qretools build with next)",
)
def test_respond_with_real_qretools(tmp_path: Path, server: Server) -> None:
    """The households fixture (qretools' own, exported with `instrument export`), with
    a model that always answers 1: the route reaches the end, and the provenance is
    written."""
    server.body = json.dumps({"choices": [{"message": {"content": "1"}}]}).encode()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[model]\nendpoint = "{endpoint}"\nname = "m"\ntimeout = 5\n'
        '[generation]\nseed = 1\n[run]\nmode = "interview"\nrespondents = 2\n'
        'system = "Answer."\nno_answer = "-9"\ndraw = ["county"]\n'
    )
    out = tmp_path / "run1"
    assert main(["respond", str(config), str(HOUSEHOLDS), "-o", str(out)]) == 0
    assert json.loads((out / "provenance.json").read_text())
    assert (out / "answers.csv").read_text().count("\n2,") > 0
