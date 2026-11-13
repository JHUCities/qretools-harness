from pathlib import Path

import pytest

from qretools_harness.qretools import OVERRIDE, QRETOOLS, Qretools, Refused, harness

WS = Path("/ws")


def test_the_harness_runs_the_one_pinned_version_through_npx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OVERRIDE, raising=False)
    q = harness(WS)
    assert isinstance(q, Qretools)
    assert q.argv("next") == ["npx", "-y", QRETOOLS, "next"]
    assert f"qretools@{q.version}" == QRETOOLS
    # The README names the version too.
    readme = Path(__file__).parent.parent / "README.md"
    assert f"`{QRETOOLS}`" in readme.read_text()


def test_a_development_build_is_run_with_node_and_named_by_its_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_file = tmp_path / "qretools.js"
    build_file.write_text("x")
    monkeypatch.setenv(OVERRIDE, str(build_file))
    q = harness(WS)
    assert isinstance(q, Qretools)
    assert q.argv("next") == ["node", str(build_file), "next"]
    assert q.version.startswith("development build sha256:2d711642")


def test_a_development_build_that_cant_be_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OVERRIDE, str(tmp_path / "none.js"))
    refused = harness(WS)
    assert isinstance(refused, Refused)
    assert OVERRIDE in refused.reason
