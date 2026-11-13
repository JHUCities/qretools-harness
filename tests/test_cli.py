import json
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


CONFIG = (Path(__file__).parent.parent / "examples/config.toml").read_text()


def ddi_at(tmp_path: Path, version: str) -> Path:
    item = {"URN": "", "Agency": "us.jhu", "ID": "agekdbrn", "Version": version}
    path = tmp_path / "ddi.json"
    path.write_text(json.dumps({"QuestionItem": {"k": item}}))
    return path


def config_at(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_check_config_passes_a_matching_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["check-config", str(config_at(tmp_path)), str(ddi_at(tmp_path, "6"))]
    assert main(argv, Fake({})) == 0
    assert "1 prompt(s) checked" in capsys.readouterr().out


def test_check_config_refuses_a_stale_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["check-config", str(config_at(tmp_path)), str(ddi_at(tmp_path, "7"))]
    assert main(argv, Fake({})) == 1
    assert "agekdbrn changed" in capsys.readouterr().err


@pytest.mark.parametrize("problem", ["no config", "bad config", "no ddi", "bad ddi"])
def test_check_config_refuses_what_it_cant_read(tmp_path: Path, problem: str) -> None:
    config = config_at(tmp_path, "[" if problem == "bad config" else CONFIG)
    ddi = ddi_at(tmp_path, "6")
    if problem == "no config":
        config.unlink()
    if problem == "no ddi":
        ddi.unlink()
    if problem == "bad ddi":
        ddi.write_text("{")
    assert main(["check-config", str(config), str(ddi)], Fake({})) == 1


def test_check_config_needs_both_files() -> None:
    with pytest.raises(SystemExit) as exit:
        main(["check-config", "config.toml"], Fake({}))
    assert exit.value.code == 2
