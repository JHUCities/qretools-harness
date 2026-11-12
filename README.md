# qretools-harness

qretools-harness runs [qretools](https://github.com/JHUCities/qretools) instruments with
respondents that are not people. It also reads real answer sets. It keys all answers by
DDI variable.

This version is the first part. It has one command, `build`. The commands that read and
make answer sets come later.

qretools decides everything about the survey. The harness only calls qretools and uses
the result.

## Install

You need these tools:

- [uv](https://docs.astral.sh/uv/).
- [mise](https://mise.jdx.dev/), version 2026.9 or later.
- A qretools workspace whose `mise.toml` pins `npm:qretools`.

The harness is not on PyPI. Install it from git:

```sh
uv tool install git+https://github.com/JHUCities/qretools-harness
```

## Build the DDI of a workspace

1. Go to the workspace.
2. Install the tools that the workspace pins:

   ```sh
   mise install
   ```

3. Build the DDI:

   ```sh
   qretools-harness build . -o dist
   ```

The command writes `dist/ddi.json`. If you do not give `-o`, the command writes into
`dist` in the workspace.

The command uses the qretools version that the workspace's `mise.toml` pins. It does not
use a `qretools` command on your `PATH`. If mise cannot give the pinned version, the
command stops and tells you why.

The workspace must be a full git clone. qretools refuses a shallow clone, because it
counts the versions of the items from the history.

The exit codes are:

| Code | Meaning |
|---|---|
| 0 | The command wrote the DDI. |
| 1 | qretools or mise refused, or a step failed. |
| 2 | The command line is not correct. |

## Development

1. Install the dependencies:

   ```sh
   uv sync
   ```

2. Do the checks. CI does the same checks on each pull request:

   ```sh
   uv run ruff check
   uv run ruff format --check
   uv run mypy --strict
   uv run pytest
   ```

The tests do not run mise or qretools. One test builds a real workspace. It runs only if
mise is installed and `QRETOOLS_WORKSPACE` gives the path of a workspace:

```sh
QRETOOLS_WORKSPACE=../qretools-gss uv run pytest
```

## Licence

MIT. See [LICENSE](LICENSE).
