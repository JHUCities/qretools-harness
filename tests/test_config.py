from pathlib import Path

import pytest

from qretools_harness.config import Config, Urn, parse, stale
from qretools_harness.qretools import Refused

EXAMPLE = (Path(__file__).parent.parent / "examples/config.toml").read_text()

MINIMAL = """
[model]
endpoint = "http://127.0.0.1:9931/v1/"
name = "m"
timeout = 5
[run]
mode = "interview"
respondents = 1
system = "Answer."
"""


def parsed(text: str) -> Config:
    config = parse(text)
    assert isinstance(config, Config), config
    return config


def refused(text: str) -> str:
    config = parse(text)
    assert isinstance(config, Refused), config
    return config.reason


def test_the_example_parses() -> None:
    config = parsed(EXAMPLE)
    assert config.model.endpoint == "http://127.0.0.1:9931/v1"
    assert config.generation["top_k"] == 40  # passed through unread
    assert config.prompts == {
        Urn("us.jhu", "agekdbrn", "6"): "Answer with a whole number of years."
    }


def test_the_endpoint_loses_its_trailing_slash() -> None:
    config = parsed(MINIMAL)
    assert config.model.endpoint == "http://127.0.0.1:9931/v1"
    assert config.generation == {}
    assert config.prompts == {}


@pytest.mark.parametrize(
    ("text", "path"),
    [("colour = 1\n" + MINIMAL, "`colour`"), (MINIMAL + "[run.more]", "`run.more`")],
)
def test_unknown_keys_are_refused_by_path(text: str, path: str) -> None:
    assert path in refused(text)


def test_a_missing_key_is_named() -> None:
    assert "`model.timeout`" in refused(MINIMAL.replace("timeout = 5", ""))
    assert "`run`" in refused(MINIMAL.split("[run]")[0])


@pytest.mark.parametrize(
    "line",
    [
        "respondents = true",
        "respondents = 0",
        "respondents = 1.5",
        'mode = "survey"',
        'system = "  "',
    ],
)
def test_bad_run_values_are_refused(line: str) -> None:
    key = line.split(" =")[0]
    text = "\n".join(
        line if row.startswith(key + " =") else row for row in MINIMAL.splitlines()
    )
    assert f"run.{key}" in refused(text)


@pytest.mark.parametrize(
    "line",
    [
        "temperature = true",
        "temperature = nan",
        "max_tokens = 0",
        "seed = false",
        "model = 'x'",
        "stream = true",
        "n = 2",
        "when = 2026-11-12",
    ],
)
def test_bad_generation_values_are_refused(line: str) -> None:
    assert "generation." in refused(MINIMAL + "[generation]\n" + line)


def test_every_reserved_key_is_named() -> None:
    reason = refused(MINIMAL + "[generation]\nmodel = 'x'\nstream = true")
    assert "`generation.model`, `generation.stream`" in reason


def test_an_integer_temperature_is_a_number() -> None:
    assert parsed(MINIMAL + "[generation]\ntemperature = 1").generation == {
        "temperature": 1
    }


@pytest.mark.parametrize(
    "endpoint", ["ftp://host/v1", "127.0.0.1:9931/v1", "http://", ""]
)
def test_an_endpoint_must_be_http(endpoint: str) -> None:
    text = MINIMAL.replace("http://127.0.0.1:9931/v1/", endpoint)
    assert "model.endpoint" in refused(text)


def test_a_timeout_must_be_positive() -> None:
    assert "model.timeout" in refused(MINIMAL.replace("timeout = 5", "timeout = 0"))


@pytest.mark.parametrize(
    "key",
    ["urn:ddi:us.jhu:agekdbrn", "urn:ddi:us.jhu::6", "agekdbrn", "urn:ddi:a:b:c:6"],
)
def test_a_prompt_key_must_be_a_urn_with_its_version(key: str) -> None:
    assert "isn't a question's URN" in refused(MINIMAL + f'[prompts]\n"{key}" = "x"')


def test_the_urn_prefix_ignores_case() -> None:
    config = parsed(MINIMAL + '[prompts]\n"URN:DDI:us.jhu:x:1" = "x"')
    assert list(config.prompts) == [Urn("us.jhu", "x", "1")]


def test_two_spellings_of_one_urn_are_refused() -> None:
    text = MINIMAL + '[prompts]\n"urn:ddi:a:x:1" = "x"\n"URN:ddi:a:x:1" = "y"'
    assert "Two prompts" in refused(text)


def test_an_empty_prompt_is_refused() -> None:
    assert "prompts." in refused(MINIMAL + '[prompts]\n"urn:ddi:a:x:1" = ""')


def test_bad_toml_is_refused() -> None:
    assert "isn't TOML" in refused("[model")


def question(agency: str, id: str, version: str) -> dict[str, str]:
    urn = f"urn:ddi:{agency}:{id}:{version}"
    return {"URN": urn, "Agency": agency, "ID": id, "Version": version}


def ddi(*items: dict[str, str]) -> dict[str, object]:
    return {
        "QuestionItem": {f"{i['Agency']}:{i['ID']}:{i['Version']}": i for i in items},
        "Variable": {"us.jhu:gone:1": question("us.jhu", "gone", "1")},
    }


def with_prompts(*urns: str) -> Config:
    lines = "\n".join(f'"{u}" = "x"' for u in urns)
    return parsed(MINIMAL + "[prompts]\n" + lines)


def test_a_prompt_at_the_current_version_passes() -> None:
    config = with_prompts("urn:ddi:us.jhu:a:3")
    assert stale(config, ddi(question("us.jhu", "a", "3"))) is None


def test_a_changed_question_is_named() -> None:
    config = with_prompts("urn:ddi:us.jhu:a:2")
    assert stale(config, ddi(question("us.jhu", "a", "3"))) == Refused(
        "Question a changed since its prompt was written"
        " (prompt: version 2; instrument: 3); review it."
    )


def test_every_stale_prompt_is_reported() -> None:
    config = with_prompts("urn:ddi:us.jhu:a:2", "urn:ddi:us.jhu:gone:1")
    problem = stale(config, ddi(question("us.jhu", "a", "3")))
    assert problem is not None
    first, second = problem.reason.splitlines()
    assert "Question a changed" in first
    # Only questions count: a Variable with the name is not the question.
    assert "no question gone" in second


def test_the_agency_must_match() -> None:
    config = with_prompts("urn:ddi:other:a:3")
    assert stale(config, ddi(question("us.jhu", "a", "3"))) is not None


def test_one_of_several_versions_passes_and_all_are_listed_otherwise() -> None:
    both = ddi(question("us.jhu", "a", "3"), question("us.jhu", "a", "4"))
    assert stale(with_prompts("urn:ddi:us.jhu:a:3"), both) is None
    problem = stale(with_prompts("urn:ddi:us.jhu:a:1"), both)
    assert problem is not None
    assert "instrument: 3, 4" in problem.reason


@pytest.mark.parametrize(
    "doc", [[], {}, {"QuestionItem": []}, {"QuestionItem": {}}, {"model": {}}]
)
def test_a_file_without_questions_isnt_an_instrument(doc: object) -> None:
    # Even with no prompts to check: the wrong file must not pass.
    assert stale(parsed(MINIMAL), doc) == Refused(
        "This isn't an instrument's DDI: it has no QuestionItem."
    )


def test_an_item_that_isnt_an_object_is_skipped() -> None:
    problem = stale(with_prompts("urn:ddi:us.jhu:a:1"), {"QuestionItem": {"k": 1}})
    assert problem is not None
    assert "no question a" in problem.reason
