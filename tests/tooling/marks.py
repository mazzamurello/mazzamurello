"""The `spec` marker for tooling tests, which also run without pytest (REPO-004).

The Tooling tests job runs them with plain `unittest`, where the marker does
nothing; under pytest it is pytest's own, so traceability and the pending
gate see it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from pytest import mark
except ModuleNotFoundError:

    class _Marks:
        @staticmethod
        def spec(*_requirements: str) -> Callable[[Any], Any]:
            return lambda target: target

    mark = _Marks()  # type: ignore[assignment]

__all__ = ["mark"]
