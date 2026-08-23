from __future__ import annotations

import asyncio
from typing import Any, List, Tuple

import pytest
from bitrix_gateway.contracts.models import (
    ExecutionStatus,
    GatewayRequest,
    GatewayResult,
    RetryPolicy,
)
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.job import GatewayJob
from bitrix_gateway.dispatch.queue import InMemoryJobQueue, QueueFullError
from bitrix_gateway.execution.executor import RequestExecutor


class SignallingQueue(InMemoryJobQueue):
    def __init__(self, max_size: int) -> None:
        super().__init__(max_size=max_size)
        self.enqueued: asyncio.Queue[GatewayJob] = asyncio.Queue()

    def enqueue(self, job: GatewayJob) -> None:
        super().enqueue(job)
        self.enqueued.put_nowait(job)


class ControlledExecutor(RequestExecutor):
    def __init__(self) -> None:
        self.calls: List[GatewayRequest] = []
        self.started: asyncio.Queue[Tuple[GatewayRequest, asyncio.Future[GatewayResult]]] = (
            asyncio.Queue()
        )

    async def execute(self, request: GatewayRequest) -> GatewayResult:
        completion: asyncio.Future[GatewayResult] = asyncio.get_running_loop().create_future()
        self.calls.append(request)
        self.started.put_nowait((request, completion))
        return await completion


class FatalExecutorError(BaseException):
    pass


def _request(name: str) -> GatewayRequest:
    return GatewayRequest(
        method=f"crm.item.{name}",
        payload={"name": name},
        retry_policy=RetryPolicy.SAFE,
    )


def _result(name: str) -> GatewayResult:
    return GatewayResult(
        status=ExecutionStatus.SUCCESS,
        data={"name": name},
        http_status=200,
        error_code=None,
        error_message=None,
        attempt_count=1,
    )


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_submit_queues_and_waits_until_run_returns_executor_result() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=2)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        request = _request("one")
        expected = _result("one")

        submitted = asyncio.create_task(dispatcher.submit(request))
        enqueued_job = await queue.enqueued.get()

        assert enqueued_job.request is request
        assert executor.calls == []
        assert not submitted.done()
        assert dispatcher.queue_size() == 1

        worker = asyncio.create_task(dispatcher.run())
        try:
            executed_request, completion = await executor.started.get()
            assert executed_request is request

            completion.set_result(expected)

            assert await submitted == expected
            assert dispatcher.queue_size() == 0
            assert not worker.done()
        finally:
            await _cancel(worker)

    asyncio.run(scenario())


def test_single_run_executes_concurrent_submissions_sequentially_in_fifo_order() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=3)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        requests = [_request("first"), _request("second"), _request("third")]
        expected = [_result("first"), _result("second"), _result("third")]
        submissions: List[asyncio.Task[GatewayResult]] = []

        for request in requests:
            submissions.append(asyncio.create_task(dispatcher.submit(request)))
            enqueued_job = await queue.enqueued.get()
            assert enqueued_job.request is request

        assert dispatcher.queue_size() == 3

        worker = asyncio.create_task(dispatcher.run())
        try:
            for index, request in enumerate(requests):
                executed_request, completion = await executor.started.get()

                assert executed_request is request
                assert executor.calls == requests[: index + 1]
                assert executor.started.empty()

                completion.set_result(expected[index])

            assert await asyncio.gather(*submissions) == expected
            assert dispatcher.queue_size() == 0
            assert not worker.done()
        finally:
            await _cancel(worker)

    asyncio.run(scenario())


def test_cancelled_queued_submission_is_skipped_and_worker_continues() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=2)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        cancelled_request = _request("cancelled")
        next_request = _request("next")

        cancelled_submission = asyncio.create_task(dispatcher.submit(cancelled_request))
        await queue.enqueued.get()
        await _cancel(cancelled_submission)

        next_submission = asyncio.create_task(dispatcher.submit(next_request))
        await queue.enqueued.get()

        worker = asyncio.create_task(dispatcher.run())
        try:
            executed_request, completion = await executor.started.get()

            assert executed_request is next_request
            assert executor.calls == [next_request]

            expected = _result("next")
            completion.set_result(expected)

            assert await next_submission == expected
            assert not worker.done()
        finally:
            await _cancel(worker)

    asyncio.run(scenario())


def test_cancelling_submit_after_execution_starts_does_not_cancel_execution() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=2)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        first_request = _request("first")
        second_request = _request("second")

        first_submission = asyncio.create_task(dispatcher.submit(first_request))
        await queue.enqueued.get()
        worker = asyncio.create_task(dispatcher.run())

        try:
            executed_first, first_completion = await executor.started.get()
            assert executed_first is first_request

            await _cancel(first_submission)

            assert not first_completion.cancelled()

            second_submission = asyncio.create_task(dispatcher.submit(second_request))
            await queue.enqueued.get()

            assert executor.calls == [first_request]

            first_completion.set_result(_result("first"))
            executed_second, second_completion = await executor.started.get()

            assert executed_second is second_request
            assert executor.calls == [first_request, second_request]

            expected_second = _result("second")
            second_completion.set_result(expected_second)

            assert await second_submission == expected_second
            assert not worker.done()
        finally:
            await _cancel(worker)

    asyncio.run(scenario())


def test_job_exception_reaches_submit_but_worker_processes_next_job() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=2)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        failed_request = _request("failed")
        next_request = _request("next")

        failed_submission = asyncio.create_task(dispatcher.submit(failed_request))
        await queue.enqueued.get()
        next_submission = asyncio.create_task(dispatcher.submit(next_request))
        await queue.enqueued.get()

        worker = asyncio.create_task(dispatcher.run())
        try:
            executed_failed, failed_completion = await executor.started.get()
            assert executed_failed is failed_request

            failed_completion.set_exception(RuntimeError("executor failed"))

            with pytest.raises(RuntimeError, match="executor failed"):
                await failed_submission

            executed_next, next_completion = await executor.started.get()
            assert executed_next is next_request

            expected_next = _result("next")
            next_completion.set_result(expected_next)

            assert await next_submission == expected_next
            assert not worker.done()
        finally:
            await _cancel(worker)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fatal_error",
    [asyncio.CancelledError(), FatalExecutorError("fatal executor failure")],
)
def test_base_exceptions_from_executor_are_not_treated_as_job_errors(
    fatal_error: BaseException,
) -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=1)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)
        submission = asyncio.create_task(dispatcher.submit(_request("fatal")))
        await queue.enqueued.get()
        worker = asyncio.create_task(dispatcher.run())

        _, completion = await executor.started.get()
        completion.set_exception(fatal_error)

        try:
            with pytest.raises(type(fatal_error)):
                await worker

            assert not submission.done()
        finally:
            await _cancel(submission)

    asyncio.run(scenario())


def test_submit_raises_queue_full_without_waiting_for_a_result() -> None:
    async def scenario() -> None:
        queue = SignallingQueue(max_size=1)
        executor = ControlledExecutor()
        dispatcher = RequestDispatcher(queue=queue, executor=executor)

        accepted = asyncio.create_task(dispatcher.submit(_request("accepted")))
        await queue.enqueued.get()

        try:
            with pytest.raises(QueueFullError, match="full"):
                await dispatcher.submit(_request("rejected"))

            assert not accepted.done()
            assert dispatcher.queue_size() == 1
            assert executor.calls == []
        finally:
            await _cancel(accepted)

    asyncio.run(scenario())
