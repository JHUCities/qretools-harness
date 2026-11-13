import threading
from collections.abc import Iterator

import pytest
from fake import Handler, Server


@pytest.fixture
def server() -> Iterator[Server]:
    s = Server(("127.0.0.1", 0), Handler)
    s.received = []
    thread = threading.Thread(target=s.serve_forever, daemon=True)
    thread.start()
    yield s
    s.shutdown()
    s.server_close()
