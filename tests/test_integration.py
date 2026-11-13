"""Tests against real tools, each run only when asked.

The build runs when mise is installed and QRETOOLS_WORKSPACE names a workspace with its
full git history (qretools build refuses a shallow clone). The chat runs when
QRETOOLS_HARNESS_MODEL_URL gives a model server's base URL."""

import os
import shutil
from pathlib import Path

import pytest

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
