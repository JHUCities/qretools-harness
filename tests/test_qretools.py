from pathlib import Path

import pytest
from fake import Fake, installed, pinned, working

from qretools_harness.qretools import (
    Built,
    Completed,
    Qretools,
    Refused,
    binary_of,
    build,
    next_step,
    pin_of,
    provenance,
    resolve,
)

WS = Path("/ws")


def test_no_pin_is_refused() -> None:
    assert pin_of("[]", WS) == Refused(
        f"{WS} pins no qretools. Add npm:qretools to its mise.toml."
    )


def test_a_pin_not_installed_says_how_to_install() -> None:
    refused = pin_of(pinned(Path("/i"), installed=False).stdout, WS)
    assert isinstance(refused, Refused)
    assert "mise install" in refused.reason


def test_unreadable_mise_output_is_refused() -> None:
    for text in ["", "{", "[{}]", "[1]"]:
        assert isinstance(pin_of(text, WS), Refused), text


def test_the_binary_is_the_file_inside_the_pinned_install(tmp_path: Path) -> None:
    install = tmp_path / "npm-qretools"
    (install / "bin").mkdir(parents=True)  # listed by mise, but holds no qretools
    (install / "node_modules/.bin").mkdir(parents=True)
    (install / "node_modules/.bin/qretools").touch()
    global_bin = tmp_path / "node/bin"  # a global qretools, first on PATH
    global_bin.mkdir(parents=True)
    (global_bin / "qretools").touch()
    paths = f"{global_bin}\n{install}/bin\n{install}/node_modules/.bin\n"
    assert binary_of(paths, install) == install / "node_modules/.bin/qretools"


def test_no_file_inside_the_install_is_refused(tmp_path: Path) -> None:
    install = tmp_path / "npm-qretools"
    (install / "bin").mkdir(parents=True)
    other = tmp_path / "npm-qretools-other/bin"  # a sibling whose name starts the same
    other.mkdir(parents=True)
    (other / "qretools").touch()
    assert isinstance(binary_of(f"{install}/bin\n{other}\n", install), Refused)


def test_resolve_asks_mise_in_the_workspace(tmp_path: Path) -> None:
    fake = working(tmp_path)
    q = resolve(WS, fake)
    binary = installed(tmp_path) / "node_modules/.bin/qretools"
    assert q == Qretools(WS, binary, "2.0.0-alpha.10")
    assert all(cwd == WS and capture for _, cwd, capture in fake.calls)


def test_resolve_passes_on_what_mise_says_when_it_fails() -> None:
    fake = Fake(
        {"mise ls": Completed(1, "", "mise ERROR Config files are not trusted.")}
    )
    refused = resolve(WS, fake)
    assert isinstance(refused, Refused)
    assert "not trusted" in refused.reason


def test_resolve_without_mise_is_refused() -> None:
    assert resolve(WS, Fake({"mise": Refused("Can't run mise.")})) == Refused(
        "Can't run mise."
    )


def test_build_runs_the_pinned_binary_through_mise_exec(tmp_path: Path) -> None:
    fake = working(tmp_path)
    q = Qretools(WS, Path("/bin/qretools"), "x")
    assert build(q, Path("/out"), fake) == Built(Path("/out/ddi.json"))
    [(argv, cwd, capture)] = fake.calls
    assert argv == ["mise", "exec", "--", "/bin/qretools", "build", ".", "-o", "/out"]
    assert cwd == WS
    assert not capture


def test_a_refused_build_is_refused(tmp_path: Path) -> None:
    q = Qretools(WS, Path("/bin/qretools"), "x")
    assert isinstance(build(q, Path("/out"), working(tmp_path, 1)), Refused)


def test_a_development_build_is_run_with_node_and_named_by_its_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_js = tmp_path / "qretools.js"
    build_js.write_text("x")
    monkeypatch.setenv("QRETOOLS_HARNESS_QRETOOLS", str(build_js))
    q = resolve(WS, Fake({}))  # mise is never asked
    assert isinstance(q, Qretools)
    assert q.version == (
        "development build"
        " sha256:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
    )
    assert q.argv("next") == ["node", str(build_js), "next"]


def test_a_development_build_that_cant_be_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QRETOOLS_HARNESS_QRETOOLS", str(tmp_path / "none.js"))
    assert isinstance(resolve(WS, Fake({})), Refused)


Q = Qretools(WS, Path("/bin/qretools"), "x")


def test_next_sends_the_state_on_stdin() -> None:
    fake = Fake({"mise exec": Completed(0, '{"kind": "end"}')})
    assert next_step(Q, Path("/i.json"), {"answers": []}, fake) == {"kind": "end"}
    assert fake.calls[0][0][-3:] == ["next", "/i.json", "-"]
    assert fake.stdins == ['{"answers": []}']


@pytest.mark.parametrize(
    "done",
    [Completed(1, "", "unknown variable"), Completed(0, "[]"), Completed(0, "{")],
)
def test_next_that_fails_or_isnt_an_object_is_refused(done: Completed) -> None:
    assert isinstance(next_step(Q, Path("/i.json"), {}, Fake({"mise": done})), Refused)


def test_provenance_runs_on_the_folder() -> None:
    fake = Fake({"mise exec": Completed(0)})
    assert provenance(Q, Path("/r"), fake) == Path("/r/provenance.json")
    assert isinstance(provenance(Q, Path("/r"), Fake({"mise": Completed(1)})), Refused)
