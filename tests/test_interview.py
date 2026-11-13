"""The prompts, the parsing of replies, and the interview loop, with stand-ins for
qretools next and the model."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from qretools_harness.chat import Reply
from qretools_harness.config import Config, parse
from qretools_harness.interview import (
    RETRIES,
    Failure,
    State,
    Trace,
    interview,
    prompt_of,
    value_of,
)
from qretools_harness.qretools import Refused

MISSING = [
    {"code": "D", "label": "Don't know"},
    {"code": "N", "label": "No answer"},
    {"code": "R", "label": "Refused"},
]
CHOICE = {
    "kind": "choice",
    "variable": "urn:v:tenure",
    "name": "tenure",
    "missing": MISSING,
    "choices": [
        {"code": "1", "label": "Very satisfied"},
        {"code": "2", "label": "Satisfied"},
    ],
}
NUMBER = {
    "kind": "number",
    "variable": "urn:v:hours",
    "name": "hours",
    "missing": MISSING,
    "min": 0,
    "max": 168,
    "decimals": 0,
}


def option(code: str) -> dict[str, Any]:
    return {
        "code": code,
        "label": f"Option {code}",
        "variable": f"urn:v:o{code}",
        "name": f"o{code}",
        "missing": MISSING,
        "ticked": "1",
        "unticked": "0",
    }


SELECT = {"kind": "select-all", "options": [option("a"), option("b")]}
TEXT = {
    "kind": "text",
    "variable": "urn:v:c",
    "name": "c",
    "missing": MISSING,
    "maxLength": 5,
}
DR = frozenset({"D", "R"})


def ask(domain: Mapping[str, Any], **more: object) -> dict[str, Any]:
    return {
        "kind": "ask",
        "step": f"urn:step:{domain.get('name', 'select')}",
        "question": "q",
        "questionUrn": "urn:ddi:a:q:1",
        "text": "How satisfied are you?",
        "instructions": ["Read the options."],
        "domain": domain,
        "statements": ["Now some questions."],
        "notes": [],
        **more,
    }


def test_a_prompt_holds_the_question_and_only_the_offered_missing_codes() -> None:
    prompt = prompt_of(ask(CHOICE), "Think of this year.", DR)
    assert prompt == (
        "Now some questions.\n\nHow satisfied are you?\n\nRead the options.\n\n"
        "Think of this year.\n\n"
        "1: Very satisfied\n2: Satisfied\nD: Don't know\nR: Refused\nAnswer with one code."
    )


def test_a_number_prompt_gives_the_range() -> None:
    assert "a whole number from 0 to 168." in prompt_of(ask(NUMBER), None, frozenset())
    assert "D: Don't know" not in prompt_of(ask(NUMBER), None, frozenset())


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ("2", "2"),
        (" '2'. ", "2"),
        ("satisfied", "2"),
        ("2. Satisfied", "2"),
        ("Don't know", "D"),
        ("R", "R"),
    ],
)
def test_a_choice_is_a_code_or_a_whole_label(reply: str, code: str) -> None:
    assert value_of(CHOICE, reply, DR) == [("urn:v:tenure", code)]


@pytest.mark.parametrize("reply", ["3", "Very", "N", "Don't", ""])
def test_a_choice_not_offered_is_a_failure(reply: str) -> None:
    assert isinstance(value_of(CHOICE, reply, DR), Failure)


@pytest.mark.parametrize(
    ("reply", "value"), [("40", 40), ("40 hours", 40), ("40.0", 40), ("1,0", 10)]
)
def test_a_number_in_range(reply: str, value: int) -> None:
    assert value_of(NUMBER, reply, DR) == [("urn:v:hours", value)]


@pytest.mark.parametrize("reply", ["169", "-1", "40.5", "forty"])
def test_a_number_out_of_its_domain_is_a_failure(reply: str) -> None:
    assert isinstance(value_of(NUMBER, reply, DR), Failure)


def test_decimals_are_kept_where_allowed() -> None:
    assert value_of({**NUMBER, "decimals": 1}, "2.5", DR) == [("urn:v:hours", 2.5)]


def test_select_all_gives_every_option_a_value() -> None:
    assert value_of(SELECT, "b", DR) == [("urn:v:oa", "0"), ("urn:v:ob", "1")]
    assert value_of(SELECT, "a, b", DR) == [("urn:v:oa", "1"), ("urn:v:ob", "1")]
    assert value_of(SELECT, "None.", DR) == [("urn:v:oa", "0"), ("urn:v:ob", "0")]
    assert value_of(SELECT, "D", DR) == [("urn:v:oa", "D"), ("urn:v:ob", "D")]
    assert isinstance(value_of(SELECT, "a, c", DR), Failure)


def test_text_within_its_length() -> None:
    assert value_of(TEXT, " fine ", DR) == [("urn:v:c", "fine")]
    assert isinstance(value_of(TEXT, "too long", DR), Failure)
    assert isinstance(value_of(TEXT, "  ", DR), Failure)


CONFIG = """
[model]
endpoint = "http://127.0.0.1:1/v1"
name = "m"
timeout = 5
[run]
mode = "interview"
respondents = 1
system = "You answer surveys."
missing = ["D"]
no_answer = "N"
draw = ["county"]
[inputs]
year = 2009
[prompts]
"urn:ddi:a:q:1" = "Extra."
"""


def config(text: str = CONFIG) -> Config:
    c = parse(text)
    assert isinstance(c, Config), c
    return c


class Script:
    """qretools next as a list of replies, keeping each state it was sent."""

    def __init__(self, *steps: Mapping[str, Any]) -> None:
        self.steps = list(steps)
        self.states: list[State] = []

    def __call__(self, state: State) -> Mapping[str, Any] | Refused:
        self.states.append(json.loads(json.dumps(state)))
        return self.steps.pop(0)


class Model:
    """The model as a list of reply texts, keeping each call's messages and seed."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[tuple[list[dict[str, str]], int]] = []

    def __call__(self, messages: Sequence[Mapping[str, str]], seed: int) -> Reply:
        self.calls.append(([dict(m) for m in messages], seed))
        return Reply(self.texts.pop(0), "stop", "served", "b1", {}, {"timings": {}})


END = {"kind": "end", "how": "end", "statements": [], "notes": []}


def run(
    script: Script, model: Model, c: Config | None = None
) -> tuple[State | Refused, list[Trace]]:
    traces: list[Trace] = []
    state = interview("1", 7, c or config(), script, model, traces.append)
    return state, traces


def test_an_interview_answers_until_the_end() -> None:
    script = Script(ask(CHOICE), ask(NUMBER, row=2), END)
    model = Model("1", "40")
    state, traces = run(script, model)
    assert state == {
        "inputs": {},
        "answers": [
            {"variable": "urn:v:tenure", "value": "1"},
            {"variable": "urn:v:hours", "row": 2, "value": 40},
        ],
    }
    # Interview mode: the second call holds the first question and its answer.
    messages, seed = model.calls[1]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert seed == 7
    assert "Extra." in messages[1]["content"]
    assert [t["kind"] for t in traces] == ["call", "call"]
    assert traces[1]["row"] == 2


def test_a_reply_not_allowed_is_asked_again_then_given_up() -> None:
    script = Script(ask(CHOICE), END)
    model = Model(*["maybe"] * (RETRIES + 1))
    state, traces = run(script, model)
    assert not isinstance(state, Refused)
    assert state["answers"] == [{"variable": "urn:v:tenure", "value": "N"}]
    assert len(model.calls) == RETRIES + 1
    assert [t["kind"] for t in traces][-1] == "no_answer"
    assert all("failure" in t for t in traces if t["kind"] == "call")


def test_a_problem_replaces_the_answer_qretools_did_not_take() -> None:
    script = Script(ask(SELECT), ask(SELECT, problem="Pick at least one."), END)
    model = Model("none", "a")
    state, _ = run(script, model)
    assert script.states[1]["answers"] == [
        {"variable": "urn:v:oa", "value": "0"},
        {"variable": "urn:v:ob", "value": "0"},
    ]
    assert state == {
        "inputs": {},
        "answers": [
            {"variable": "urn:v:oa", "value": "1"},
            {"variable": "urn:v:ob", "value": "0"},
        ],
    }
    assert model.calls[1][0][-1]["content"].startswith(
        "That answer can't be taken: Pick at least one."
    )


def test_a_problem_after_no_answer_stops_the_interview() -> None:
    problem = ask(CHOICE, problem="Answer it.")
    script = Script(ask(CHOICE), problem, problem, problem, problem, END)
    state, _ = run(script, Model("1", "1", "1"))
    assert isinstance(state, Refused)
    assert "no_answer" in state.reason


def test_inputs_come_from_the_config_or_are_drawn_or_are_null() -> None:
    def needs(name: str, domain: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "kind": "input",
            "name": name,
            "variable": "urn:i",
            "domain": domain,
            "missing": MISSING,
            "notes": [],
        }

    county = {
        "kind": "choice",
        "choices": [{"code": "1", "label": "N"}, {"code": "2", "label": "S"}],
    }
    script = Script(
        needs("year", {"kind": "number", "decimals": 0}),
        needs("county", county),
        needs("job", {"kind": "text"}),
        END,
    )
    state, traces = run(script, Model())
    assert not isinstance(state, Refused)
    assert state["inputs"]["year"] == 2009
    assert state["inputs"]["county"] in {"1", "2"}
    assert state["inputs"]["job"] is None
    assert [t["how"] for t in traces] == ["config", "drawn", "not in the config"]
    # The draw is the respondent's seed's: the same seed, the same county.
    again, _ = run(Script(needs("county", county), END), Model())
    assert not isinstance(again, Refused)
    assert again["inputs"]["county"] == state["inputs"]["county"]


def test_no_answer_must_be_a_missing_code_of_the_variable() -> None:
    domain = {**CHOICE, "missing": MISSING[:1]}
    state, _ = run(Script(ask(domain)), Model())
    assert isinstance(state, Refused)
    assert "no missing code N" in state.reason


def test_a_refused_call_names_the_respondent_and_the_step() -> None:
    def down(messages: Sequence[Mapping[str, str]], seed: int) -> Refused:
        return Refused("The model server answered 400.")

    state = interview("3", 1, config(), Script(ask(CHOICE)), down, lambda t: None)
    assert isinstance(state, Refused)
    assert state.reason.startswith("respondent 3, urn:step:tenure: ")


def test_a_missing_code_is_a_whole_reply_where_words_and_numbers_are_answers() -> None:
    # "D.C." is a place, not the missing code D; 98 is a number, not the code 98.
    assert value_of({**TEXT, "maxLength": 10}, "D.C.", DR) == [("urn:v:c", "D.C.")]
    assert value_of(TEXT, "D", DR) == [("urn:v:c", "D")]
    numeric = {**NUMBER, "missing": [{"code": "98", "label": "Don't know"}]}
    assert value_of(numeric, "98 hours", frozenset({"98"})) == [("urn:v:hours", 98)]
    assert value_of(numeric, "Don't know", frozenset({"98"})) == [("urn:v:hours", "98")]


def test_no_answer_after_a_problem_says_the_problem() -> None:
    script = Script(
        ask(CHOICE),
        ask(CHOICE, problem="Not that one."),
        ask(CHOICE, problem="Not that one."),
        ask(CHOICE, problem="Not that one."),
        END,
    )
    state, traces = run(script, Model("1", "1", "1"))
    assert not isinstance(state, Refused)
    assert traces[-1]["kind"] == "no_answer"
    assert traces[-1]["problem"] == "Not that one."
