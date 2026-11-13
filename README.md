# qretools-harness

qretools-harness asks a language model the questions of a
[qretools](https://github.com/JHUCities/qretools) instrument. The model answers as one or
more respondents. The harness then makes a dataset with qretools.

## The words

| Word | What it means |
|---|---|
| instrument | A survey: its questions and their order. qretools writes it as DDI. |
| dataset | A DDI document. It holds the answers and their provenance. |
| provenance | Where the answers came from: who answered, what asked the questions, when, and with which files. |
| config | A TOML file. It holds the settings of a run. |
| run | One `qretools-harness respond` command. It interviews the model one time for each respondent. A run writes one folder. It makes one dataset from the respondents that finish. See "Errors". |
| respondent | One interview. The model answers as one person, with its own seed and its own conversation. |
| trace | One line in `traces.jsonl`: one call to the model, or one other event. |

A dataset records two different facts:

- **Who answered.** For example, people, or a language model.
- **How the questions were asked.** For example, by an interviewer, on the web through a
  survey platform such as Qualtrics, or in a simulation.

The harness makes only one kind of dataset: a language model answered, in a simulation. To make a dataset from
real answers, use qretools. The README of the qretools workspace gives the procedure.

## The two programs

- **qretools** knows the survey. It decides the next question, and it writes all the DDI.
- **The harness** calls the model. It does not read the routing, and it does not decide
  the next question.

## Install

You need these tools:

- [uv](https://docs.astral.sh/uv/).
- [Node.js](https://nodejs.org/) 22 or later, with `npx`.
- A model server with an OpenAI-compatible API, for example llama.cpp.

The harness is not on PyPI. Install it from git:

```sh
uv tool install git+https://github.com/JHUCities/qretools-harness
```

The harness runs one qretools version: the value of `QRETOOLS` in
[`src/qretools_harness/qretools.py`](src/qretools_harness/qretools.py), now
`qretools@2.0.0-alpha.13`. A test checks that this README names the same version. The
harness runs it with `npx -y`. The first time, `npx` needs access
to the npm registry.

## Run a model through an instrument

1. Run `qretools build` in the qretools workspace. The DDI of each instrument is
   `dist/instruments/<name>.json`.
2. Write a config. See "The config".
3. Check the config:

   ```sh
   qretools-harness check-config config.toml
   ```

4. Start the model server. For llama.cpp, give a context of 8,192 tokens and one slot
   (`-c 8192 -np 1`).
**Caution: do not put the run folder in a qretools workspace.** The folder must not
exist, or it must be empty.

5. Start the run:

   ```sh
   qretools-harness respond config.toml -n 3 -o runs/try-1
   ```

   `-n` is the number of respondents. `-o` is the run folder.

## The config

[`examples/config.toml`](examples/config.toml) is an example.

| Table | Key | What it holds |
|---|---|---|
| (top) | `instrument` | The path or the `https://` URL of the instrument's DDI. A relative path starts from the folder of the config. Write this key before the first table. |
| `model` | `endpoint` | The base URL of the model server, for example `http://127.0.0.1:9931/v1`. |
| `model` | `name` | The name of the model. |
| `model` | `timeout` | The maximum time for one reply, in seconds. |
| `generation` | any key | The settings that the harness sends to the server without change, for example `temperature`, `max_tokens` and `seed`. The harness checks the types of these three keys only. It refuses `model`, `messages`, `stream` and `n`, because it sets them. |
| `run` | `system` | The system prompt. |
| `run` | `missing` | The missing codes that the model can give, for example `["D", "R"]`. The harness offers a code only for a question that has it. Without this key, the model must choose an answer. |
| `run` | `no_answer` | The missing code that the harness records if the model gives no accepted answer. Give each question this code. `check-config` does not check it. |
| `run` | `draw` | The names of the inputs that the harness chooses at random, with the seed of the respondent. |
| `inputs` | the name of an input | The value of the input, for each respondent. |
| `prompts` | the URN of a question | More text for the model about that question. The URN includes the version of the question. |

Rules for the config:

- Give `generation.seed` and `run.no_answer`.
- Do not write an API key in the config. The run folder keeps a copy of the config.
- The harness refuses an unknown key, except in `generation`.
- The harness does not accept a tag reference (`owner/repo@tag:name`) for `instrument`.
  Give the `https://` URL of the instrument's DDI in the release.

`check-config` refuses the config in these conditions:

- A key or a value is not correct.
- The harness cannot read the instrument, or the instrument has no question.
- The instrument has a roster. qretools cannot record the rows of a roster in a dataset yet.
- A URN in `prompts` is not a question of the instrument.
- The version in a URN in `prompts` is not the version in the DDI.

If the version is different, then the question changed after you wrote its prompt. Read
the question again. Change the prompt if necessary. Then write the new version in the URN.

`check-config` does not connect to the model server, and does not run qretools.

### An instrument by URL

If `instrument` is a URL, then the harness reads the DDI from the URL. It reads only
`https://` URLs.

- `check-config` reads the URL one time. `respond` also reads it one time, before the
  first respondent.
- The harness gives the URL to qretools without change. qretools reads the URL again at
  each step, and `qretools responses` reads it one more time.
- Do not change the DDI at the URL during a run.
- The first line of `traces.jsonl` records the SHA-256 digest of the DDI that the harness
  read. The dataset records the digest of the DDI that `qretools responses` read. If the
  two digests are different, then the DDI changed during the run.

## What `respond` does

For each respondent, the harness does these steps:

1. It gives respondent *i* the seed `generation.seed + i - 1`.
2. It records the start time.
3. It asks `qretools next` for the next step. qretools gives one of three replies:
   - `input`: the harness gives the value from `inputs`, or it draws one from `draw`. If
     the config gives neither, then it sends "not known" (`null`).
   - `ask`: the harness sends the question to the model, and records the answer.
   - `end`: the harness records the end time.
4. If the harness or qretools does not accept an answer, then the harness asks again,
   with the reason. After the third answer that it does not accept, it records the
   `no_answer` code. If qretools
   does not accept that code, then the respondent stops.

Then the harness writes the run folder, and starts `qretools responses`. That command
writes the dataset.

| File | What it holds |
|---|---|
| `answers.csv` | One line for each value: `respondent,variable,row,value`. The variable is the URN of a DDI variable. The values of the inputs are there too. Each respondent also has a `start` line and an `end` line, in UTC. |
| `traces.jsonl` | The settings of the run, then one line for each event: a call to the model, an input, a `no_answer` code, the end of an interview, or a respondent that stopped. |
| `config.toml` | A copy of the config. |
| `dataset.json` | The dataset, from `qretools responses`. It records the digests of `traces.jsonl` and `config.toml`. |

**Caution: do not publish `answers.csv` or `traces.jsonl` without a check.** The traces
can hold local paths of the server's computer, for example the path of the model file.
To publish the provenance without the answers, write a view with qretools:

```sh
qretools dataset export runs/try-1/dataset.json --provenance --ddi <DDI> -o provenance.json
```

`--ddi` is the DDI of the instrument: its path or its URL. If the DDI declares access
levels, then also give `--access <level>`.

### What a run records

The first line of `traces.jsonl` records each setting that can change the result:

- the command line, the number of respondents and the seed of each respondent;
- the config, with the defaults;
- the path or the URL of the instrument, and the SHA-256 digest of the DDI that the
  harness read;
- the qretools version, and the harness version;
- what the server tells about itself: its software, its build, the context size, the
  sampler settings, the chat template and its launch arguments.

The harness writes `<redacted>` in place of a launch argument whose name holds `key`,
`token`, `secret` or `password`.

The dataset names the server's software as the runtime, for example `llama.cpp`. If the
server does not give its software, then the runtime is `unknown`. The dataset names the
server's build as the runtime version, if the server gives it. The model and its
settings are in `config.toml`.

### How the harness reads a reply

- For a question with options, the reply can be a code, the full label of an option, or
  a code then a space or punctuation (`3. Retired`).
- For a number, the reply must start with digits, in the range of the question. It must
  not have more decimals than the question permits. The harness does not read number
  words.
- For "select all that apply", the reply gives the codes of the selected options, or
  `none`.
- The harness does not accept a reply that the server cut off at `max_tokens`.

### Errors

- If the model server or qretools fails during an interview, then that respondent
  stops. The harness goes on with the next respondent.
- If the harness cannot connect to the server, then the run stops.
- The dataset holds only the respondents that finished. If one or more respondents
  stopped, then the command exits with 1 and gives the reasons.
- If no respondent finished, then the command writes no `answers.csv` and no dataset.
- If `qretools responses` refuses the answers, then the command keeps `answers.csv`. It
  exits with 1, and it prints the command that runs `qretools responses` again.

The exit codes are:

| Code | Meaning |
|---|---|
| 0 | The command did its work. |
| 1 | The command refused the input, or a step failed. |
| 2 | The command line is not correct. |

### Limits

- Each question and each answer stay in the conversation. If the conversation is larger
  than the context of the model, then that respondent stops. The command prints the size
  of the largest prompt.
- To get the same answers again, llama.cpp must use one slot (`-np 1`).
- The harness gives the options in their written order. It ignores `responseOrder`.
- Each step runs `npx`. This adds a fraction of a second to each step. If `instrument`
  is a URL, then qretools reads the URL at each step. This adds more time to each step.

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

One test runs `respond` with the pinned qretools and a stand-in for the model. It runs if
`npx` is on `PATH`.

One test sends a message to a model server. It runs only if you give the server and the
model:

```sh
QRETOOLS_HARNESS_MODEL_URL=http://127.0.0.1:9931/v1 \
QRETOOLS_HARNESS_MODEL=ggml-org/LFM3-Omni-2B-GGUF:Q8_0 uv run pytest
```

To use a development copy of qretools, set `QRETOOLS_HARNESS_QRETOOLS` to the
path of its JavaScript file, for example `packages/cli/dist/qretools.js`. The harness then
runs that file with `node`. Use this for development only.

## Licence

MIT. See [LICENSE](LICENSE).
