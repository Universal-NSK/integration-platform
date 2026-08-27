from __future__ import annotations

import asyncio
from typing import Protocol

from bitrix_gateway.dispatch.job import GatewayJob


class QueueFullError(Exception):
    """Сообщает об отказе постановки задания в заполненную очередь."""


class JobQueue(Protocol):
    """Определяет минимальный FIFO-контракт очереди заданий Gateway."""

    def enqueue(self, job: GatewayJob) -> None:
        """Поставить задание без ожидания свободного места."""

        ...

    async def dequeue(self) -> GatewayJob:
        """Дождаться и извлечь следующее задание."""

        ...

    def size(self) -> int:
        """Вернуть текущее число ожидающих заданий."""

        ...


class InMemoryJobQueue:
    """Хранит ограниченную FIFO-очередь в памяти процесса."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size должен быть больше нуля")

        self._queue: asyncio.Queue[GatewayJob] = asyncio.Queue(
            maxsize=max_size,
        )

    def enqueue(self, job: GatewayJob) -> None:
        """Поставить задание или немедленно сообщить о переполнении."""

        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise QueueFullError("Очередь заданий Gateway переполнена") from exc

    async def dequeue(self) -> GatewayJob:
        """Дождаться и извлечь самое раннее задание."""

        return await self._queue.get()

    def size(self) -> int:
        """Вернуть текущее число заданий в памяти."""

        return self._queue.qsize()
