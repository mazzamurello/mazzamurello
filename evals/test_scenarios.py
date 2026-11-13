"""Every scenario against every model of the models file (EVL-001, EVL-002, EVL-003, ADR-0092)."""

from __future__ import annotations

import dataclasses

import pytest

from evals.harness import ModelUnderEvaluation, Outcome, Player
from evals.scenarios import Scenario


def test_scenario(
    evaluation: tuple[ModelUnderEvaluation, Scenario, int], player: Player, outcomes: list[Outcome]
) -> None:
    model, scenario, attempt = evaluation
    outcome = dataclasses.replace(player.play(scenario, model), attempt=attempt)
    outcomes.append(outcome)
    if not outcome.passed:
        pytest.fail("\n".join(f"- {check}" for check in outcome.failed_checks), pytrace=False)
