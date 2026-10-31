"""Command line entry points of the server: `python -m mazzamurello_server api` (ADR-0050)."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from mazzamurello_server.app import create_app
from mazzamurello_server.config import ConfigurationError, load_api_configuration


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mazzamurello_server")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api", help="run the public API")
    arguments = parser.parse_args(argv)
    if arguments.command == "api":
        return _api()
    parser.error(f"unknown command {arguments.command}")


if __name__ == "__main__":
    sys.exit(main())
