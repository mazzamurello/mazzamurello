"""Records the outbound connections of the processes the test harness starts (OBS-006, ADR-0072).

The harness puts this directory on `PYTHONPATH` and names a file in
`TEST_OUTBOUND_LOG`; Python imports `sitecustomize` when it starts, and the
audit hook below appends one JSON line per connection and per name lookup.
Unix sockets are local and not recorded.
"""

import json
import os
import sys
from typing import cast

_LOG = os.environ.get("TEST_OUTBOUND_LOG")


def _write(entry: dict[str, object]) -> None:
    line = (json.dumps(entry) + "\n").encode()
    descriptor = os.open(_LOG or os.devnull, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def _hook(event: str, args: tuple[object, ...]) -> None:
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple):
            host, port = cast(tuple[object, ...], address)[:2]
            _write({"connect": str(host), "port": port, "pid": os.getpid()})
    elif event == "socket.getaddrinfo":
        _write({"resolve": str(args[0]), "pid": os.getpid()})


if _LOG:
    sys.addaudithook(_hook)
