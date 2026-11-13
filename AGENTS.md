# qretools-harness: instructions for agents

Read this file before you change anything.

## The rule

qretools owns the survey. This package only orchestrates it.

- The harness never reads the surface YAML of a workspace. It reads what qretools writes:
  the DDI, and the output of qretools commands.
- The harness never evaluates a condition, and never decides which question comes next or
  what a fill says. If it needs one of those answers, it asks qretools. If qretools has no
  command for it, add the command to qretools.
- qretools holds nothing that is about language models. Everything about a model (the run
  plan, prompts, the text a model gets for a question, the record of a run) lives here.
- Real survey data never goes in git. `runs/` is ignored for that reason. A simulated answer
  set may go in git. The record of a run may go in git, because it holds no answers.

## Layout

```
src/qretools_harness/
  cli.py        the commands (argparse); exit 0 done, 1 refused or failed, 2 usage
  qretools.py   the only module that runs the qretools CLI
  config.py     the config (TOML), and its check against the instrument's DDI
  chat.py       the only module that opens a network connection: the model server
examples/
  config.toml   an example config; the tests read it
tests/
  fake.py       a stand-in for running processes
  test_*.py     unit tests; test_integration.py builds a real workspace when asked
```

## How the harness runs qretools

`qretools.py` is the only module that starts a process. Do not call `subprocess` anywhere
else.

All commands except `build` run one qretools version, `QRETOOLS` in `qretools.py`, with
`npx -y`. Change the version only there. `npx` with an exact version runs that version
from npm, never a `qretools` on `PATH`. `QRETOOLS_HARNESS_QRETOOLS`, for development
only, names a qretools build (its JS file); the harness then runs it with `node`, and
records its SHA-256 digest as its version.

`build` runs the qretools that the workspace pins:

1. `mise ls --current --json npm:qretools`, in the workspace, gives the pinned version and
   its install path. No pin, or a pin that is not installed, is a refusal.
2. `mise bin-paths npm:qretools` gives the directories of that tool. The harness uses the
   `qretools` file in the directory inside the install path.
3. The harness runs that file by its absolute path with `mise exec --`, in the workspace,
   so that node is the version the workspace pins.

A `qretools` on `PATH` is never used. A global install can shadow the pinned one.

This is different from the workspace CI, which runs `mise exec -- which qretools` and stops
if the result is not inside `mise where npm:qretools`. The harness does not need that
check, because it never looks for qretools on `PATH`. A global install therefore cannot
stop the harness. Do not change the harness to match the CI.

## The config

The config is TOML, because the standard library reads TOML (`tomllib`) and the harness
has no runtime dependencies. The config holds only facts about the model. A fact that the
DDI holds is not a config field. A path in the config starts from the folder of the
config.

The interview loop must not send the same seed for each respondent. With the same seed
and the same messages, llama.cpp gives the same reply, so all respondents would be the
same. Derive one seed for each respondent from the config's seed.

## Style

- Functions take values and return values. Effects stay at the edge, and are passed in
  (the `run` parameter), so a test gives a fake.
- Errors are values. A function that can fail returns `Refused` with a sentence for a
  person. It does not raise.
- Small, total, named functions. No runtime dependencies: use the standard library.
- Python 3.13, managed with uv. `mypy --strict` and `ruff` must pass.

## Checks

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run mypy --strict
uv run pytest
```

CI (`.github/workflows/check.yml`) runs the same checks with `uv sync --locked`.
