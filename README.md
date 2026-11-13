# qretools-harness

qretools-harness asks a language model the questions of a
[qretools](https://github.com/JHUCities/qretools) instrument. The model answers as a
respondent. The answers are a synthetic dataset, keyed by the DDI variables of the
instrument.

This version has two commands: `check-config` and `respond`. The other parts come later.
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
| Access levels (who can see an answer) | yes | It does not filter. `qretools dataset export --access` writes a view. |
| The model and its settings | no | yes, in the config |
| The extra text for each question, for the model | no | yes, in the config |
| The prompt that the model gets | no | It makes the prompt from the DDI and the config. It keeps each prompt in the traces. |
| The dataset and its provenance | yes: `qretools responses` writes them | It gives the answers, the traces and the config to qretools. |

The DDI of the instrument never changes after a run. A run adds new DDI items that refer to
the instrument.

### The run folder

Each run with a model has one folder. The harness writes it, outside any workspace:

```
runs/<id>/
  answers.csv     the answers, and the start and end time of each interview
  traces.jsonl    the traces
  config.toml     a copy of the config
  dataset.json    the dataset, written by `qretools responses`
```

`dataset.json` is a DDI document. It holds each value, the time of each interview, and the
provenance: the instrument and its digest, the dates, that the answers are synthetic, the
runtime, and the SHA-256 digest of the traces and of the config.

The rule is: **derive, do not declare.** qretools reads each fact from a file if it can. The
dates come from the times in `answers.csv`. The harness gives on the command line only
the facts that no file holds: that the answers are synthetic, and the runtime.

**Caution: do not commit or publish a dataset of real answers.** Git ignores `runs/`.
`qretools dataset export --provenance` writes a view without the values.

### Weights

A survey of people often needs a weight. Without it, the dataset does not describe the
population. A model run has no weight: each answer counts once.

- The tools never choose a weight. The researcher chooses it.
- qretools records each weight that the publisher gives, with the publisher's advice.

### Rules that protect the results

1. **A dataset holds one kind of respondent.** If a source holds people and test responses,
   the person makes one dataset for each kind.
2. **A synthetic dataset always says that it is synthetic.** It can have the same columns as
   real data. Its provenance never hides what made it.
3. **Each dataset goes through the access filter** before analysis:
   `qretools dataset export --access` writes a view at one access level.
4. **Record each run.** If you change the config and run again, each run has its own folder,
   with its own config and its own provenance.

### The parts and their status

| Part | Status |
|---|---|
| `qretools next`: the next step of an interview, so that the interview follows the routing | done, in qretools |
| `qretools responses`: the dataset and its provenance | done, in qretools |
| `qretools dataset export`: a view of a dataset, at an access level | done, in qretools |
| The config, its check against the DDI, and the client for the model server | done |
| `qretools-harness respond`: a model answers the instrument, as an interview | done |
| An instrument given as a tag reference | later: `qretools next` must read one first |
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

## Run a model through an instrument

1. Build the DDI of the instrument with qretools. The DDI of each instrument is
   `dist/instruments/<name>.json` in the workspace.
2. Write a config (see "Write a config"). Give `generation.seed` and `run.no_answer`.
3. Make sure that the model server runs.
4. Run the interviews:

   ```sh
   qretools-harness respond config.toml -n 3 -o runs/try-1
   ```

`-n` is the number of respondents. The run folder must not exist, or must be empty. Do not
put it in a workspace.

The command writes `answers.csv`, `traces.jsonl` and a copy of the config into the run
folder. Then it runs `qretools responses` in the run folder, which writes `dataset.json`.

| File | What it holds |
|---|---|
| `answers.csv` | One line for each value: `respondent,variable,row,value`. The variable is the URN of a DDI variable. Each respondent also has a `start` line and an `end` line, with the time in UTC. The respondents are `1`, `2`, and so on. |
| `traces.jsonl` | One line for each event. The first line gives the versions of qretools and of the harness. Each call to the model gives the messages as sent, the reply, the model that the server served, the server's build, the token counts, the server's timings, the notes of qretools, and the value or the reason that the harness did not accept the reply. Each input gives its value and where the value came from. The end of each interview gives its notes. |
| `config.toml` | A copy of the config. |
| `dataset.json` | Written by `qretools responses`. |

The runtime of the dataset is the model that the server says it served, or `model.name`
if the replies do not agree. The runtime version is the server's build
(`system_fingerprint`), if every reply gives the same one.

These are the rules of an interview:

- **The route.** The harness calls `qretools next` for each step. qretools decides the
  next question and its text. The harness does not evaluate a condition.
- **The prompt.** The prompt for a question has the statements since the last question,
  the text of the question, its instructions, the text from `prompts` for that question,
  the options with their codes, and how to answer. Each question and each answer stay in
  the conversation.
- **The seed.** Respondent *i* gets `generation.seed + i - 1`. With one seed for all,
  llama.cpp gives the same answers to each respondent. Thus, two runs whose seeds are
  near each other can have the same respondents.
- **The reply.** The harness accepts a code, the full label of an option (in any case),
  or a code followed by a space or punctuation (`3. Retired`). For a number, the reply
  must start with a number in the range, with no more decimals than the question allows.
  For select-all, the reply gives the codes of the ticked options, or `none`. A reply that
  the server cut off (`max_tokens`) is not accepted.
- **Retries.** If the harness does not accept a reply, or qretools does not accept the
  answer (`problem`), the harness asks the question again, with the reason. It asks a
  question at most 3 times. Then it records the `no_answer` code, and the traces say so.
  If qretools does not accept the `no_answer` code, the run stops.
- **Notes.** The harness writes the notes of qretools into the traces. A note never
  changes the interview, also a note with a code that the harness does not know.
- **Inputs.** If the route needs an input, the harness gives the value from `inputs`, or
  draws a value from `draw`. If the config gives neither, the harness sends "not known"
  (`null`), and says so on stderr and in the traces. A value that is not null goes into
  `answers.csv`, with the variable of the input.
- **Errors.** If the model server or qretools fails during the interviews, the run stops.
  The run folder then holds the config and the traces until the failure, and no
  `answers.csv`. If `qretools responses` refuses, the command gives the command line to
  run it again.

Limits:

- The conversation grows with each question, and each re-ask makes it longer. If the
  conversation is larger than the context of the model, the server gives an error, and
  the run stops. The run is all or nothing: the respondents that finished before the
  error are not in a dataset either. The command prints the size of the largest prompt.
  With the GSS 2010 instrument, a context of 4,096 tokens is too small. Use 8,192 tokens
  (for llama.cpp, `-c 8192`).
- For the same answers again, llama.cpp must use one slot (`-np 1`).
- The harness asks the options in their written order. It ignores `responseOrder`.
- `qretools responses` cannot hold an answer in a roster row yet. It refuses such a run.
- Each step runs `npx`, which adds a fraction of a second to each step.

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

One test runs `respond` with the pinned qretools, through `npx`, and a stand-in for the
model, against `tests/fixtures/flat.json` (the questions of qretools' households tests,
with no roster). The other tests do not run qretools. It runs if `npx` is on `PATH`. It needs access to the npm registry the first time.

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
