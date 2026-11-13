"""The client against a local stand-in for a model server: no network."""

import json
import socket
import threading
from types import MappingProxyType

import pytest
from fake import GOOD, Handler, Server

from qretools_harness.chat import (
    Reply,
    Unreachable,
    complete,
    redacted,
    reply_of,
    server_info,
)
from qretools_harness.config import Model
from qretools_harness.qretools import Refused


def model_at(s: Server, timeout: float = 5) -> Model:
    return Model(f"http://127.0.0.1:{s.server_address[1]}/v1", "asked-model", timeout)


MESSAGES = [{"role": "user", "content": "Say yes."}]


def test_the_request_and_the_reply(server: Server) -> None:
    reply = complete(model_at(server), {"seed": 1, "top_k": 40}, MESSAGES)
    assert reply == Reply(
        text="Yes",
        finish_reason="length",
        model="served-model",
        fingerprint="b12110-cd959bae9",
        usage={"prompt_tokens": 13, "completion_tokens": 1},
        body=GOOD,
        server="fake-server",
    )
    [(path, body)] = server.received
    assert path == "/v1/chat/completions"
    assert body == {
        "seed": 1,
        "top_k": 40,
        "model": "asked-model",
        "messages": MESSAGES,
    }


def test_an_error_reply_says_what_the_server_said(server: Server) -> None:
    server.status = 500
    server.body = b'{"error": {"message": "model not loaded"}}'
    reply = complete(model_at(server), {}, MESSAGES)
    assert isinstance(reply, Refused)
    assert "answered 500" in reply.reason
    assert "model not loaded" in reply.reason


def test_a_slow_server_times_out(server: Server) -> None:
    server.delay = 1
    reply = complete(model_at(server, timeout=0.2), {}, MESSAGES)
    assert isinstance(reply, Refused)
    assert "no reply in 0.2s" in reply.reason


def test_a_reply_that_isnt_json_is_refused(server: Server) -> None:
    server.body = b"<html>"
    reply = complete(model_at(server), {}, MESSAGES)
    assert isinstance(reply, Refused)
    assert "didn't reply with JSON" in reply.reason


def test_no_server_is_refused() -> None:
    s = Server(("127.0.0.1", 0), Handler)
    model = model_at(s)
    s.server_close()  # nothing listens on the port now
    reply = complete(model, {}, MESSAGES)
    assert isinstance(reply, Refused)
    assert "Can't reach" in reply.reason


def test_a_server_that_isnt_http_is_refused() -> None:
    listener = socket.create_server(("127.0.0.1", 0))

    def banner() -> None:
        connection, _ = listener.accept()
        with connection:
            connection.sendall(b"SSH-2.0-OpenSSH_9.9\r\n")
            # Read until the client closes: closing first can break its send (EPIPE).
            while connection.recv(4096):
                pass

    thread = threading.Thread(target=banner, daemon=True)
    thread.start()
    port = listener.getsockname()[1]
    reply = complete(Model(f"http://127.0.0.1:{port}/v1", "m", 5), {}, MESSAGES)
    thread.join()
    listener.close()
    assert isinstance(reply, Refused)
    assert "didn't answer as HTTP" in reply.reason


def test_messages_may_be_any_mapping(server: Server) -> None:
    reply = complete(model_at(server), {}, [MappingProxyType(MESSAGES[0])])
    assert isinstance(reply, Reply)
    assert server.received[0][1] == {"model": "asked-model", "messages": MESSAGES}


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None, "reasoning_content": "hm"}}]},
    ],
)
def test_a_reply_without_text_is_refused(body: object) -> None:
    assert isinstance(reply_of(body), Refused)


def test_what_the_server_doesnt_say_is_none() -> None:
    reply = reply_of({"choices": [{"message": {"content": ""}}]})
    assert isinstance(reply, Reply)
    assert (reply.model, reply.fingerprint, reply.finish_reason) == (None, None, None)
    assert reply.usage == {}


def test_server_info_records_props_and_the_models_launch_arguments(
    server: Server,
) -> None:
    model = model_at(server)
    server.pages = {
        "/props?model=asked-model": {"build_info": "b9", "n_ctx": 8192},
        "/v1/models": {
            "data": [
                {"id": "other"},
                {
                    "id": "asked-model",
                    "status": {
                        "args": [
                            "--ctx-size",
                            "8192",
                            "--api-key",
                            "s3",
                            "--hf-token=t",
                        ],
                        "preset": "ctx-size = 8192\napi-key = s3\n",
                    },
                },
            ]
        },
    }
    info = server_info(model)
    assert info["server"] == "fake-server"
    assert info["props"] == {"build_info": "b9", "n_ctx": 8192}
    assert info["models"] == {
        "id": "asked-model",
        "status": {
            "args": [
                "--ctx-size",
                "8192",
                "--api-key",
                "<redacted>",
                "--hf-token=<redacted>",
            ],
            "preset": "ctx-size = 8192\napi-key = <redacted>\n",
        },
    }
    assert "s3" not in json.dumps(info)


def test_a_server_without_props_is_recorded_not_refused(server: Server) -> None:
    info = server_info(model_at(server))
    assert "404" in str(info["props"])
    assert "unavailable" in str(info["models"])


def test_a_server_that_isnt_there_is_unreachable() -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    reply = complete(Model(f"http://127.0.0.1:{port}/v1", "m", 5), {}, MESSAGES)
    assert isinstance(reply, Unreachable)


def test_redaction_covers_keys_short_flags_and_one_line_presets() -> None:
    assert redacted({"api_key": "x", "n_ctx": 8192}) == {
        "api_key": "<redacted>",
        "n_ctx": 8192,
    }
    assert redacted(["-hft", "t", "-c", "8192"]) == ["-hft", "<redacted>", "-c", "8192"]
    assert redacted("api-key = x") == "api-key = <redacted>"
    assert redacted("model = /m.gguf") == "model = /m.gguf"
