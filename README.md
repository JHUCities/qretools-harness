# qretools-harness

qretools-harness asks a language model the questions of a
[qretools](https://github.com/JHUCities/qretools) instrument. The model answers as a
respondent. The answers are a synthetic dataset, keyed by the DDI variables of the
instrument.

This version has three commands: `build`, `check-config` and `respond`. The other parts come
later.
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
  config.toml       for a model run: the config
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
| `qretools provenance`: the provenance of a run folder | done, in qretools; not released yet |
| `qretools next`: the next question for a respondent, so that the interview follows the routing | done, in qretools; not released yet |
| The config, its check against the DDI, and the client for the model server | done |
| The prompts: the text that the model gets for each question | done, in `respond` |
| `qretools-harness respond`: a model answers the instrument, as an interview | done; it needs a qretools release with `next` and `provenance` |
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

## Write a config

A config holds the settings of a run with a model. It is a TOML file.
[`examples/config.toml`](examples/config.toml) is an example.

| Table | Key | What it holds |
|---|---|---|
| `model` | `endpoint` | The base URL of an OpenAI-compatible server, for example `http://127.0.0.1:9931/v1` for llama.cpp. |
| `model` | `name` | The name of the model that the harness asks for. |
| `model` | `timeout` | The maximum time for one reply, in seconds. |
| `generation` | any key | The settings that the harness sends to the server, for example `temperature`, `max_tokens` and `seed`. The harness sends them without change. It refuses `model`, `messages`, `stream` and `n`, because it sets them itself. |
| `run` | `mode` | `"interview"`. This is the only mode now. |
| `run` | `respondents` | The number of respondents. |
| `run` | `system` | The system prompt. |
| `run` | `missing` | The missing codes that the model can give, for example `["D", "R"]`. The harness offers a code only for a question that has it. If you do not give this key, the harness offers no missing code, and the model must choose an answer. |
| `run` | `no_answer` | The missing code that the harness records if the model gives no allowed answer. Each question must have this code. |
| `run` | `draw` | The names of inputs that the harness chooses at random from their choices, with the seed of the respondent. |
| `inputs` | an input's name | The value of an input of the instrument, for each respondent. |
| `prompts` | a question's URN | Extra text for the model about one question. The key is the URN of the question, with its version. |

The config holds no fact that the DDI holds. The instrument, its questions and their
versions come from the DDI. The version in each URN of `prompts` is there to find a
changed question.

The config holds no API key. Do not write a key in it, because the run folder keeps a
copy of the config.

Unknown keys are refused, except in `generation`. Thus the harness does not find an
incorrect name in `generation`, for example `temprature`.

## Check a config

1. Build the DDI of the instrument (see "Build the DDI of a workspace").
2. Check the config against the DDI:

   ```sh
   qretools-harness check-config config.toml dist/ddi.json
   ```

The command refuses the config if a key or a value is not correct. It refuses a DDI file
that holds no question. It also refuses the config if a URN in `prompts` is not a question in the DDI, or if the version of the
question in the DDI is different. Then the question changed after you wrote its prompt.
Read the question again, change the prompt if necessary, and write the new version in
the URN.

The command does not connect to the model server. The exit codes are the same as for
`build`.

## Run a model through an instrument

1. Build the DDI of the workspace (see "Build the DDI of a workspace"). The DDI of each
   instrument is `dist/instruments/<name>.json`.
2. Write a config (see "Write a config"). Give `generation.seed` and `run.no_answer`.
3. Make sure that the model server runs.
4. Go to the workspace. The harness uses the qretools that `mise.toml` pins in the current
   directory.
5. Run the interviews:

   ```sh
   qretools-harness respond config.toml dist/instruments/gss_2010.json -o runs/try-1
   ```

The run folder must not exist, or must be empty. Its name must contain only letters,
digits, `-` and `_`, because qretools makes the IDs of the provenance from it.

The command writes these files:

| File | What it holds |
|---|---|
| `answers.csv` | The answers, one line for each value: `respondent,variable,row,value`. The respondents are `1`, `2`, and so on. |
| `traces.jsonl` | One line for each event. The first line gives the versions of qretools and of the harness. Each call to the model gives the messages as sent, the reply, the model that the server served, the token counts, the server's timings, and the value or the reason that the harness did not accept the reply. Each input gives its value and where the value came from. |
| `config.toml` | A copy of the config. |
| `ddi.json` | A copy of the instrument's DDI. |
| `run.json` | The facts that no other file holds: the respondent is synthetic, the model that the server served and its build, and the start and end times (UTC). |
| `provenance.json` | Written by `qretools provenance`. |

These are the rules of an interview:

- **The route.** The harness calls `qretools next` for each step. qretools decides the
  next question and its text. The harness does not evaluate a condition.
- **The prompt.** The prompt for a question has the statements since the last question,
  the text of the question, its instructions, the text from `prompts` for that question,
  the options with their codes, and how to answer. Each question and each answer stay in
  the conversation.
- **The seed.** Respondent *i* gets `generation.seed + i - 1`. With one seed for all,
  llama.cpp gives the same answers to each respondent. Thus, two runs whose seeds are
  near each other can have the same respondents: run 1 with seed 1 has the respondent 2
  that run 2 with seed 2 has as respondent 1.
- **The reply.** The harness accepts a code, the full label of an option (in any case),
  or a code followed by a space or punctuation (`3. Retired`). For a number, the reply
  must start with a number in the range, with no more decimals than the question allows.
  For select-all, the reply gives the codes of the ticked options, or `none`. Each option
  then gets its ticked or unticked code. A reply that the server cut off (`max_tokens`)
  is not accepted.
- **Retries.** If the harness does not accept a reply, or qretools does not accept the
  answer (`problem`), the harness asks the question again, with the reason. It asks a
  question at most 3 times. Then it records the `no_answer` code, and the traces say so.
  If qretools did not accept the last answer, the trace also gives its reason. If
  qretools does not accept the `no_answer` code, the run stops.
- **Inputs.** If the route needs an input, the harness gives the value from `inputs`, or
  draws a value from `draw`. If the config gives neither, the harness sends "not known"
  (`null`). It says so on stderr and in the traces.
- **Errors.** If the model server or qretools fails, the run stops. The run folder then
  holds the traces until the failure, and no `answers.csv`.

Limits:

- The conversation grows with each question. If the conversation is larger than the
  context of the model, the server gives an error, and the run stops. Give the server a
  context that is larger than the largest prompt plus `max_tokens`. The command prints the
  size of the largest prompt. With the GSS 2010 instrument, it was about 3,800 tokens, so
  a context of 4,096 tokens is too small. Use 8,192 tokens (for llama.cpp, `-c 8192`).
- The harness asks the options in their written order. It ignores `responseOrder`.
- An unticked select-all option gets a line in `answers.csv` with its unticked code.
  `qretools responses` writes no line for a blank cell of a Qualtrics export.

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

One test sends a message to a model server. It runs only if
`QRETOOLS_HARNESS_MODEL_URL` gives the base URL of the server.
`QRETOOLS_HARNESS_MODEL` gives the name of the model:

```sh
QRETOOLS_HARNESS_MODEL_URL=http://127.0.0.1:9931/v1 \
QRETOOLS_HARNESS_MODEL=ggml-org/LFM3-Omni-2B-GGUF:Q8_0 uv run pytest
```

To use a qretools build that is not released, set `QRETOOLS_HARNESS_QRETOOLS` to the
path of its JavaScript file, for example `packages/cli/dist/qretools.js` in a clone of
qretools. The harness then runs that file with the `node` on `PATH`, and does not ask
mise. The traces give the SHA-256 digest of the file in place of a version. This is for
development only.

One test runs `respond` with that build, against `tests/fixtures/households.json` (the
households instrument of qretools' tests, from `qretools instrument export`):

```sh
QRETOOLS_HARNESS_QRETOOLS=../qretools/packages/cli/dist/qretools.js uv run pytest
```

## Licence

MIT. See [LICENSE](LICENSE).
