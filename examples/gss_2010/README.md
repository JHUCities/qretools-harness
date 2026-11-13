# Example: the GSS 2010 instrument

This example asks a language model the questions of the General Social Survey (GSS) 2010
instrument. The model answers as three respondents. The harness then makes a dataset,
and you check its provenance.

The instrument is the DDI of `gss_2010` in the `v15` release of
[qretools-gss](https://github.com/JHUCities/qretools-gss). The config gives its URL:

```
https://jhucities.github.io/qretools-gss/v15/instruments/gss_2010.json
```

## What you need

- [uv](https://docs.astral.sh/uv/), and the harness. See "Install" in the
  [main README](../../README.md).
- [Node.js](https://nodejs.org/) 22 or later, with `npx`.
- A model server with an OpenAI-compatible API at `http://127.0.0.1:9931/v1`. For
  llama.cpp, give a context of 8,192 tokens and one slot (`-c 8192 -np 1`).
- The model that `[model] name` in [`config.toml`](config.toml) gives.
- Access to the internet. The harness and qretools read the DDI from its URL.

## Procedure

In the commands, `<version>` is the qretools version that the harness runs. The main
README gives it.

**Caution: do not put the run folder in a git repository.** The folder holds the answers
and the traces.

1. Go to the folder of this README.

2. Check the config:

   ```sh
   qretools-harness check-config config.toml
   ```

3. Start the model server.

4. Start the run. Use a new folder outside each repository, for example
   `~/qretools-runs/gss_2010-1`:

   ```sh
   qretools-harness respond config.toml -n 3 -o ~/qretools-runs/gss_2010-1
   ```

5. Go to the run folder:

   ```sh
   cd ~/qretools-runs/gss_2010-1
   ```

6. Write the provenance view of the dataset. Give the same URL to `--ddi`:

   ```sh
   npx -y qretools@<version> dataset export dataset.json --provenance \
     --ddi https://jhucities.github.io/qretools-gss/v15/instruments/gss_2010.json \
     -o provenance.json
   ```

7. Write the values of the dataset as CSV:

   ```sh
   npx -y qretools@<version> dataset export dataset.json --csv \
     --ddi https://jhucities.github.io/qretools-gss/v15/instruments/gss_2010.json \
     -o values.csv
   ```

## Checks

Do these checks on `provenance.json` and `traces.jsonl`. Each check must pass.

1. Find the `OtherMaterial` item whose `TypeOfMaterial` has the `StringValue`
   `instrument DDI`. Make sure of these two facts:
   - Its `ExternalURLReference` holds the URL of the instrument.
   - The `StringValue` of its `UserID` is equal to the `sha256` of `instrument` in the
     first line of `traces.jsonl`.
2. Find the `CollectionEvent` in `DataCollection`. Make sure that it has a
   `DataCollectionDate` with a `StartDate` and an `EndDate`.
3. Find the `SourceType` in the `DataSource` of that `CollectionEvent`. Make sure that
   its `OtherValue` is `synthetic`.
4. Make sure that `provenance.json` holds no `ItemSet`. The provenance view holds no
   values.

If the two digests in check 1 are different, then the DDI at the URL changed during the
run. Start the run again.

## Comparison with real GSS answers

The harness does not compare the answers of the model with the answers of real GSS
respondents. That comparison is outside the harness. The QREtools research skill
describes it.
