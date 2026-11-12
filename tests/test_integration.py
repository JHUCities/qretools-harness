"""Builds a real workspace. Runs only when mise is installed and QRETOOLS_WORKSPACE names
a workspace with its full git history (qretools build refuses a shallow clone)."""

import os
import shutil
from pathlib import Path

import pytest

from qretools_harness.cli import main

WORKSPACE = os.environ.get("QRETOOLS_WORKSPACE")


@pytest.mark.skipif(
    not (WORKSPACE and shutil.which("mise")), reason="needs mise and QRETOOLS_WORKSPACE"
)
def test_builds_a_real_workspace(tmp_path: Path) -> None:
    assert WORKSPACE
    assert main(["build", WORKSPACE, "-o", str(tmp_path)]) == 0
    assert (tmp_path / "ddi.json").stat().st_size > 0
