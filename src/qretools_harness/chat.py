"""The only module that opens a network connection: a client for an OpenAI-compatible
chat server, such as llama.cpp's.

Every function returns a value. Nothing here raises for a failed request.
"""

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from qretools_harness.config import Model
from qretools_harness.qretools import Refused

# How much of an error reply goes into a refusal: llama.cpp explains itself in the body.
DETAIL = 500


@dataclass(frozen=True)
class Reply:
    """What the server answered, and what it says about itself."""

    text: str
    finish_reason: str | None  # "length" means max_tokens cut the reply off
    model: str | None  # the model the server says it served
    fingerprint: str | None  # `system_fingerprint`: the server's build, if it says
    usage: Mapping[str, object]
    body: Mapping[str, object]  # the whole reply, for the trace


def reply_of(body: object) -> Reply | Refused:
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
    try:
        with urllib.request.urlopen(request, timeout=model.timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        return Refused(
            f"The model server at {url} answered {error.code}." + detail_of(error)
        )
    except TimeoutError:
        return Refused(f"The model server at {url} gave no reply in {model.timeout}s.")
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):  # a connect that timed out
            return Refused(
                f"The model server at {url} gave no reply in {model.timeout}s."
            )
        return Refused(f"Can't reach the model server at {url}: {error.reason}.")
    except OSError as error:
        return Refused(f"Can't reach the model server at {url}: {error}.")
    except (
        http.client.HTTPException
    ) as error:  # not an OSError: a reply that isn't HTTP
        return Refused(f"The model server at {url} didn't answer as HTTP: {error!r}.")
    try:
        return reply_of(json.loads(raw))
    except ValueError:
        return Refused(f"The model server at {url} didn't reply with JSON.")
