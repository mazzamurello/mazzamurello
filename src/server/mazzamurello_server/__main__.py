"""Command line entry points of the server: `api` (ADR-0050), `worker` (ADR-0052), `init` and `setup` (ADR-0054)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from mazzamurello_server import operator_commands
from mazzamurello_server.app import create_app
from mazzamurello_server.config import ConfigurationError, load_api_configuration, load_worker_configuration


def _api() -> int:
    try:
        configuration = load_api_configuration(os.environ)
    except ConfigurationError as error:
        print(f"mazzamurello: configuration error: {error}", file=sys.stderr)
        return 2
    uvicorn.run(
        create_app(configuration),
        host=configuration.http_host,
        port=configuration.http_port,
        # The source address is derived from trusted proxies only (ADR-0050).
        proxy_headers=False,
        server_header=False,
        log_level="info",
    )
    return 0


def _worker() -> int:
    try:
        configuration = load_worker_configuration(os.environ)
    except ConfigurationError as error:
        print(f"mazzamurello: configuration error: {error}", file=sys.stderr)
        return 2
    # Imported here: only the worker registers workflows with DBOS.
    from mazzamurello_server.worker import run_worker

    run_worker(configuration)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mazzamurello_server")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api", help="run the public API")
    commands.add_parser("worker", help="execute runs")
    init = commands.add_parser("init", help="write a deployment's .env with fresh secrets")
    init.add_argument("--output", required=True, type=Path, help="the file to write; never overwritten")
    commands.add_parser("setup", help="create the first tenant and its administrator, once")
    arguments = parser.parse_args(argv)
    if arguments.command == "api":
        return _api()
    if arguments.command == "worker":
        return _worker()
    if arguments.command == "init":
        return operator_commands.init(arguments.output)
    if arguments.command == "setup":
        return operator_commands.setup(os.environ)
    parser.error(f"unknown command {arguments.command}")


if __name__ == "__main__":
    sys.exit(main())
