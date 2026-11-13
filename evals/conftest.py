"""The eval suite's runner: options, the models to evaluate, and the report (EVL-001, EVL-002, ADR-0092).

    uv run pytest evals --eval-models evals/models.toml [--eval-repeat N] [--eval-report DIR]

Every scenario runs `--eval-repeat` times against every model of the models
file, on the stack the tests start (specs/contracts/test-harness.md). The
terminal shows each scenario's pass rate per model; the JSON report holds
every run, with the transcript of each failed one.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest
from tests.support.database import Database
from tests.support.fixtures import database as database
from tests.support.fixtures import sandboxes as sandboxes
from tests.support.fixtures import search_service as search_service
from tests.support.fixtures import server as server
from tests.support.sandbox import Driver
from tests.support.search import SearchServer
from tests.support.server import Server

from evals.harness import ModelUnderEvaluation, Outcome, Player
from evals.scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
OUTCOMES = pytest.StashKey[list[Outcome]]()
REPEAT = 3


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals", "the eval suite (ADR-0092)")
    group.addoption("--eval-models", metavar="FILE", help="the models file to evaluate")
    group.addoption("--eval-repeat", type=int, default=REPEAT, metavar="N", help="runs of each scenario per model")
    group.addoption(
        "--eval-report", default=str(ROOT / "evals" / "results"), metavar="DIR", help="where the JSON report goes"
    )


def load_models(path: Path) -> list[ModelUnderEvaluation]:
    """The models of a models file; a key comes from the environment variable it names."""
    listed = cast(list[dict[str, Any]], tomllib.loads(path.read_text(encoding="utf-8")).get("model", []))
    models: list[ModelUnderEvaluation] = []
    for entry in listed:
        variable = entry.get("api_key_env")
        key = os.environ.get(str(variable)) if variable else None
        if variable and not key:
            raise pytest.UsageError(f"{path}: {entry.get('name')} needs its key in ${variable}")
        models.append(
            ModelUnderEvaluation(
                name=str(entry["name"]),
                kind=str(entry["kind"]),
                model=str(entry["model"]),
                base_url=entry.get("base_url"),
                location=entry.get("location"),
                api_key=key,
            )
        )
    if not models:
        raise pytest.UsageError(f"{path} names no model")
    return models


def pytest_configure(config: pytest.Config) -> None:
    config.stash[OUTCOMES] = []


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "evaluation" not in metafunc.fixturenames:
        return
    given = metafunc.config.getoption("--eval-models")
    models = load_models(Path(given)) if given else []
    repeat = max(1, cast(int, metafunc.config.getoption("--eval-repeat")))
    cases = [
        pytest.param((model, scenario, attempt), id=f"{model.name}-{scenario.name}-{attempt}")
        for model in models
        for scenario in SCENARIOS
        for attempt in range(1, repeat + 1)
    ]
    if not cases:
        cases = [pytest.param(None, marks=pytest.mark.skip(reason="no models: pass --eval-models FILE"))]
    metafunc.parametrize("evaluation", cases)


@pytest.fixture(scope="session")
def player(database: Database, server: Server, sandboxes: Driver, search_service: SearchServer) -> Player:
    return Player(database, server, sandboxes, search_service)


@pytest.fixture
def outcomes(request: pytest.FixtureRequest) -> list[Outcome]:
    return request.config.stash[OUTCOMES]


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, config: pytest.Config) -> None:
    outcomes = config.stash[OUTCOMES]
    if not outcomes:
        return
    terminalreporter.write_sep("=", "eval results (ADR-0092)")
    models = sorted({outcome.model for outcome in outcomes})
    width = max(len(scenario.name) for scenario in SCENARIOS) + 2
    terminalreporter.write_line("scenario".ljust(width) + "".join(model[:24].ljust(26) for model in models))
    for scenario in SCENARIOS:
        cells: list[str] = []
        for model in models:
            runs = [o for o in outcomes if o.model == model and o.scenario == scenario.name]
            if not runs:
                cells.append("-".ljust(26))
                continue
            passed = sum(o.passed for o in runs)
            # Every failed run of an adversarial scenario is flagged; LEAK/HARM when the agent did harm (EVL-003).
            mark = ""
            if any(o.harmed for o in runs):
                mark = "  LEAK/HARM"
            elif scenario.adversarial and passed < len(runs):
                mark = "  FLAGGED"
            cells.append(f"{passed}/{len(runs)}{mark}".ljust(26))
        terminalreporter.write_line(scenario.name.ljust(width) + "".join(cells))
    folder = Path(str(config.getoption("--eval-report")))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
    report = {"runs": [outcome.report() for outcome in outcomes]}
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    terminalreporter.write_line(f"report: {path}")
