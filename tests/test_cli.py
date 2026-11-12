from pathlib import Path

import pytest
from fake import Fake, working

from qretools_harness.cli import main


def test_build_reports_where_the_ddi_went(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", str(tmp_path)], working(tmp_path)) == 0
    assert str(tmp_path.resolve() / "dist" / "ddi.json") in capsys.readouterr().out


def test_outdir_is_relative_to_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ws").mkdir()
    fake = working(tmp_path)
    assert main(["build", "ws", "-o", "out"], fake) == 0
    argv, cwd, _ = fake.calls[-1]
    assert cwd == tmp_path.resolve() / "ws"
    assert argv[-1] == str(tmp_path.resolve() / "out")


def test_refused_build_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", str(tmp_path)], working(tmp_path, 1)) == 1
    assert "refused" in capsys.readouterr().err


def test_missing_workspace_exits_1(tmp_path: Path) -> None:
    assert main(["build", str(tmp_path / "nowhere")], Fake({})) == 1


@pytest.mark.parametrize("argv", [[], ["nothing"], ["build"]])
def test_usage_exits_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit:
        main(argv, Fake({}))
    assert exit.value.code == 2
