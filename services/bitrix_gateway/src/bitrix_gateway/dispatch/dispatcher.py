from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from platform_logging import log_event

from bitrix_gateway.contracts.models import (
    GatewayRequest,
    GatewayResult,
)
from bitrix_gateway.dispatch.job import GatewayJob
from bitrix_gateway.dispatch.queue import JobQueue, QueueFullError
from bitrix_gateway.execution.executor import RequestExecutor

logger = logging.getLogger(__name__)


class RequestDispatcher:
    """Связывает входящие запросы с одним последовательным worker."""

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
        """Поставить запрос в очередь и дождаться результата его задания."""

        loop = asyncio.get_running_loop()

        future: asyncio.Future[GatewayResult] = loop.create_future()

        job = GatewayJob(
            id=uuid4().hex,
            request=request,
            created_at=datetime.now(timezone.utc),
        )

        self._pending[job.id] = future

        try:
            try:
                self._queue.enqueue(job)
            except QueueFullError:
                log_event(
                    logger,
                    logging.WARNING,
                    "dispatcher_job_rejected",
                    method=request.method,
                    queue_size=self._queue.size(),
                    job_id=job.id,
                    error_code="QUEUE_FULL",
                )
                raise

            log_event(
                logger,
                logging.DEBUG,
                "dispatcher_job_enqueued",
                method=request.method,
                queue_size=self._queue.size(),
                job_id=job.id,
            )
            return await future
        finally:
            self._pending.pop(job.id, None)

    async def run(self) -> None:
        """Последовательно обрабатывать задания, не завершаясь из-за обычной ошибки."""

        while True:
            job = await self._queue.dequeue()

            log_event(
                logger,
                logging.DEBUG,
                "dispatcher_job_dequeued",
                method=job.request.method,
                queue_size=self._queue.size(),
                job_id=job.id,
            )

            future = self._pending.get(job.id)

            if future is None or future.done():
                log_event(
                    logger,
                    logging.DEBUG,
                    "dispatcher_job_skipped",
                    method=job.request.method,
                    queue_size=self._queue.size(),
                    job_id=job.id,
                )
                continue

            try:
                result = await self._executor.execute(
                    job.request,
                )
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "dispatcher_job_failed",
                    method=job.request.method,
                    job_id=job.id,
                    exception_type=type(exc).__name__,
                )
                self._complete_with_exception(
                    job.id,
                    future,
                    exc,
                )
                continue

            log_event(
                logger,
                logging.DEBUG,
                "dispatcher_job_completed",
                method=job.request.method,
                status=result.status.value,
                attempt_count=result.attempt_count,
                job_id=job.id,
            )
            self._complete_with_result(
                job.id,
                future,
                result,
            )

    def queue_size(self) -> int:
        """Вернуть число заданий, ожидающих обработки."""

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
