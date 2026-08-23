from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from bitrix_gateway.contracts.models import (
    GatewayRequest,
    GatewayResult,
)
from bitrix_gateway.dispatch.job import GatewayJob
from bitrix_gateway.dispatch.queue import JobQueue
from bitrix_gateway.execution.executor import RequestExecutor


class RequestDispatcher:
    def __init__(
        self,
        queue: JobQueue,
        executor: RequestExecutor,
    ) -> None:
        self._queue = queue
        self._executor = executor

        self._pending: Dict[
            str,
            asyncio.Future[GatewayResult],
        ] = {}

    async def submit(
        self,
        request: GatewayRequest,
    ) -> GatewayResult:
        loop = asyncio.get_running_loop()

        future: asyncio.Future[GatewayResult] = loop.create_future()

        job = GatewayJob(
            id=uuid4().hex,
            request=request,
            created_at=datetime.now(timezone.utc),
        )

        self._pending[job.id] = future

        try:
            self._queue.enqueue(job)
            return await future
        finally:
            self._pending.pop(job.id, None)

    async def run(self) -> None:
        while True:
            job = await self._queue.dequeue()

            future = self._pending.get(job.id)

            if future is None or future.done():
                continue

            try:
                result = await self._executor.execute(
                    job.request,
                )
            except Exception as exc:
                self._complete_with_exception(
                    job.id,
                    future,
                    exc,
                )
                continue

            self._complete_with_result(
                job.id,
                future,
                result,
            )

    def queue_size(self) -> int:
        return self._queue.size()

    def _complete_with_result(
        self,
        job_id: str,
        future: asyncio.Future[GatewayResult],
        result: GatewayResult,
    ) -> None:
        current = self._pending.get(job_id)

        if current is not future:
            return

        if future.done():
            return

        future.set_result(result)

    def _complete_with_exception(
        self,
        job_id: str,
        future: asyncio.Future[GatewayResult],
        error: Exception,
    ) -> None:
        current = self._pending.get(job_id)

        if current is not future:
            return

        if future.done():
            return

        future.set_exception(error)
