"""`python -m sibillo_sandboxd`: the sandbox driver (ADR-0022, ADR-0053)."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from sibillo_sandboxd.app import create_app
from sibillo_sandboxd.config import ConfigurationError, load_configuration


def main() -> int:
    try:
        configuration = load_configuration(os.environ)
    except ConfigurationError as error:
        print(f"sibillo-sandboxd: configuration error: {error}", file=sys.stderr)
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
