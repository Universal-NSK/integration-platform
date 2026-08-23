import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import bitrix_gateway.execution.executor as executor_module
import pytest
from bitrix_gateway.contracts.models import (
    ExecutionStatus,
    GatewayRequest,
    GatewayResult,
    RetryPolicy,
    TransportResult,
)
from bitrix_gateway.execution.executor import RequestExecutor
from bitrix_gateway.execution.transport import TransportError
from bitrix_gateway.limits.controller import BitrixApiLimitController

ScriptedOutcome = Union[TransportResult, TransportError]


class ScriptedTransport:
    def __init__(
        self,
        outcomes: Sequence[ScriptedOutcome],
        events: Optional[List[str]] = None,
    ) -> None:
        self._outcomes = list(outcomes)
        self._events = events
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def call(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> TransportResult:
        if self._events is not None:
            self._events.append(f"transport:{method}")
        self.calls.append((method, payload))

        if not self._outcomes:
            raise AssertionError("transport called more times than scripted")

        outcome = self._outcomes.pop(0)
        if isinstance(outcome, TransportError):
            raise outcome
        return outcome


class RecordingLimits(BitrixApiLimitController):
    def __init__(self, events: Optional[List[str]] = None) -> None:
        self._events = events
        self.waited_methods: List[str] = []
        self.cooldowns: List[Tuple[str, float]] = []

    async def wait_turn(self, method: str) -> None:
        if self._events is not None:
            self._events.append(f"limits:{method}")
        self.waited_methods.append(method)

    def set_cooldown(self, method: str, duration: float) -> None:
        self.cooldowns.append((method, duration))


def _request(
    retry_policy: RetryPolicy,
    *,
    method: str = "crm.item.list",
) -> GatewayRequest:
    return GatewayRequest(
        method=method,
        payload={"entityTypeId": 2},
        retry_policy=retry_policy,
    )


def _success(
    data: Optional[Dict[str, Any]] = None,
    *,
    operating_reset_at: Optional[float] = None,
) -> TransportResult:
    return TransportResult(
        data=data if data is not None else {"result": {"items": []}},
        http_status=200,
        error_code=None,
        error_message=None,
        operating_reset_at=operating_reset_at,
    )


def _api_error(
    http_status: int,
    error_code: str,
    *,
    operating_reset_at: Optional[float] = None,
) -> TransportResult:
    return TransportResult(
        data=None,
        http_status=http_status,
        error_code=error_code,
        error_message=f"{error_code} description",
        operating_reset_at=operating_reset_at,
    )


def _run(executor: RequestExecutor, request: GatewayRequest) -> GatewayResult:
    return asyncio.run(executor.execute(request))


def test_wait_turn_precedes_transport_and_success_passes_full_data() -> None:
    events: List[str] = []
    body: Dict[str, Any] = {
        "result": {"items": [{"id": 1}]},
        "next": 50,
        "total": 1576,
        "time": {"operating_reset_at": 1787492641},
    }
    transport = ScriptedTransport([_success(body)], events)
    limits = RecordingLimits(events)
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.SAFE))

    assert result == GatewayResult(
        status=ExecutionStatus.SUCCESS,
        data=body,
        http_status=200,
        error_code=None,
        error_message=None,
        attempt_count=1,
    )
    assert events == ["limits:crm.item.list", "transport:crm.item.list"]
    assert transport.calls == [("crm.item.list", {"entityTypeId": 2})]


def test_ordinary_bitrix_4xx_is_failed_without_retry() -> None:
    transport = ScriptedTransport(
        [
            _api_error(400, "ENTITY_TYPE_NOT_SUPPORTED"),
            _success(),
        ]
    )
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.SAFE))

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "ENTITY_TYPE_NOT_SUPPORTED"
    assert result.attempt_count == 1
    assert len(transport.calls) == 1
    assert limits.waited_methods == ["crm.item.list"]


def test_safe_retries_transport_errors_and_waits_before_every_attempt() -> None:
    events: List[str] = []
    transport = ScriptedTransport(
        [
            TransportError("not connected", outcome_uncertain=False),
            TransportError("response lost", outcome_uncertain=True),
            _success(),
        ],
        events,
    )
    limits = RecordingLimits(events)
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.SAFE))

    assert result.status is ExecutionStatus.SUCCESS
    assert result.attempt_count == 3
    assert events == [
        "limits:crm.item.list",
        "transport:crm.item.list",
        "limits:crm.item.list",
        "transport:crm.item.list",
        "limits:crm.item.list",
        "transport:crm.item.list",
    ]


@pytest.mark.parametrize(
    ("outcome_uncertain", "expected_status"),
    [
        (True, ExecutionStatus.UNKNOWN),
        (False, ExecutionStatus.FAILED),
    ],
)
def test_never_does_not_retry_transport_error_and_maps_certainty(
    outcome_uncertain: bool,
    expected_status: ExecutionStatus,
) -> None:
    transport = ScriptedTransport(
        [
            TransportError("transport failed", outcome_uncertain=outcome_uncertain),
            _success(),
        ]
    )
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.NEVER))

    assert result.status is expected_status
    assert result.error_code == "TRANSPORT_ERROR"
    assert result.attempt_count == 1
    assert len(transport.calls) == 1
    assert limits.waited_methods == ["crm.item.list"]


@pytest.mark.parametrize("max_attempts", [0, -1])
def test_max_attempts_must_be_positive(max_attempts: int) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RequestExecutor(
            ScriptedTransport([_success()]),
            RecordingLimits(),
            max_attempts=max_attempts,
            retry_delay=0,
        )


def test_retry_delay_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="retry_delay"):
        RequestExecutor(
            ScriptedTransport([_success()]),
            RecordingLimits(),
            max_attempts=1,
            retry_delay=-0.1,
        )


@pytest.mark.parametrize(
    "temporary_result",
    [
        _api_error(429, "QUERY_LIMIT_EXCEEDED"),
        _api_error(503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_safe_retries_query_limit_and_server_errors(
    temporary_result: TransportResult,
) -> None:
    transport = ScriptedTransport([temporary_result, _success()])
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=2, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.SAFE))

    assert result.status is ExecutionStatus.SUCCESS
    assert result.attempt_count == 2
    assert len(transport.calls) == 2
    assert limits.waited_methods == ["crm.item.list", "crm.item.list"]


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (_api_error(429, "QUERY_LIMIT_EXCEEDED"), ExecutionStatus.FAILED),
        (_api_error(503, "SERVICE_UNAVAILABLE"), ExecutionStatus.UNKNOWN),
    ],
)
def test_never_does_not_retry_query_limit_or_server_error(
    response: TransportResult,
    expected_status: ExecutionStatus,
) -> None:
    transport = ScriptedTransport([response, _success()])
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=2, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.NEVER))

    assert result.status is expected_status
    assert result.attempt_count == 1
    assert len(transport.calls) == 1
    assert limits.waited_methods == ["crm.item.list"]


def test_operation_time_limit_sets_saved_method_cooldown_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: List[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(executor_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(executor_module.asyncio, "sleep", fake_sleep)

    method = "crm.item.list"
    transport = ScriptedTransport(
        [
            _success(operating_reset_at=160.0),
            _api_error(400, "OPERATION_TIME_LIMIT"),
        ]
    )
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=10)

    first_result = _run(executor, _request(RetryPolicy.SAFE, method=method))
    limited_result = _run(executor, _request(RetryPolicy.SAFE, method=method))

    assert first_result.status is ExecutionStatus.SUCCESS
    assert limited_result.status is ExecutionStatus.FAILED
    assert limited_result.attempt_count == 1
    assert limits.cooldowns == [(method, 60.0)]
    assert sleep_calls == []
    assert len(transport.calls) == 2


def test_operating_reset_at_is_remembered_per_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor_module.time, "time", lambda: 100.0)

    first_method = "crm.item.list"
    second_method = "crm.lead.list"
    transport = ScriptedTransport(
        [
            _success(operating_reset_at=150.0),
            _success(operating_reset_at=300.0),
            _api_error(400, "OPERATION_TIME_LIMIT"),
            _api_error(400, "OPERATION_TIME_LIMIT"),
        ]
    )
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=1, retry_delay=0)

    _run(executor, _request(RetryPolicy.SAFE, method=first_method))
    _run(executor, _request(RetryPolicy.SAFE, method=second_method))
    _run(executor, _request(RetryPolicy.SAFE, method=first_method))
    _run(executor, _request(RetryPolicy.SAFE, method=second_method))

    assert limits.cooldowns == [
        (first_method, 50.0),
        (second_method, 200.0),
    ]


def test_exhausted_safe_retries_return_final_gateway_result() -> None:
    transport = ScriptedTransport(
        [
            _api_error(503, "SERVICE_UNAVAILABLE"),
            _api_error(503, "SERVICE_UNAVAILABLE"),
            _api_error(503, "SERVICE_UNAVAILABLE"),
        ]
    )
    limits = RecordingLimits()
    executor = RequestExecutor(transport, limits, max_attempts=3, retry_delay=0)

    result = _run(executor, _request(RetryPolicy.SAFE))

    assert result.status is ExecutionStatus.FAILED
    assert result.http_status == 503
    assert result.error_code == "SERVICE_UNAVAILABLE"
    assert result.attempt_count == 3
    assert len(transport.calls) == 3
    assert limits.waited_methods == [
        "crm.item.list",
        "crm.item.list",
        "crm.item.list",
    ]
