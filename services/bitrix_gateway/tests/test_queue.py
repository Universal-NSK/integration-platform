import asyncio
from datetime import datetime, timezone

import pytest
from bitrix_gateway.contracts.models import GatewayRequest, RetryPolicy
from bitrix_gateway.dispatch.job import GatewayJob
from bitrix_gateway.dispatch.queue import InMemoryJobQueue, JobQueue, QueueFullError


def _job(identifier: str) -> GatewayJob:
    return GatewayJob(
        id=identifier,
        request=GatewayRequest(
            method=f"crm.item.{identifier}",
            payload={"id": identifier},
            retry_policy=RetryPolicy.SAFE,
        ),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("max_size", [0, -1])
def test_max_size_must_be_positive(max_size: int) -> None:
    with pytest.raises(ValueError, match="max_size"):
        InMemoryJobQueue(max_size=max_size)


def test_enqueue_and_dequeue_are_fifo_and_report_current_size() -> None:
    async def scenario() -> None:
        queue: JobQueue = InMemoryJobQueue(max_size=2)
        first = _job("first")
        second = _job("second")

        assert queue.size() == 0
        queue.enqueue(first)
        queue.enqueue(second)
        assert queue.size() == 2
        assert await queue.dequeue() == first
        assert queue.size() == 1
        assert await queue.dequeue() == second
        assert queue.size() == 0

    asyncio.run(scenario())


def test_enqueue_raises_public_error_when_queue_is_full() -> None:
    async def scenario() -> None:
        queue = InMemoryJobQueue(max_size=1)
        accepted = _job("accepted")
        queue.enqueue(accepted)

        with pytest.raises(QueueFullError, match="full"):
            queue.enqueue(_job("rejected"))

        assert queue.size() == 1

    asyncio.run(scenario())


def test_dequeue_waits_until_a_job_is_enqueued() -> None:
    async def scenario() -> None:
        queue = InMemoryJobQueue(max_size=1)
        dequeue_started = asyncio.Event()

        async def dequeue() -> GatewayJob:
            dequeue_started.set()
            return await queue.dequeue()

        waiting_dequeue = asyncio.create_task(dequeue())
        await dequeue_started.wait()
        assert not waiting_dequeue.done()

        job = _job("ready")
        queue.enqueue(job)
        assert await waiting_dequeue == job

    asyncio.run(scenario())
