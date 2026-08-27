"""Deterministic provider-failure scenarios for demos and contract tests."""

from .failure_scenarios import (
    FailureScenario,
    SimulatedDelivery,
    SimulationCase,
    build_failure_scenario,
)

__all__ = [
    "FailureScenario",
    "SimulatedDelivery",
    "SimulationCase",
    "build_failure_scenario",
]
