"""The config of a run with a model, and its check against the instrument's DDI.

The config is TOML: the standard library reads it (`tomllib`), it has comments, and
multi-line strings suit prompts. It holds only what is about the model. The instrument,
its questions and their versions come from the DDI, never from here.

Every function returns a value. Nothing here raises for a bad config.
"""

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from qretools_harness.qretools import Refused

# Keys the harness sets itself, or that the client can't read a reply for.
RESERVED = frozenset({"model", "messages", "stream", "n"})


@dataclass(frozen=True)
class Urn:
    """A DDI URN with its version: `urn:ddi:<agency>:<id>:<version>`."""

    agency: str
    id: str
    version: str

    def __str__(self) -> str:
        return f"urn:ddi:{self.agency}:{self.id}:{self.version}"


@dataclass(frozen=True)
class Model:
    endpoint: str  # an OpenAI-compatible base URL, without its trailing /
    name: str
    timeout: float  # seconds


@dataclass(frozen=True)
class Config:
    instrument: (
        Path  # the instrument's DDI; a relative path is from the config's folder
    )
    model: Model
    generation: Mapping[str, object]  # sent to the server as written
    system: str
    missing: frozenset[
        str
    ]  # the missing codes the model may give, where a variable has them
    no_answer: str  # the missing code recorded when the model gives no allowed answer
    draw: frozenset[str]  # inputs drawn from their choices with the respondent's seed
    inputs: Mapping[str, str | int | float]  # inputs given as written
    prompts: Mapping[Urn, str]


class _Bad(Exception):
    """Internal only: a reason, raised inside `parse` and returned as Refused."""


def urn_of(text: str) -> Urn | None:
    parts = text.split(":")
    if len(parts) != 5 or parts[0].lower() != "urn" or parts[1].lower() != "ddi":
        return None
    _, _, agency, id, version = parts
    return Urn(agency, id, version) if agency and id and version else None


def _table(value: object, where: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _Bad(f"`{where}` must be a table.")
    unknown = sorted(set(value) - keys)
    if unknown:
        dotted = ", ".join(f"`{where}.{k}`" if where else f"`{k}`" for k in unknown)
        raise _Bad(f"Unknown key {dotted} in the config.")
    return value


def _required(table: dict[str, object], key: str, where: str) -> object:
    if key not in table:
        raise _Bad(f"The config has no `{where + '.' if where else ''}{key}`.")
    return table[key]


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Bad(f"`{where}` must be text, not empty.")
    return value


def _number(value: object, where: str) -> float:
    # bool is an int in Python; a config's `true` is never a number.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _Bad(f"`{where}` must be a number.")
    if not math.isfinite(value):
        raise _Bad(f"`{where}` must be a finite number.")
    return value


def _integer(value: object, where: str, least: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise _Bad(f"`{where}` must be a whole number, {least} or more.")
    return value


def _model(value: object) -> Model:
    t = _table(value, "model", {"endpoint", "name", "timeout"})
    endpoint = _text(_required(t, "endpoint", "model"), "model.endpoint").rstrip("/")
    url = urlsplit(endpoint)
    if url.scheme not in ("http", "https") or not url.hostname:
        raise _Bad("`model.endpoint` must be an http or https URL.")
    timeout = _number(_required(t, "timeout", "model"), "model.timeout")
    if timeout <= 0:
        raise _Bad("`model.timeout` must be more than 0 seconds.")
    return Model(endpoint, _text(_required(t, "name", "model"), "model.name"), timeout)


def _generation(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _Bad("`generation` must be a table.")
    reserved = sorted(RESERVED & set(value))
    if reserved:
        keys = ", ".join(f"`generation.{k}`" for k in reserved)
        raise _Bad(f"The harness sets {keys} itself; remove it from the config.")
    if "temperature" in value:
        _number(value["temperature"], "generation.temperature")
    if "max_tokens" in value:
        _integer(value["max_tokens"], "generation.max_tokens", 1)
    # 0 or more: llama.cpp takes -1 as "random", and a run must record its seed.
    if "seed" in value:
        _integer(value["seed"], "generation.seed", 0)
    _json(value, "generation")
    return MappingProxyType(dict(value))


def _json(value: object, where: str) -> None:
    """A value JSON can carry: TOML also has dates and times, which it can't."""
    if isinstance(value, dict):
        for k, v in value.items():
            _json(v, f"{where}.{k}")
    elif isinstance(value, list):
        for v in value:
            _json(v, where)
    elif isinstance(value, float) and not math.isfinite(value):
        raise _Bad(f"`{where}` must be a finite number.")
    elif not isinstance(value, str | int | float | bool):
        raise _Bad(f"`{where}` can't be sent as JSON; write it as text or a number.")


def _codes(value: object, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(
        isinstance(v, str) and v.strip() for v in value
    ):
        raise _Bad(f'`{where}` must be a list of text, for example ["a", "b"].')
    return frozenset(value)


def _inputs(value: object) -> Mapping[str, str | int | float]:
    if not isinstance(value, dict):
        raise _Bad("`inputs` must be a table.")
    for key, given in value.items():
        if isinstance(given, bool) or not isinstance(given, str | int | float):
            raise _Bad(f"`inputs.{key}` must be text or a number.")
        _json(given, f"inputs.{key}")
    return MappingProxyType(dict(value))


def _prompts(value: object) -> Mapping[Urn, str]:
    if not isinstance(value, dict):
        raise _Bad("`prompts` must be a table.")
    prompts: dict[Urn, str] = {}
    for key, text in value.items():
        urn = urn_of(key)
        if urn is None:
            raise _Bad(
                f"Prompt key `{key}` isn't a question's URN with its version"
                " (`urn:ddi:<agency>:<id>:<version>`)."
            )
        if urn in prompts:
            raise _Bad(f"Two prompts name `{urn}`.")
        prompts[urn] = _text(text, f"prompts.{key}")
    return MappingProxyType(prompts)


def _instrument(value: object, folder: Path) -> Path:
    text = _text(value, "instrument")
    if not text.endswith(".json"):
        if "@" in text:
            raise _Bad(
                f"`instrument` is a tag reference ({text}). The harness can't use one"
                " yet, because `qretools next` reads only a DDI file. Build the"
                " instrument with qretools and give the path of its .json file."
            )
        raise _Bad("`instrument` must be the path of the instrument's DDI (.json).")
    return folder / text  # an absolute path stays as written


def parse(text: str, folder: Path) -> Config | Refused:
    """A config from the text of a TOML file, or why it isn't one. `folder` is the
    config file's folder: a relative `instrument` starts there."""
    try:
        top = _table(
            tomllib.loads(text),
            "",
            {"instrument", "model", "generation", "run", "inputs", "prompts"},
        )
        run = _table(
            _required(top, "run", ""),
            "run",
            {"system", "missing", "no_answer", "draw"},
        )
        inputs = _inputs(top.get("inputs", {}))
        draw = _codes(run.get("draw", []), "run.draw")
        both = sorted(draw & set(inputs))
        if both:
            names = ", ".join(f"`{n}`" for n in both)
            raise _Bad(f"{names} is both drawn (`run.draw`) and given (`inputs`).")
        return Config(
            instrument=_instrument(_required(top, "instrument", ""), folder),
            model=_model(_required(top, "model", "")),
            generation=_generation(top.get("generation", {})),
            system=_text(_required(run, "system", "run"), "run.system"),
            missing=_codes(run.get("missing", []), "run.missing"),
            no_answer=_text(_required(run, "no_answer", "run"), "run.no_answer"),
            draw=draw,
            inputs=inputs,
            prompts=_prompts(top.get("prompts", {})),
        )
    except tomllib.TOMLDecodeError as error:
        return Refused(f"The config isn't TOML: {error}.")
    except _Bad as bad:
        return Refused(str(bad))


def stale(config: Config, ddi: object) -> Refused | None:
    """Why a prompt doesn't match the instrument's DDI, for every prompt that doesn't.

    A prompt names one version of a question. If the DDI has that question only at
    other versions, the question changed after the prompt was written.
    """
    questions = ddi.get("QuestionItem") if isinstance(ddi, dict) else None
    if not isinstance(questions, dict) or not questions:
        return Refused("This isn't an instrument's DDI: it has no QuestionItem.")
    versions: dict[tuple[str, str], set[str]] = {}
    for item in questions.values():
        if isinstance(item, dict):
            key = (str(item.get("Agency")), str(item.get("ID")))
            versions.setdefault(key, set()).add(str(item.get("Version")))
    problems = []
    for urn in config.prompts:
        present = versions.get((urn.agency, urn.id))
        if present is None:
            problems.append(f"The instrument has no question {urn.id} ({urn}).")
        elif urn.version not in present:
            now = ", ".join(sorted(present))
            problems.append(
                f"Question {urn.id} changed since its prompt was written"
                f" (prompt: version {urn.version}; instrument: {now}); review it."
            )
    return Refused("\n".join(problems)) if problems else None
