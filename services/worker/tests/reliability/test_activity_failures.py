from __future__ import annotations

import ast
import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

ATTEMPTS: dict[str, int] = {}


def test_workflow_module_has_no_external_provider_or_http_imports() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / "app" / "workflow.py"
    tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    forbidden = {
        name
        for name in imports
        if name == "httpx"
        or ".integrations" in name
        or name.startswith("services.api.app.providers")
    }
    assert forbidden == set()


@activity.defn(name="phase4.retry_probe")
async def retry_probe(mode: str) -> str:
    ATTEMPTS[mode] = ATTEMPTS.get(mode, 0) + 1
    if mode == "transient" and ATTEMPTS[mode] < 3:
        raise ApplicationError("transient provider read failure", type="TRANSIENT")
    if mode == "timeout":
        await asyncio.sleep(0.05)
    if mode == "submission":
        raise ApplicationError("submission outcome unknown", type="SUBMISSION_UNCERTAIN")
    return "ok"


@workflow.defn(name="phase4.retry_probe_workflow")
class RetryProbeWorkflow:
    @workflow.run
    async def run(self, mode: str) -> str:
        provider_submission = mode == "submission"
        result = await workflow.execute_activity(
            "phase4.retry_probe",
            mode,
            result_type=str,
            start_to_close_timeout=timedelta(milliseconds=10 if mode == "timeout" else 500),
            retry_policy=RetryPolicy(
                maximum_attempts=1 if provider_submission else 3,
                initial_interval=timedelta(milliseconds=5),
                maximum_interval=timedelta(milliseconds=10),
                backoff_coefficient=1.0,
            ),
        )
        return str(result)


@pytest.mark.asyncio
async def test_retryable_activity_recovers_on_third_attempt() -> None:
    ATTEMPTS.clear()
    async with (
        await WorkflowEnvironment.start_time_skipping() as environment,
        Worker(
            environment.client,
            task_queue="phase4-transient",
            workflows=[RetryProbeWorkflow],
            activities=[retry_probe],
        ),
    ):
        result = await environment.client.execute_workflow(
            RetryProbeWorkflow.run,
            "transient",
            id="phase4-transient",
            task_queue="phase4-transient",
        )
    assert result == "ok"
    assert ATTEMPTS["transient"] == 3


@pytest.mark.asyncio
async def test_activity_timeout_stops_after_bounded_retry_count() -> None:
    ATTEMPTS.clear()
    async with (
        await WorkflowEnvironment.start_time_skipping() as environment,
        Worker(
            environment.client,
            task_queue="phase4-timeout",
            workflows=[RetryProbeWorkflow],
            activities=[retry_probe],
        ),
    ):
        with pytest.raises(WorkflowFailureError):
            await environment.client.execute_workflow(
                RetryProbeWorkflow.run,
                "timeout",
                id="phase4-timeout",
                task_queue="phase4-timeout",
            )
    assert ATTEMPTS["timeout"] == 3


@pytest.mark.asyncio
async def test_uncertain_provider_submission_is_attempted_exactly_once() -> None:
    ATTEMPTS.clear()
    async with (
        await WorkflowEnvironment.start_time_skipping() as environment,
        Worker(
            environment.client,
            task_queue="phase4-submission",
            workflows=[RetryProbeWorkflow],
            activities=[retry_probe],
        ),
    ):
        with pytest.raises(WorkflowFailureError):
            await environment.client.execute_workflow(
                RetryProbeWorkflow.run,
                "submission",
                id="phase4-submission",
                task_queue="phase4-submission",
            )
    assert ATTEMPTS["submission"] == 1
