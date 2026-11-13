"""One interview of a model through an instrument: the prompts, the parsing of replies,
and the loop.

qretools decides the route: the loop calls `next` for each step and does what the reply
says. The text the model gets, and how its reply becomes a value, are decided here.
Everything is pure except the two functions the loop is given, `next` and `complete`,
and `record`, which keeps each trace as it is made.

The replies of `qretools next` are read as JSON objects without a schema of their own
here: qretools publishes it (`qretools next --schema`), and only its fields are read.
"""

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from qretools_harness.chat import Reply
from qretools_harness.config import Config, urn_of
from qretools_harness.qretools import Refused

# How many times a question is asked again after an answer that isn't allowed, or that
# qretools doesn't take. Then the config's `no_answer` code is recorded.
RETRIES = 2

Value = str | int | float
Message = Mapping[str, str]
State = dict[str, Any]  # `qretools next`'s state: {"inputs": {...}, "answers": [...]}
Step = Mapping[str, Any]  # one reply of `qretools next`
Trace = Mapping[str, object]

Next = Callable[[State], Step | Refused]
Complete = Callable[[Sequence[Message], int], Reply | Refused]
Record = Callable[[Trace], None]


@dataclass(frozen=True)
class Failure:
    """Why a reply isn't an answer the domain takes, as a sentence for the model."""

    reason: str


# --- What the model may answer --------------------------------------------------------


def offered(
    missing: Sequence[Mapping[str, str]], codes: frozenset[str]
) -> list[Mapping[str, str]]:
    """The variable's missing codes that the config lets the model give, in its order."""
    return [m for m in missing if m["code"] in codes]


def variables(domain: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The variables a domain records: one, or one for each select-all option."""
    return list(domain["options"]) if domain["kind"] == "select-all" else [domain]


def listed(choices: Sequence[Mapping[str, str]]) -> str:
    return "\n".join(f"{c['code']}: {c['label']}" for c in choices)


def number_rule(domain: Mapping[str, Any]) -> str:
    kind = (
        "a whole number"
        if domain["decimals"] == 0
        else (f"a number with at most {domain['decimals']} decimal places")
    )
    low, high = domain.get("min"), domain.get("max")
    if low is not None and high is not None:
        return f"{kind} from {low} to {high}"
    if low is not None:
        return f"{kind}, {low} or more"
    if high is not None:
        return f"{kind}, {high} or less"
    return kind


def answer_rule(domain: Mapping[str, Any], missing: Sequence[Mapping[str, str]]) -> str:
    """The options, and how to answer, at the end of a question's prompt."""
    kind = domain["kind"]
    if kind == "choice":
        return f"{listed([*domain['choices'], *missing])}\nAnswer with one code."
    if kind == "select-all":
        options = listed(domain["options"])
        rule = 'Answer with the codes of all that apply, separated by commas, or with "none".'
        if missing:
            rule += f" Or answer with one of these codes:\n{listed(missing)}"
        return f"{options}\n{rule}"
    if kind == "number":
        rule = f"Answer with {number_rule(domain)}."
    elif kind == "text" and "maxLength" in domain:
        rule = f"Answer in your own words, in at most {domain['maxLength']} characters."
    else:
        rule = "Answer in your own words."
    return (
        f"{rule}\nOr answer with one of these codes:\n{listed(missing)}"
        if missing
        else rule
    )


def prompt_of(ask: Step, extra: str | None, codes: frozenset[str]) -> str:
    """The text the model gets for one question: what was said since the last question,
    the question with its fills, its instructions, the config's text for it, and the
    answers it may give."""
    domain = ask["domain"]
    missing = offered(variables(domain)[0]["missing"], codes)
    parts = [*ask["statements"], ask["text"], *ask["instructions"]]
    if extra:
        parts.append(extra.strip())
    parts.append(answer_rule(domain, missing))
    return "\n\n".join(parts)


# --- Reading the model's reply --------------------------------------------------------


def plain(text: str) -> str:
    """The reply without the quotes, emphasis and closing stop a model wraps it in."""
    quotes = "\"'`* \u201c\u201d\u2018\u2019"
    return text.strip().rstrip(".! ").strip(quotes).rstrip(".! ")


def coded(
    text: str, choices: Sequence[Mapping[str, str]], whole: bool = False
) -> str | None:
    """The code a reply names: the code itself, its whole label (any case), or, unless
    `whole`, the code first, then punctuation or a space ("3. Retired"). A label is never
    matched by part: "Satisfied" is in "Very satisfied"."""
    t = plain(text)
    for c in choices:
        if t == c["code"] or t.casefold() == c["label"].casefold():
            return c["code"]
    first = None if whole else re.match(r"[A-Za-z0-9]+(?![A-Za-z0-9'\u2019])", t)
    if first:
        for c in choices:
            if first.group() == c["code"]:
                return c["code"]
    return None


def number_of(text: str, domain: Mapping[str, Any]) -> Value | Failure:
    """A number the domain takes, from a reply that starts with one ("40 hours")."""
    found = re.match(r"-?\d[\d,]*(\.\d+)?", plain(text))
    if not found:
        return Failure("That isn't a number.")
    digits = found.group().replace(",", "")
    fraction = digits.partition(".")[2].rstrip("0")
    if len(fraction) > domain["decimals"]:
        return Failure(f"The answer must be {number_rule(domain)}.")
    value: Value = float(digits) if fraction else int(float(digits))
    low, high = domain.get("min"), domain.get("max")
    if (low is not None and value < low) or (high is not None and value > high):
        return Failure(f"The answer must be {number_rule(domain)}.")
    return value


def value_of(
    domain: Mapping[str, Any], text: str, codes: frozenset[str]
) -> list[tuple[str, Value]] | Failure:
    """The (variable, value) pairs a reply gives, or why it gives none."""
    kind = domain["kind"]
    missing = offered(variables(domain)[0]["missing"], codes)
    # Only a whole reply is a missing code where words or numbers are answers too:
    # "D.C." is a place, and "98" a number, where D or 98 is a missing code.
    code = coded(text, missing, whole=kind not in ("choice", "select-all"))
    if kind == "select-all":
        options = domain["options"]
        if code is not None:
            return [(o["variable"], code) for o in options]
        if plain(text).casefold() == "none":
            return [(o["variable"], o["unticked"]) for o in options]
        given = [g for g in re.split(r"[\s,;]+", plain(text)) if g]
        ticked = {coded(g, options) for g in given}
        if not given or None in ticked:
            return Failure('Answer only with the codes of the options, or with "none".')
        return [
            (o["variable"], o["ticked"] if o["code"] in ticked else o["unticked"])
            for o in options
        ]
    variable = domain["variable"]
    if code is not None:
        return [(variable, code)]
    if kind == "choice":
        found = coded(text, domain["choices"])
        return [(variable, found)] if found else Failure("That isn't one of the codes.")
    if kind == "number":
        number = number_of(text, domain)
        return number if isinstance(number, Failure) else [(variable, number)]
    words = text.strip()
    if not words:
        return Failure("The answer is empty.")
    if kind == "text" and len(words) > domain.get("maxLength", len(words)):
        return Failure(f"The answer must be at most {domain['maxLength']} characters.")
    return [(variable, words)]


# --- Inputs -----------------------------------------------------------------------------


def input_of(
    step: Step, config: Config, rng: random.Random
) -> tuple[Value | None, str] | Refused:
    """The value given for an input, and how it was chosen: from the config, drawn from
    the input's choices, or none (sent as not known, because the config doesn't say)."""
    name = step["name"]
    if name in config.inputs:
        return config.inputs[name], "config"
    if name in config.draw:
        if step["domain"]["kind"] != "choice":
            return Refused(f"The input {name} has no choices, so it can't be drawn.")
        return rng.choice(step["domain"]["choices"])["code"], "drawn"
    return None, "not in the config"


def extra_of(config: Config, ask: Step) -> str | None:
    """The config's text for the question asked, by its URN with its version."""
    urn = urn_of(ask["questionUrn"])
    return config.prompts.get(urn) if urn else None


# --- The loop ---------------------------------------------------------------------------


def interview(
    respondent: str,
    seed: int,
    config: Config,
    next: Next,
    complete: Complete,
    record: Record,
) -> State | Refused:
    """One respondent's interview, from an empty state to `end`; the final state.

    Each model call, input and recorded `no_answer` is passed to `record` as it happens,
    so a run that stops still has its traces.
    """
    state: State = {"inputs": {}, "answers": []}
    messages: list[Message] = [{"role": "system", "content": config.system}]
    rng = random.Random(seed)
    asked: dict[tuple[str, int | None], int] = {}  # model calls for each question
    given: list[dict[str, Any]] = []  # the answers last sent, taken back on a problem
    gave_up = False  # the last answers were `no_answer`

    def where(step: Step) -> str:
        row = f", row {step['row']}" if "row" in step else ""
        return f"respondent {respondent}, {step.get('step') or step.get('name')}{row}"

    while True:
        step = next(state)
        if isinstance(step, Refused):
            return step
        if step["kind"] == "end":
            return state
        if step["kind"] == "input":
            chosen = input_of(step, config, rng)
            if isinstance(chosen, Refused):
                return Refused(f"{where(step)}: {chosen.reason}")
            value, how = chosen
            state["inputs"][step["name"]] = value
            record(
                {
                    "kind": "input",
                    "respondent": respondent,
                    "input": step["name"],
                    "value": value,
                    "how": how,
                    "notes": step["notes"],
                }
            )
            continue

        problem = step.get("problem")
        if problem is not None:
            if gave_up:
                return Refused(
                    f"{where(step)}: qretools doesn't take the `no_answer` code"
                    f" either: {problem}"
                )
            taken = {id(a) for a in given}
            state["answers"] = [a for a in state["answers"] if id(a) not in taken]
        domain = step["domain"]
        for v in variables(domain):
            if config.no_answer not in {m["code"] for m in v["missing"]}:
                return Refused(
                    f"{where(step)}: {v['name']} has no missing code"
                    f" {config.no_answer} (`run.no_answer`)."
                )
        key = (step["step"], step.get("row"))
        prompt = prompt_of(step, extra_of(config, step), config.missing)
        if problem is not None:
            prompt = f"That answer can't be taken: {problem}\n\n{prompt}"
        answers: list[tuple[str, Value]] | None = None
        while answers is None and asked.get(key, 0) <= RETRIES:
            asked[key] = asked.get(key, 0) + 1
            messages.append({"role": "user", "content": prompt})
            reply = complete(messages, seed)
            if isinstance(reply, Refused):
                return Refused(f"{where(step)}: {reply.reason}")
            messages.append({"role": "assistant", "content": reply.text})
            parsed = (
                Failure("That answer is too long.")
                if reply.finish_reason == "length"
                else value_of(domain, reply.text, config.missing)
            )
            record(
                {
                    "kind": "call",
                    "respondent": respondent,
                    "step": step["step"],
                    **({"row": step["row"]} if "row" in step else {}),
                    "question": step["questionUrn"],
                    "seed": seed,
                    "messages": [dict(m) for m in messages[:-1]],
                    "reply": reply.text,
                    "finish_reason": reply.finish_reason,
                    "model": reply.model,
                    "fingerprint": reply.fingerprint,
                    "usage": dict(reply.usage),
                    "timings": reply.body.get("timings"),
                    "notes": step["notes"],
                    **(
                        {"failure": parsed.reason}
                        if isinstance(parsed, Failure)
                        else {
                            "answers": [{"variable": v, "value": x} for v, x in parsed]
                        }
                    ),
                }
            )
            if isinstance(parsed, Failure):
                missing = offered(variables(domain)[0]["missing"], config.missing)
                prompt = f"{parsed.reason} {answer_rule(domain, missing)}"
            else:
                answers = parsed
        gave_up = answers is None
        if answers is None:
            answers = [(v["variable"], config.no_answer) for v in variables(domain)]
            record(
                {
                    "kind": "no_answer",
                    "respondent": respondent,
                    "step": step["step"],
                    **({"row": step["row"]} if "row" in step else {}),
                    "code": config.no_answer,
                    "why": f"no answer taken in {1 + RETRIES} asks",
                    # Why qretools refused the last answer, if it did.
                    **({"problem": problem} if problem is not None else {}),
                }
            )
        row = {"row": step["row"]} if "row" in step else {}
        given = [{"variable": v, **row, "value": x} for v, x in answers]
        state["answers"].extend(given)
