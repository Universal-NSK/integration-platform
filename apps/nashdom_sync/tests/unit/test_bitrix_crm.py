import logging
from dataclasses import FrozenInstanceError
from typing import Any, Callable, Dict, Iterator, List, Tuple, Type
from unittest.mock import Mock

import pytest
from nashdom_sync.bitrix_crm import (
    BitrixGatewayError,
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
    ClientBitrixCRM,
)
from nashdom_sync.bitrix_crm._contracts import (
    GatewayCallResult,
    GatewayExecutionStatus,
    RetryPolicy,
)
from platform_logging.formatter import DETAILS_ATTRIBUTE, EVENT_ATTRIBUTE

Operation = Callable[[ClientBitrixCRM], Any]


def crm_events(caplog: pytest.LogCaptureFixture) -> List[Tuple[str, Dict[str, Any]]]:
    records = [r for r in caplog.records if r.name == "nashdom_sync.bitrix_crm.client"]
    assert all(r.levelno == logging.DEBUG and r.exc_info is None for r in records)
    return [(getattr(r, EVENT_ATTRIBUTE), getattr(r, DETAILS_ATTRIBUTE)) for r in records]


def success(data: Dict[str, Any]) -> GatewayCallResult:
    return GatewayCallResult(GatewayExecutionStatus.SUCCESS, data, 200, None, None, 1)


@pytest.fixture
def crm(monkeypatch: pytest.MonkeyPatch) -> Iterator[Tuple[ClientBitrixCRM, Mock]]:
    gateway = Mock()
    constructor = Mock(return_value=gateway)
    monkeypatch.setattr("nashdom_sync.bitrix_crm.client.GatewayHttpClient", constructor)
    client = ClientBitrixCRM(gateway_url="http://gateway.invalid", timeout=3.0)
    constructor.assert_called_once_with(base_url="http://gateway.invalid", timeout=3.0)
    try:
        yield client, gateway
    finally:
        client.close()


READ_CASES: List[Tuple[Operation, str, Dict[str, Any], Any, Any]] = [
    (lambda c: c.profile(), "profile", {}, {"ID": "1"}, {"ID": "1"}),
    (
        lambda c: c.list_items(4, filter_={"id": 7}, select=["id"]),
        "crm.item.list",
        {"entityTypeId": 4, "filter": {"id": 7}, "select": ["id"]},
        {"items": [{"id": 7}]},
        [{"id": 7}],
    ),
    (
        lambda c: c.get_item_fields(4),
        "crm.item.fields",
        {"entityTypeId": 4},
        {"fields": {"title": {"type": "string"}}},
        {"title": {"type": "string"}},
    ),
    (
        lambda c: c.list_statuses("SOURCE"),
        "crm.status.list",
        {"filter": {"ENTITY_ID": "SOURCE"}},
        [{"ID": "1"}],
        [{"ID": "1"}],
    ),
    (
        lambda c: c.list_users(filter_={"NAME": "Иван"}),
        "user.get",
        {"FILTER": {"NAME": "Иван"}},
        [{"ID": "1"}],
        [{"ID": "1"}],
    ),
    (lambda c: c.list_requisite_presets(), "crm.requisite.preset.list", {}, [], []),
    (
        lambda c: c.list_requisites(filter_={"ENTITY_ID": 7}),
        "crm.requisite.list",
        {"filter": {"ENTITY_ID": 7}},
        [],
        [],
    ),
    (
        lambda c: c.list_addresses(filter_={"ENTITY_ID": 8}),
        "crm.address.list",
        {"filter": {"ENTITY_ID": 8}},
        [],
        [],
    ),
    (
        lambda c: c.get_address_fields(),
        "crm.address.fields",
        {},
        {"ADDRESS_2": {}},
        {"ADDRESS_2": {}},
    ),
    (lambda c: c.list_address_types(), "crm.enum.addresstype", {}, [{"ID": 6}], [{"ID": 6}]),
    (
        lambda c: c.list_owner_types(),
        "crm.enum.ownertype",
        {},
        [{"ID": 1050, "NAME": "Группа компаний"}],
        [{"ID": 1050, "NAME": "Группа компаний"}],
    ),
]


@pytest.mark.parametrize(
    "operation,method,payload,result,expected",
    READ_CASES,
)
def test_read_contracts(
    crm: Tuple[ClientBitrixCRM, Mock],
    operation: Operation,
    method: str,
    payload: Dict[str, Any],
    result: Any,
    expected: Any,
) -> None:
    client, gateway = crm
    gateway.call.return_value = success({"result": result})
    assert operation(client) == expected
    gateway.call.assert_called_once_with(method, payload, RetryPolicy.SAFE)


WRITE_CASES: List[Tuple[Operation, str, Dict[str, Any], Any, Any]] = [
    (
        lambda c: c.add_item(4, {"title": "Компания"}),
        "crm.item.add",
        {"entityTypeId": 4, "fields": {"title": "Компания"}},
        {"item": {"id": 7}},
        7,
    ),
    (
        lambda c: c.add_requisite({"RQ_INN": "001", "RQ_KPP": "002", "RQ_OGRN": "003"}),
        "crm.requisite.add",
        {"fields": {"RQ_INN": "001", "RQ_KPP": "002", "RQ_OGRN": "003"}},
        8,
        8,
    ),
    (
        lambda c: c.add_address({"ADDRESS_2": "Улица Пушкина"}),
        "crm.address.add",
        {"fields": {"ADDRESS_2": "Улица Пушкина"}},
        True,
        None,
    ),
]


@pytest.mark.parametrize(
    "operation,method,payload,result,expected",
    WRITE_CASES,
)
def test_write_contracts(
    crm: Tuple[ClientBitrixCRM, Mock],
    operation: Operation,
    method: str,
    payload: Dict[str, Any],
    result: Any,
    expected: Any,
) -> None:
    client, gateway = crm
    gateway.call.return_value = success({"result": result})
    assert operation(client) == expected
    gateway.call.assert_called_once_with(method, payload, RetryPolicy.NEVER)


PAGE_CASES: List[Tuple[Operation, bool]] = [
    (lambda c: c.list_items(4, filter_={}, select=[]), True),
    (lambda c: c.list_statuses("INDUSTRY"), False),
    (lambda c: c.list_users(), False),
    (lambda c: c.list_requisite_presets(), False),
    (lambda c: c.list_requisites(), False),
    (lambda c: c.list_addresses(), False),
]


@pytest.mark.parametrize(
    "operation,items",
    PAGE_CASES,
)
def test_all_pages(crm: Tuple[ClientBitrixCRM, Mock], operation: Operation, items: bool) -> None:
    client, gateway = crm
    first = [{"id": i} for i in range(50)]
    second = [{"id": 50}]
    gateway.call.side_effect = [
        success({"result": {"items": first} if items else first, "next": 50, "total": 51}),
        success({"result": {"items": second} if items else second, "total": 51}),
    ]
    assert operation(client) == first + second
    before: Dict[str, Any] = gateway.call.call_args_list[0].args[1]
    after: Dict[str, Any] = gateway.call.call_args_list[1].args[1]
    assert "start" not in before
    assert after == dict(before, start=50)
    assert all(call.args[2] is RetryPolicy.SAFE for call in gateway.call.call_args_list)


@pytest.mark.parametrize("next_value", [0, -1, True, "50", None, [], {}])
def test_bad_next_is_rejected(crm: Tuple[ClientBitrixCRM, Mock], next_value: Any) -> None:
    client, gateway = crm
    gateway.call.return_value = success({"result": [], "next": next_value})
    with pytest.raises(BitrixGatewayError, match="next"):
        client.list_users()
    assert gateway.call.call_count == 1


def test_repeated_cursor_is_rejected(crm: Tuple[ClientBitrixCRM, Mock]) -> None:
    client, gateway = crm
    gateway.call.return_value = success({"result": [], "next": 50})
    with pytest.raises(BitrixGatewayError, match="next"):
        client.list_users()
    assert gateway.call.call_count == 2


def test_filter_and_select_are_not_mutated(crm: Tuple[ClientBitrixCRM, Mock]) -> None:
    client, gateway = crm
    filter_: Dict[str, Any] = {"id": 1}
    select: List[str] = ["id"]
    gateway.call.side_effect = [
        success({"result": {"items": []}, "next": 50}),
        success({"result": {"items": []}}),
    ]
    assert client.list_items(4, filter_=filter_, select=select) == []
    assert filter_ == {"id": 1}
    assert select == ["id"]


@pytest.mark.parametrize(
    "status,error",
    [
        (GatewayExecutionStatus.FAILED, BitrixRequestFailedError),
        (GatewayExecutionStatus.UNKNOWN, BitrixRequestUnknownError),
    ],
)
def test_failure_diagnostics_hide_server_text(
    crm: Tuple[ClientBitrixCRM, Mock],
    status: GatewayExecutionStatus,
    error: Type[Exception],
) -> None:
    client, gateway = crm
    gateway.call.return_value = GatewayCallResult(
        status,
        None,
        400,
        "ACCESS_DENIED",
        "token=private https://secret.invalid/rest/key",
        1,
    )
    with pytest.raises(error) as exc:
        client.add_requisite({})
    message = str(exc.value)
    assert "crm.requisite.add" in message and "400" in message and "ACCESS_DENIED" in message
    assert "private" not in message and "secret.invalid" not in message
    assert gateway.call.call_count == 1


BAD_CASES: List[Tuple[Operation, Any]] = [
    (lambda c: c.profile(), []),
    (lambda c: c.list_users(), {}),
    (lambda c: c.list_users(), [1]),
    (lambda c: c.list_items(4), []),
    (lambda c: c.get_item_fields(4), {}),
    (lambda c: c.get_address_fields(), []),
    (lambda c: c.add_item(4, {}), {"item": {"id": True}}),
    (lambda c: c.add_requisite({}), "8"),
    (lambda c: c.add_requisite({}), 0),
    (lambda c: c.add_address({}), 1),
    (lambda c: c.add_address({}), False),
]


@pytest.mark.parametrize(
    "operation,result",
    BAD_CASES,
)
def test_bad_bitrix_result(
    crm: Tuple[ClientBitrixCRM, Mock],
    operation: Operation,
    result: Any,
) -> None:
    client, gateway = crm
    gateway.call.return_value = success({"result": result})
    with pytest.raises(BitrixGatewayError):
        operation(client)


def test_close_delegates(crm: Tuple[ClientBitrixCRM, Mock]) -> None:
    client, gateway = crm
    client.close()
    gateway.close.assert_called_once_with()


def test_result_is_frozen() -> None:
    result = success({"result": True})
    with pytest.raises(FrozenInstanceError):
        result.attempt_count = 2  # pyright: ignore[reportAttributeAccessIssue]


def test_single_call_debug_events(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(
        "nashdom_sync.bitrix_crm.client.perf_counter", Mock(side_effect=[10, 10.25])
    )
    gateway.call.return_value = success({"result": {"fields": {"private": "secret"}}})
    assert client.get_item_fields(4) == {"private": "secret"}
    context = {"method": "crm.item.fields", "retry_policy": "safe", "entity_type_id": 4}
    assert crm_events(caplog) == [
        ("bitrix_call_started", context),
        (
            "bitrix_call_completed",
            dict(
                context,
                gateway_status="success",
                http_status=200,
                attempt_count=1,
                duration_seconds=0.25,
            ),
        ),
    ]
    assert "secret" not in repr([r.__dict__ for r in caplog.records])


@pytest.mark.parametrize(
    "status,error",
    [
        (GatewayExecutionStatus.FAILED, BitrixRequestFailedError),
        (GatewayExecutionStatus.UNKNOWN, BitrixRequestUnknownError),
    ],
)
@pytest.mark.parametrize(
    "code,safe_code",
    [
        ("ACCESS_DENIED", "ACCESS_DENIED"),
        (None, None),
        ("A" + "_" * 79, "A" + "_" * 79),
        ("A" * 81, "[скрыто]"),
        ("", "[скрыто]"),
        ("private https://secret.invalid/token", "[скрыто]"),
        ("ERROR\n", "[скрыто]"),
        ("lowercase", "[скрыто]"),
    ],
)
def test_unsuccessful_debug_events(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
    status: GatewayExecutionStatus,
    error: Type[Exception],
    code: Any,
    safe_code: Any,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    gateway.call.return_value = GatewayCallResult(
        status,
        None,
        503,
        code,
        "private server message",
        3,
    )
    with pytest.raises(error) as exc:
        client.get_item_fields(4)
    events = crm_events(caplog)
    assert [name for name, _ in events] == ["bitrix_call_started", "bitrix_call_unsuccessful"]
    details = events[-1][1]
    assert details.pop("duration_seconds") >= 0
    assert details == {
        "method": "crm.item.fields",
        "retry_policy": "safe",
        "entity_type_id": 4,
        "gateway_status": status.value,
        "http_status": 503,
        "attempt_count": 3,
        "error_code": safe_code,
    }
    assert "error_code={}".format(safe_code) in str(exc.value)
    assert "private" not in str(exc.value)
    assert "private" not in repr([r.__dict__ for r in caplog.records])


def test_gateway_failure_is_reraised_and_logged(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    error = BitrixGatewayError("private gateway URL")
    cause = ValueError("private cause")
    error.__cause__ = cause
    gateway.call.side_effect = error
    with pytest.raises(BitrixGatewayError) as exc:
        client.get_item_fields(4)
    assert exc.value is error and exc.value.__cause__ is cause
    events = crm_events(caplog)
    assert [name for name, _ in events] == ["bitrix_call_started", "bitrix_call_failed"]
    details = events[-1][1]
    assert details.pop("duration_seconds") >= 0
    assert details == {
        "method": "crm.item.fields",
        "retry_policy": "safe",
        "entity_type_id": 4,
        "exception_type": "BitrixGatewayError",
    }
    assert "private" not in repr([r.__dict__ for r in caplog.records])


def test_pagination_debug_events_and_payload_allowlist(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(
        "nashdom_sync.bitrix_crm.client.perf_counter",
        Mock(side_effect=[0, 1, 2, 3, 4, 5]),
    )
    gateway.call.side_effect = [
        success({"result": {"items": [{"private": 1}, {"private": 2}]}, "next": 50}),
        success({"result": {"items": [{"private": 3}]}}),
    ]
    assert len(client.list_items(4, filter_={"private": "secret"}, select=["private"])) == 3
    events = crm_events(caplog)
    assert [name for name, _ in events] == [
        "bitrix_call_started",
        "bitrix_call_completed",
        "bitrix_call_started",
        "bitrix_call_completed",
        "bitrix_pagination_completed",
    ]
    for _, details in events[:4]:
        assert details["entity_type_id"] == 4
        assert details["retry_policy"] == "safe"
    assert "start" not in events[0][1] and "start" not in events[1][1]
    assert events[2][1]["start"] == events[3][1]["start"] == 50
    assert events[-1][1] == {
        "method": "crm.item.list",
        "entity_type_id": 4,
        "pages": 2,
        "records": 3,
        "duration_seconds": 5,
    }
    assert "private" not in repr([r.__dict__ for r in caplog.records])
    assert "secret" not in repr([r.__dict__ for r in caplog.records])


@pytest.mark.parametrize("error", [BitrixGatewayError("private"), ValueError("private")])
@pytest.mark.parametrize("first_page", [False, True])
def test_pagination_failure_progress_and_identity(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    first_page: bool,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    gateway.call.side_effect = (
        [
            success({"result": {"items": [{"id": 1}]}, "next": 50}),
        ]
        if first_page
        else []
    ) + [error]
    with pytest.raises(type(error)) as exc:
        client.list_items(4, filter_={"private": "secret"})
    assert exc.value is error
    events = crm_events(caplog)
    assert [name for name, _ in events[-3:]] == [
        "bitrix_call_started",
        "bitrix_call_failed",
        "bitrix_pagination_failed",
    ]
    details = events[-1][1]
    assert details.pop("duration_seconds") >= 0
    assert details == {
        "method": "crm.item.list",
        "entity_type_id": 4,
        "pages_completed": int(first_page),
        "records_received": int(first_page),
        "next_start": 50 if first_page else 0,
        "exception_type": type(error).__name__,
    }
    assert "private" not in repr([r.__dict__ for r in caplog.records])


@pytest.mark.parametrize(
    "page,records_received",
    [
        ({"result": [{"id": 2}], "next": "private"}, 2),
        ({"result": [{"id": 2}], "next": 50}, 2),
        ({"result": "private"}, 1),
    ],
)
def test_pagination_contract_failure_debug_event(
    crm: Tuple[ClientBitrixCRM, Mock],
    caplog: pytest.LogCaptureFixture,
    page: Dict[str, Any],
    records_received: int,
) -> None:
    client, gateway = crm
    caplog.set_level(logging.DEBUG)
    gateway.call.side_effect = [success({"result": [{"id": 1}], "next": 50}), success(page)]
    with pytest.raises(BitrixGatewayError):
        client.list_users()
    events = crm_events(caplog)
    assert events[-1][0] == "bitrix_pagination_failed"
    details = events[-1][1]
    assert details.pop("duration_seconds") >= 0
    assert details == {
        "method": "user.get",
        "pages_completed": 1,
        "records_received": records_received,
        "next_start": 50,
        "exception_type": "BitrixGatewayError",
    }
    assert "private" not in repr([r.__dict__ for r in caplog.records])


def test_search_users_pagination(crm: Tuple[ClientBitrixCRM, Mock]) -> None:
    client, gateway = crm
    gateway.call.side_effect = [
        success({"result": [{"ID": "1"}], "next": 50}),
        success({"result": [{"ID": "2"}]}),
    ]
    assert client.search_users("Иванов Иван") == [{"ID": "1"}, {"ID": "2"}]
    assert gateway.call.call_count == 2
    assert gateway.call.call_args_list[0].args == (
        "user.search",
        {"FILTER": {"FIND": "Иванов Иван"}},
        RetryPolicy.SAFE,
    )
    assert gateway.call.call_args_list[1].args == (
        "user.search",
        {"FILTER": {"FIND": "Иванов Иван"}, "start": 50},
        RetryPolicy.SAFE,
    )


@pytest.mark.parametrize(
    "data",
    [
        {"result": {}},
        {"result": [None]},
        {"result": [], "next": "50"},
        {"result": [], "next": 0},
    ],
)
def test_search_users_rejects_malformed_page(
    crm: Tuple[ClientBitrixCRM, Mock], data: Dict[str, Any]
) -> None:
    client, gateway = crm
    gateway.call.return_value = success(data)
    with pytest.raises(BitrixGatewayError):
        client.search_users("Иванов")
