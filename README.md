# qretools-harness

qretools-harness asks a language model the questions of a
[qretools](https://github.com/JHUCities/qretools) instrument. The model answers as a
respondent. The answers are a synthetic dataset, keyed by the DDI variables of the
instrument.

This version is the first part. It has one command, `build`. The other parts come later.
The section "The design" tells what they do.

## The design

### The goal

One instrument, three kinds of respondent:

1. **People.** For example, the real respondents of a published survey.
2. **A survey runtime.** For example, Qualtrics, with its test responses.
3. **A language model.** The harness asks the model the questions, as an interview.

Each set of answers is a **dataset**. All the datasets use the same DDI variables, so a
researcher can compare them, variable by variable. Each dataset has its **provenance**: a DDI
document that tells where the dataset came from.

### The words

One word names one thing.

| Word | What it means |
|---|---|
| instrument | The survey: its questions and their order. qretools writes it as DDI. |
| run | One time that respondents answer the instrument. |
| dataset | The answers of one run. The file has one line for each answer: the respondent, the variable, and the value. So a respondent has one line for each question that they answered. |
| config | The settings of a run with a model: the model, its settings, and the extra text for each question. |
| trace | One call to the model: the prompt that the harness sent, and the reply. |
| provenance | Where a dataset came from, written as DDI. |
| weight | A number for each respondent: how many people in the population that respondent stands for. |

### The two programs

- **qretools** knows the survey. It writes all the DDI. It reads and filters the datasets.
  It knows nothing about language models.
- **The harness** has one task: it makes synthetic answers. It calls the model, and it holds
  the config. It calls qretools for all other work.

qretools decides everything about the survey. The harness never reads the questions itself,
and never decides which question comes next.

Real answers do not go through the harness. To make a dataset from real data, a person uses
qretools commands. The README of the workspace gives the procedure.

### What goes where

| Item | qretools | The harness |
|---|---|---|
| The questions, the order, the routing | yes | It reads them from the DDI. |
| Access levels (who can see an answer) | yes | It uses `qretools filter`. |
| The model and its settings | no | yes, in the config |
| The extra text for each question, for the model | no | yes, in the config |
| The prompt that the model gets | no | It makes the prompt from the DDI and the config. It keeps each prompt in the traces. |
| The provenance of a dataset | yes: `qretools provenance` writes it | It gives the run folder to qretools. |

The DDI of the instrument never changes after a run. A run adds new DDI items that refer to
the instrument.

### The run folder

Each dataset has one folder:

```
runs/<id>/
  answers.csv       the dataset
  ddi.json          a copy of the instrument's DDI
  <map>.json        for real data: the map from the source's columns to the DDI variables
  source.csv        for real data: the file that qretools read
  config.yaml       for a model run: the config
  traces.jsonl      for a model run: the traces
  run.json          only the facts that no other file holds
  provenance.json   written by qretools
```

**Caution: do not commit or publish a folder that holds real answers.** A Qualtrics export
can hold IP addresses. Only `provenance.json` is safe to publish. Git ignores `runs/`.

### How qretools writes the provenance

The rule is: **derive, do not declare.** qretools reads each fact from a file if it can. The
harness writes a fact in `run.json` only if no file holds it.

qretools reads these facts from the files:

- the instrument, its version and its digest, from `ddi.json`;
- the kind of dataset, from a field in the map, or from `run.json` for a model run;
- for Qualtrics: how the questions were asked, who answered, and the dates, from the export;
- the SHA-256 digest of each file;
- the variables in the dataset, and the variables that are not in it.

The harness writes only these facts in `run.json`:

- that the respondent is a model;
- the start and end times, if no file holds them;
- for a data file: how the publisher asked the questions, and who answered;
- the name and version of the runtime, and what the runtime reported;
- the access level.

qretools checks the facts. It does not trust them:

- For real data, qretools reads the source again. The result must be the same as
  `answers.csv`, byte for byte.
- It checks that the access level removes nothing more from the dataset.
- It checks the DDI that it writes against the official DDI schema.

### Weights

A survey of people often needs a weight. Without it, the dataset does not describe the
population. A model run has no weight: each answer counts once.

- The tools never choose a weight. The researcher chooses it.
- qretools records each weight that the publisher gives, with the publisher's advice.

### Rules that protect the results

1. **A dataset holds one kind of respondent.** If a source holds people and test responses,
   the person makes one run folder for each kind. `qretools provenance` refuses a dataset
   that holds two kinds.
2. **A synthetic dataset always says that it is synthetic.** It can have the same columns as
   real data. Its provenance never hides what made it.
3. **Each dataset goes through the access filter** before analysis. The filter refuses to
   write a result if a restricted answer stays in it.
4. **Record each run.** If you change the config and run again, each run has its own folder,
   with its own config and its own provenance.

### The parts and their status

| Part | Status |
|---|---|
| `qretools-harness build`: the DDI of a workspace | done |
| `qretools filter --access` | done, in qretools |
| `qretools provenance`: the provenance of a run folder | in work, in qretools |
| `qretools next`: the next question for a respondent, so that the interview follows the routing | in work, in qretools |
| The config, and the prompts | later |
| `qretools-harness respond`: a model answers the instrument, as an interview | later |
| Weights in the provenance | later |

Not in this plan: `qretools compare`, and a sweep (many runs that a program makes and scores).

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
