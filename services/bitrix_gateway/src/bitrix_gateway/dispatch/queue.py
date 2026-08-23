from __future__ import annotations

import asyncio
from typing import Protocol

from bitrix_gateway.dispatch.job import GatewayJob


class QueueFullError(Exception):
    pass


class JobQueue(Protocol):
    def enqueue(self, job: GatewayJob) -> None: ...

    async def dequeue(self) -> GatewayJob: ...

    def size(self) -> int: ...


class InMemoryJobQueue:
    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero")

        self._queue: asyncio.Queue[GatewayJob] = asyncio.Queue(
            maxsize=max_size,
        )

    def enqueue(self, job: GatewayJob) -> None:
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise QueueFullError("Job queue is full") from exc

    async def dequeue(self) -> GatewayJob:
        return await self._queue.get()

    def size(self) -> int:
        return self._queue.qsize()
