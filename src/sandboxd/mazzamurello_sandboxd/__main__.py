"""`python -m mazzamurello_sandboxd`: the sandbox driver (ADR-0022, ADR-0053)."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from mazzamurello_sandboxd.app import create_app
from mazzamurello_sandboxd.config import ConfigurationError, load_configuration


def main() -> int:
    try:
        configuration = load_configuration(os.environ)
    except ConfigurationError as error:
        print(f"mazzamurello-sandboxd: configuration error: {error}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(configuration),
        host=configuration.host,
        port=configuration.port,
        proxy_headers=False,
        server_header=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
