"""Tests against real tools, each run only when asked.

The chat runs when QRETOOLS_HARNESS_MODEL_URL gives a model server's base URL."""

import os

import pytest

from qretools_harness.chat import Reply, complete
from qretools_harness.config import Model

MODEL_URL = os.environ.get("QRETOOLS_HARNESS_MODEL_URL")
MODEL_NAME = os.environ.get("QRETOOLS_HARNESS_MODEL", "")


@pytest.mark.skipif(
    not MODEL_URL,
    reason="needs QRETOOLS_HARNESS_MODEL_URL (and QRETOOLS_HARNESS_MODEL)",
)
def test_a_live_server_replies() -> None:
    assert MODEL_URL
    model = Model(MODEL_URL.rstrip("/"), MODEL_NAME, 300)
    reply = complete(
        model, {"max_tokens": 8, "seed": 1}, [{"role": "user", "content": "Say yes."}]
    )
    assert isinstance(reply, Reply), reply
    assert reply.text
