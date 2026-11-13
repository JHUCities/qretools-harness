# qretools-harness

qretools-harness asks a language model the questions of a
[qretools](https://github.com/JHUCities/qretools) instrument. The model answers as a
respondent. The answers are a synthetic dataset, keyed by the DDI variables of the
instrument.

This version has one command: `check-config`. The other parts come later.
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
| `qretools filter --access` | done, in qretools |
| `qretools provenance`: the provenance of a run folder | in work, in qretools |
| `qretools next`: the next question for a respondent, so that the interview follows the routing | in work, in qretools |
| The config, its check against the DDI, and the client for the model server | done |
| `qretools-harness respond`: a model answers the instrument, as an interview | later |
| Weights in the provenance | later |

Not in this plan: `qretools compare`, and a sweep (many runs that a program makes and scores).

## Install

You need these tools:

- [uv](https://docs.astral.sh/uv/).
- [Node.js](https://nodejs.org/) 22 or later, with `npx`.

The harness is not on PyPI. Install it from git:

```sh
uv tool install git+https://github.com/JHUCities/qretools-harness
```

## Write a config

A config holds the settings of a run with a model. It is a TOML file.
[`examples/config.toml`](examples/config.toml) is an example.

| Table | Key | What it holds |
|---|---|---|
| (top) | `instrument` | The path of the instrument's DDI, as `qretools build` writes it (`dist/instruments/<name>.json`). A relative path starts from the folder of the config, not from the current directory. Write this key before the first table, because TOML puts a key that follows a table in that table. |
| `model` | `endpoint` | The base URL of an OpenAI-compatible server, for example `http://127.0.0.1:9931/v1` for llama.cpp. |
| `model` | `name` | The name of the model that the harness asks for. |
| `model` | `timeout` | The maximum time for one reply, in seconds. |
| `generation` | any key | The settings that the harness sends to the server, for example `temperature`, `max_tokens` and `seed`. The harness sends them without change. It refuses `model`, `messages`, `stream` and `n`, because it sets them itself. |
| `run` | `system` | The system prompt. |
| `run` | `missing` | The missing codes that the model can give, for example `["D", "R"]`. The harness offers a code only for a question that has it. If you do not give this key, the harness offers no missing code, and the model must choose an answer. |
| `run` | `no_answer` | The missing code that the harness records if the model gives no allowed answer. Each question must have this code. |
| `run` | `draw` | The names of inputs that the harness chooses at random from their choices, with the seed of the respondent. |
| `inputs` | an input's name | The value of an input of the instrument, for each respondent. |
| `prompts` | a question's URN | Extra text for the model about one question. The key is the URN of the question, with its version. |

The config holds no fact that the DDI holds. The questions and their versions come from
the DDI. The version in each URN of `prompts` is there to find a changed question.

A tag reference (`owner/repo@tag:name`) is not supported yet for `instrument`, because
`qretools next` reads only a DDI file. The harness refuses it. Build the DDI with
qretools, and give its path.

The config holds no API key. Do not write a key in it, because a run keeps a copy of the
config.

Unknown keys are refused, except in `generation`. Thus the harness does not find an
incorrect name in `generation`, for example `temprature`.

## Check a config

```sh
qretools-harness check-config config.toml
```

The command reads the instrument that the config names. It refuses the config if a key
or a value is not correct. It refuses an instrument that it cannot read, or that holds no
question. It also refuses the config if a URN in `prompts` is not a question in the DDI,
or if the version of the question in the DDI is different. Then the question changed
after you wrote its prompt. Read the question again, change the prompt if necessary, and
write the new version in the URN.

It also refuses an instrument that has a roster, because qretools cannot record roster
rows in a dataset yet.

The command does not connect to the model server, and does not run qretools.

The exit codes are:

| Code | Meaning |
|---|---|
| 0 | The config matches the instrument. |
| 1 | The command refused the config or the instrument. |
| 2 | The command line is not correct. |

## The qretools version

The harness runs one qretools version: the version in `QRETOOLS` in
[`src/qretools_harness/qretools.py`](src/qretools_harness/qretools.py), now
`qretools@2.0.0-alpha.12`. The harness runs it with `npx -y`, so you need Node 22 or
later and access to the npm registry the first time.

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

The tests do not run qretools.

One test sends a message to a model server. It runs only if
`QRETOOLS_HARNESS_MODEL_URL` gives the base URL of the server.
`QRETOOLS_HARNESS_MODEL` gives the name of the model:

```sh
QRETOOLS_HARNESS_MODEL_URL=http://127.0.0.1:9931/v1 \
QRETOOLS_HARNESS_MODEL=ggml-org/LFM3-Omni-2B-GGUF:Q8_0 uv run pytest
```

To use a qretools build that is not released, set `QRETOOLS_HARNESS_QRETOOLS` to the
path of its JavaScript file, for example `packages/cli/dist/qretools.js` in a clone of
qretools. The harness then runs that file with the `node` on `PATH`, in place of
`QRETOOLS`. This is for development only.

## Licence

MIT. See [LICENSE](LICENSE).
