"""`python -m mazzamurello_netguard` keeps the egress table; `... check` is its health check (ADR-0053)."""

from __future__ import annotations

import sys

from mazzamurello_netguard.guard import healthy, run


def main(argv: list[str]) -> int:
    if argv == ["check"]:
        return 0 if healthy() else 1
    if argv:
        print(f"usage: python -m mazzamurello_netguard [check], not {' '.join(argv)}", file=sys.stderr)
        return 2
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
