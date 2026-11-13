"""The only module that opens a network connection: a client for an OpenAI-compatible
chat server, such as llama.cpp's.

Every function returns a value. Nothing here raises for a failed request.
"""

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from qretools_harness.config import Model
from qretools_harness.qretools import Refused

# How much of an error reply goes into a refusal: llama.cpp explains itself in the body.
DETAIL = 500


@dataclass(frozen=True)
class Unreachable(Refused):
    """The server gave no answer at all: every later call would fail the same way."""


@dataclass(frozen=True)
class Reply:
    """What the server answered, and what it says about itself."""

    text: str
    finish_reason: str | None  # "length" means max_tokens cut the reply off
    model: str | None  # the model the server says it served
    fingerprint: str | None  # `system_fingerprint`: the server's build, if it says
    usage: Mapping[str, object]
    body: Mapping[str, object]  # the whole reply, for the trace
    server: str | None = None  # the HTTP `Server` header: the server's software


def reply_of(body: object, server: str | None = None) -> Reply | Refused:
    """A Reply from the JSON body of `/chat/completions`, or why it isn't one."""
    if not isinstance(body, dict):
        return Refused("The model server's reply isn't a JSON object.")
    choices = body.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(first, dict):
        return Refused("The model server's reply has no choices.")
    message = first.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        return Refused(
            "The model server's reply has no text in its first choice"
            " (a tool call, or reasoning only?)."
        )

    def optional(value: object) -> str | None:
        return value if isinstance(value, str) else None

    usage = body.get("usage")
    return Reply(
        text=text,
        finish_reason=optional(first.get("finish_reason")),
        model=optional(body.get("model")),
        fingerprint=optional(body.get("system_fingerprint")),
        usage=usage if isinstance(usage, dict) else {},
        body=body,
        server=server,
    )


def detail_of(error: urllib.error.HTTPError) -> str:
    """The start of an error reply's body, on a line of its own; empty if it has none."""
    try:
        with error:
            detail = error.read().decode(errors="replace").strip()[:DETAIL]
    except OSError:
        return ""
    return f"\n{detail}" if detail else ""


def complete(
    model: Model,
    generation: Mapping[str, object],
    messages: Sequence[Mapping[str, str]],
) -> Reply | Refused:
    """POST `messages` to `<endpoint>/chat/completions` with the generation settings."""
    url = f"{model.endpoint}/chat/completions"
    payload = {
        **generation,
        "model": model.name,
        "messages": [dict(m) for m in messages],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    got = fetch(request, model.timeout)
    if isinstance(got, Refused):
        return got
    raw, server = got
    try:
        return reply_of(json.loads(raw), server)
    except ValueError:
        return Refused(f"The model server at {url} didn't reply with JSON.")


def fetch(
    request: urllib.request.Request, timeout: float
) -> tuple[bytes, str | None] | Refused:
    """The body of the reply to `request`, and its `Server` header."""
    url = request.full_url
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), (
                response.headers.get("Server") or ""
            ).strip() or None
    except urllib.error.HTTPError as error:
        return Refused(
            f"The model server at {url} answered {error.code}." + detail_of(error)
        )
    except TimeoutError:
        return Unreachable(f"The model server at {url} gave no reply in {timeout}s.")
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):  # a connect that timed out
            return Unreachable(
                f"The model server at {url} gave no reply in {timeout}s."
            )
        return Unreachable(f"Can't reach the model server at {url}: {error.reason}.")
    except OSError as error:
        return Unreachable(f"Can't reach the model server at {url}: {error}.")
    except http.client.HTTPException as error:  # not an OSError: not HTTP
        return Unreachable(
            f"The model server at {url} didn't answer as HTTP: {error!r}."
        )


# A launch argument or setting whose value is a secret: it never goes into a trace.
SECRET = re.compile(r"key|token|secret|password", re.IGNORECASE)
SHORT_SECRETS = frozenset({"-hft"})  # llama.cpp's short form of --hf-token


def _secret(name: str) -> bool:
    return name in SHORT_SECRETS or bool(SECRET.search(name))


def redacted(value: object) -> object:
    """`value` with every secret replaced: the argument after `--api-key` and the like,
    `--api-key=x`, an `api-key = x` line of a preset, and a value whose key names one."""
    if isinstance(value, list):
        out: list[object] = []
        for i, arg in enumerate(value):
            before = value[i - 1] if i else None
            if isinstance(before, str) and before.startswith("-") and _secret(before):
                out.append("<redacted>")
            elif isinstance(arg, str) and arg.startswith("-") and "=" in arg:
                flag = arg.split("=")[0]
                out.append(f"{flag}=<redacted>" if _secret(flag) else arg)
            else:
                out.append(redacted(arg))
        return out
    if isinstance(value, dict):
        return {
            k: "<redacted>" if _secret(str(k)) else redacted(v)
            for k, v in value.items()
        }
    if isinstance(value, str) and "=" in value:
        return "\n".join(
            f"{line.split('=')[0]}= <redacted>"
            if "=" in line and _secret(line.split("=")[0].strip())
            else line
            for line in value.split("\n")
        )
    return value


# Long enough for a router to load the model; a hung server shouldn't hold up the run.
INFO_TIMEOUT = 60.0


def server_info(model: Model) -> dict[str, object]:
    """What the server says about itself and the model, for the record: llama.cpp's
    `/props?model=` (its build, context size, sampler defaults, chat template) and the
    model's entry in `/v1/models` (its launch arguments, secrets redacted). A server
    that has neither is recorded as such: nothing here stops a run."""
    root = urllib.parse.urlsplit(model.endpoint)
    props_url = urllib.parse.urlunsplit(
        (
            root.scheme,
            root.netloc,
            "/props",
            urllib.parse.urlencode({"model": model.name}),
            "",
        )
    )
    info: dict[str, object] = {}
    for key, url in (("props", props_url), ("models", f"{model.endpoint}/models")):
        got = fetch(urllib.request.Request(url), min(model.timeout, INFO_TIMEOUT))
        if isinstance(got, Refused):
            info[key] = {"unavailable": got.reason}
            continue
        raw, server = got
        info.setdefault("server", server)
        try:
            body = json.loads(raw)
        except ValueError:
            info[key] = {"unavailable": f"{url} didn't reply with JSON."}
            continue
        if key == "models":
            data = body.get("data") if isinstance(body, dict) else None
            entries = [
                m
                for m in data or []
                if isinstance(m, dict) and m.get("id") == model.name
            ]
            body = (
                entries[0]
                if entries
                else {"unavailable": f"{url} doesn't list {model.name}."}
            )
        info[key] = redacted(body)
    return info
