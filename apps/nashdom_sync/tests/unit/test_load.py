"""Контракты, зависимости и владение клиентом Load без внешних вызовов."""

import logging
from dataclasses import FrozenInstanceError
from typing import Any, Dict, List, Optional, Type, cast
from unittest.mock import Mock, call

import pytest
from nashdom_sync.bitrix_crm import (
    BitrixGatewayError,
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
    ClientBitrixCRM,
)
from nashdom_sync.contracts import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    BitrixClientSettings,
    CrmCommand,
    LoadResult,
    OperationResult,
    OperationStatus,
    PlannedOperation,
    RuntimeBinding,
    SyncPlan,
)
from nashdom_sync.load import (
    CrmCommandExecutor,
    LoadInvariantError,
    LoadService,
    RuntimeBindingResolver,
    SyncPlanExecutor,
)
from nashdom_sync.load import service as service_module
from platform_logging.formatter import DETAILS_ATTRIBUTE


@pytest.mark.parametrize("status", list(OperationStatus))
def test_result_success_and_immutability(status: OperationStatus) -> None:
    operation = OperationResult("a", status)
    result = LoadResult((OperationResult("b", OperationStatus.SUCCESS, 1), operation))
    assert result.is_successful is (status is OperationStatus.SUCCESS)
    assert LoadResult(()).is_successful
    for model, field in ((operation, "crm_id"), (result, "operations")):
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, None)


@pytest.mark.parametrize(
    "command",
    [
        AddItemCommand(4, {"TITLE": "Секрет"}),
        AddRequisiteCommand({"RQ_INN": "0012345678"}),
        AddAddressCommand({"ADDRESS_1": "Секретный адрес"}),
    ],
)
@pytest.mark.parametrize("bound", [False, True])
def test_resolver_new_command_without_mutation(command: CrmCommand, bound: bool) -> None:
    fields = dict(command.fields)
    bindings = (RuntimeBinding("OWNER", "source"),) if bound else ()
    operation = PlannedOperation("target", command, bindings)
    resolved = RuntimeBindingResolver().resolve(
        operation, {"source": OperationResult("source", OperationStatus.SUCCESS, 73)}
    )
    assert resolved is not command
    assert type(resolved) is type(command)
    assert resolved.fields is not command.fields
    expected_fields = dict(fields, OWNER=73) if bound else fields
    assert resolved.fields == expected_fields
    if isinstance(resolved, AddItemCommand):
        assert resolved.entity_type_id == 4
    assert command.fields == fields
    assert operation.command is command


@pytest.mark.parametrize(
    "source",
    [
        None,
        OperationResult("source", OperationStatus.SUCCESS),
        OperationResult("source", OperationStatus.FAILED),
        OperationResult("source", OperationStatus.UNKNOWN),
        OperationResult("source", OperationStatus.BLOCKED),
    ],
)
def test_resolver_invariants(source: Optional[OperationResult]) -> None:
    operation = PlannedOperation(
        "target",
        AddRequisiteCommand({"RQ_INN": "секрет"}),
        (RuntimeBinding("OWNER", "source"),),
    )
    with pytest.raises(LoadInvariantError) as caught:
        RuntimeBindingResolver().resolve(operation, {} if source is None else {"source": source})
    assert all(value in str(caught.value) for value in ("target", "source", "OWNER"))
    assert "секрет" not in str(caught.value)
    if source is not None and source.status is OperationStatus.SUCCESS:
        assert "crm_id" in str(caught.value)


@pytest.mark.parametrize(
    "command, method, args, result",
    [
        (AddItemCommand(4, {"TITLE": "Имя"}), "add_item", (4, {"TITLE": "Имя"}), 11),
        (AddRequisiteCommand({"RQ_INN": "001"}), "add_requisite", ({"RQ_INN": "001"},), 12),
        (AddAddressCommand({"CITY": "Город"}), "add_address", ({"CITY": "Город"},), None),
    ],
)
def test_command_dispatch(
    command: CrmCommand, method: str, args: Any, result: Optional[int]
) -> None:
    client = Mock(spec=ClientBitrixCRM)
    getattr(client, method).return_value = result
    assert CrmCommandExecutor(client).execute(command) == result
    assert client.mock_calls == [getattr(call, method)(*args)]


def test_unsupported_command() -> None:
    command = cast(CrmCommand, object())
    client = Mock(spec=ClientBitrixCRM)
    for action in (
        lambda: CrmCommandExecutor(client).execute(command),
        lambda: RuntimeBindingResolver().resolve(PlannedOperation("target", command), {}),
    ):
        with pytest.raises(LoadInvariantError, match="CRM-команды: object"):
            action()
    assert not client.mock_calls


def test_execute_order_resolved_ids_and_address_success() -> None:
    client = Mock(spec=ClientBitrixCRM)
    client.add_item.side_effect = [101, 303]
    client.add_requisite.return_value = 202
    plan = SyncPlan(
        (
            PlannedOperation("z", AddItemCommand(4, {"TITLE": "Компания"})),
            PlannedOperation("r", AddRequisiteCommand({}), (RuntimeBinding("ENTITY_ID", "z"),)),
            PlannedOperation("a", AddAddressCommand({}), (RuntimeBinding("ENTITY_ID", "r"),)),
            PlannedOperation("b", AddItemCommand(2, {}), dependencies=("a",)),
        )
    )
    result = SyncPlanExecutor(RuntimeBindingResolver(), CrmCommandExecutor(client)).execute(plan)
    assert result == LoadResult(
        (
            OperationResult("z", OperationStatus.SUCCESS, 101),
            OperationResult("r", OperationStatus.SUCCESS, 202),
            OperationResult("a", OperationStatus.SUCCESS),
            OperationResult("b", OperationStatus.SUCCESS, 303),
        )
    )
    assert result.is_successful
    assert client.mock_calls == [
        call.add_item(4, {"TITLE": "Компания"}),
        call.add_requisite({"ENTITY_ID": 101}),
        call.add_address({"ENTITY_ID": 202}),
        call.add_item(2, {}),
    ]
    assert plan.operations[1].command.fields == {}


@pytest.mark.parametrize(
    "error, status",
    [
        (BitrixRequestFailedError("секрет"), OperationStatus.FAILED),
        (BitrixRequestUnknownError("секрет"), OperationStatus.UNKNOWN),
    ],
)
def test_failed_branches_block_only_direct_dependencies(
    error: Exception, status: OperationStatus
) -> None:
    command = AddItemCommand(4, {})
    executor = Mock(spec=CrmCommandExecutor)
    executor.execute.side_effect = [error, error, 30, 40, 50]
    plan = SyncPlan(
        (
            PlannedOperation("first", command),
            PlannedOperation("second", command),
            PlannedOperation("bound", command, (RuntimeBinding("OWNER", "first"),)),
            PlannedOperation("explicit", command, dependencies=("second",)),
            PlannedOperation(
                "duplicate",
                command,
                (RuntimeBinding("OWNER", "first"), RuntimeBinding("OTHER", "second")),
                ("second", "first", "second"),
            ),
            PlannedOperation("transitive", command, dependencies=("bound", "explicit")),
            PlannedOperation("independent", command),
            PlannedOperation("sibling1", command, dependencies=("independent",)),
            PlannedOperation("sibling2", command, dependencies=("independent",)),
        )
    )
    result = SyncPlanExecutor(RuntimeBindingResolver(), executor).execute(plan)
    assert tuple(r.operation_id for r in result.operations) == tuple(
        op.operation_id for op in plan.operations
    )
    for item in result.operations[:2]:
        assert item.status is status
        assert item.error_type == type(error).__name__
        assert item.crm_id is None
    assert [r.blocked_by for r in result.operations[2:6]] == [
        ("first",),
        ("second",),
        ("second", "first"),
        ("bound", "explicit"),
    ]
    assert all(r.status is OperationStatus.BLOCKED for r in result.operations[2:6])
    assert all(r.status is OperationStatus.SUCCESS for r in result.operations[6:])
    assert executor.execute.call_count == 5


@pytest.mark.parametrize(
    "error",
    [
        BitrixGatewayError("секрет"),
        RuntimeError("секрет"),
        LoadInvariantError("Ошибка контракта"),
    ],
)
def test_execute_aborts_on_primary_error(error: Exception) -> None:
    executor = Mock(spec=CrmCommandExecutor)
    executor.execute.side_effect = error
    plan = SyncPlan(tuple(PlannedOperation(str(i), AddItemCommand(4, {})) for i in range(2)))
    with pytest.raises(type(error)) as caught:
        SyncPlanExecutor(RuntimeBindingResolver(), executor).execute(plan)
    assert caught.value is error
    executor.execute.assert_called_once()


@pytest.mark.parametrize(
    "bindings, dependencies",
    [
        ((RuntimeBinding("OWNER", "later"),), ()),
        ((), ("later",)),
    ],
)
def test_missing_earlier_dependency(bindings: Any, dependencies: Any) -> None:
    executor = Mock(spec=CrmCommandExecutor)
    plan = SyncPlan(
        (
            PlannedOperation(
                "target", AddItemCommand(4, {"TITLE": "секрет"}), bindings, dependencies
            ),
            PlannedOperation("later", AddItemCommand(4, {})),
        )
    )
    with pytest.raises(LoadInvariantError) as caught:
        SyncPlanExecutor(RuntimeBindingResolver(), executor).execute(plan)
    assert "target" in str(caught.value) and "later" in str(caught.value)
    assert "секрет" not in str(caught.value)
    executor.execute.assert_not_called()


def test_missing_dependency_not_hidden_by_blocker() -> None:
    executor = Mock(spec=CrmCommandExecutor)
    executor.execute.side_effect = BitrixRequestFailedError("Ошибка запроса")
    command = AddItemCommand(4, {})
    plan = SyncPlan(
        (
            PlannedOperation("a", command),
            PlannedOperation("b", command, dependencies=("a", "missing")),
        )
    )
    with pytest.raises(LoadInvariantError, match="missing"):
        SyncPlanExecutor(RuntimeBindingResolver(), executor).execute(plan)
    executor.execute.assert_called_once()


def test_duplicate_operation_is_not_executed_twice() -> None:
    executor = Mock(spec=CrmCommandExecutor)
    executor.execute.return_value = 1
    operation = PlannedOperation("same", AddItemCommand(4, {}))
    with pytest.raises(LoadInvariantError, match="same"):
        SyncPlanExecutor(RuntimeBindingResolver(), executor).execute(
            SyncPlan((operation, operation))
        )
    executor.execute.assert_called_once()


def test_empty_plan() -> None:
    resolver = Mock(spec=RuntimeBindingResolver)
    executor = Mock(spec=CrmCommandExecutor)
    assert SyncPlanExecutor(resolver, executor).execute(SyncPlan(())) == LoadResult(())
    resolver.resolve.assert_not_called()
    executor.execute.assert_not_called()


def settings() -> BitrixClientSettings:
    return BitrixClientSettings.parse_obj(
        {"gateway_url": "http://example.invalid", "timeout": 180.0}
    )


@pytest.mark.parametrize("execution_fails", [False, True])
@pytest.mark.parametrize("close_fails", [False, True])
def test_service_ownership(
    monkeypatch: pytest.MonkeyPatch, execution_fails: bool, close_fails: bool
) -> None:
    factory = Mock(spec=ClientBitrixCRM)
    executor = Mock(spec=SyncPlanExecutor)
    monkeypatch.setattr(service_module, "ClientBitrixCRM", factory)
    monkeypatch.setattr(service_module, "SyncPlanExecutor", executor)
    primary, secondary = RuntimeError("Ошибка выполнения"), OSError("Ошибка закрытия")
    executor.return_value.execute.return_value = LoadResult(())
    if execution_fails:
        executor.return_value.execute.side_effect = primary
    if close_fails:
        factory.return_value.close.side_effect = secondary
    service = LoadService(settings())
    factory.assert_not_called()
    plan = SyncPlan(())
    expected = primary if execution_fails else secondary if close_fails else None
    if expected is None:
        assert service.load(plan) == LoadResult(())
    else:
        with pytest.raises(type(expected)) as caught:
            service.load(plan)
        assert caught.value is expected
    factory.assert_called_once_with(gateway_url="http://example.invalid", timeout=180.0)
    executor.return_value.execute.assert_called_once_with(plan)
    factory.return_value.close.assert_called_once_with()


@pytest.mark.parametrize("empty", [False, True])
def test_service_real_components_no_retry_and_safe_logging(
    monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    client = Mock(spec=ClientBitrixCRM)
    factory = Mock(return_value=client)
    monkeypatch.setattr(service_module, "ClientBitrixCRM", factory)
    secret = "Тайный адрес +79999999999 email@example.invalid ИНН token"
    client.add_item.side_effect = [
        11,
        BitrixRequestFailedError(secret),
        BitrixRequestUnknownError(secret),
    ]
    events: Dict[str, Any] = {}
    records: List[Dict[str, Any]] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.__dict__)

    logger = logging.getLogger("nashdom_sync.load")
    previous = logger.level
    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    plan = (
        SyncPlan(())
        if empty
        else SyncPlan(
            (
                PlannedOperation("ok", AddItemCommand(4, {"TITLE": secret})),
                PlannedOperation("failed", AddItemCommand(4, {"TITLE": secret})),
                PlannedOperation("unknown", AddItemCommand(4, {"TITLE": secret})),
                PlannedOperation("blocked", AddAddressCommand({}), dependencies=("failed",)),
            )
        )
    )
    try:
        result = LoadService(settings()).load(plan)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert secret not in repr(records)
    for record in records:
        events[str(record["msg"])] = record
    assert "load_started" in events and "load_completed" in events
    completed = events["load_completed"][DETAILS_ATTRIBUTE]
    assert result.is_successful is empty
    assert client.add_item.call_count == (0 if empty else 3)
    client.add_address.assert_not_called()
    client.close.assert_called_once_with()
    assert completed["duration_seconds"] >= 0
    assert completed["operations"] == (0 if empty else 4)
    for status in ("success", "failed", "unknown", "blocked"):
        assert completed[status] == (0 if empty else 1)
    for record in records:
        assert "payload" not in record[DETAILS_ATTRIBUTE]
        assert "fields" not in record[DETAILS_ATTRIBUTE]
    if not empty:
        assert "load_operation_failed" in events
        assert "load_operation_blocked" in events
        assert "BitrixRequestUnknownError" in repr(records)


@pytest.mark.parametrize("error_type", [BitrixGatewayError, RuntimeError])
def test_service_failure_log_preserves_primary(
    monkeypatch: pytest.MonkeyPatch, error_type: Type[Exception]
) -> None:
    error = error_type("Секретная ошибка")
    factory = Mock(side_effect=error)
    monkeypatch.setattr(service_module, "ClientBitrixCRM", factory)
    log = Mock()

    def emit(*args: Any, **kwargs: Any) -> None:
        if args[2] == "load_failed":
            assert kwargs["exception_type"] == error_type.__name__
            assert "Секретная ошибка" not in repr(kwargs)
            raise OSError("Вторичная ошибка диагностики")

    log.side_effect = emit
    monkeypatch.setattr(service_module, "log_event", log)
    with pytest.raises(error_type) as caught:
        LoadService(settings()).load(SyncPlan(()))
    assert caught.value is error
    assert log.call_count == 2


@pytest.mark.parametrize("failed_sibling", [False, True])
def test_sibling_after_failed_sibling_still_runs(failed_sibling: bool) -> None:
    client = Mock(spec=ClientBitrixCRM)
    client.add_item.return_value = 101
    client.add_requisite.side_effect = (
        BitrixRequestFailedError("Ошибка реквизитов")
        if failed_sibling
        else BitrixRequestUnknownError("Неизвестный результат реквизитов")
    )
    plan = SyncPlan(
        (
            PlannedOperation("parent", AddItemCommand(4, {})),
            PlannedOperation(
                "sibling1", AddRequisiteCommand({}), (RuntimeBinding("OWNER", "parent"),)
            ),
            PlannedOperation(
                "sibling2", AddAddressCommand({}), (RuntimeBinding("OWNER", "parent"),)
            ),
        )
    )
    result = SyncPlanExecutor(RuntimeBindingResolver(), CrmCommandExecutor(client)).execute(plan)
    assert result.operations[2].status is OperationStatus.SUCCESS
    client.add_address.assert_called_once_with({"OWNER": 101})


def test_binding_to_success_without_id_aborts_before_next_write() -> None:
    client = Mock(spec=ClientBitrixCRM)
    plan = SyncPlan(
        (
            PlannedOperation("address", AddAddressCommand({})),
            PlannedOperation(
                "target", AddRequisiteCommand({}), (RuntimeBinding("OWNER", "address"),)
            ),
        )
    )
    with pytest.raises(LoadInvariantError, match="crm_id"):
        SyncPlanExecutor(RuntimeBindingResolver(), CrmCommandExecutor(client)).execute(plan)
    client.add_address.assert_called_once_with({})
    client.add_requisite.assert_not_called()


def test_service_component_construction_failure_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock(spec=ClientBitrixCRM)
    monkeypatch.setattr(service_module, "ClientBitrixCRM", Mock(return_value=client))
    error = RuntimeError("Ошибка создания исполнителя")
    monkeypatch.setattr(service_module, "SyncPlanExecutor", Mock(side_effect=error))
    with pytest.raises(RuntimeError) as caught:
        LoadService(settings()).load(SyncPlan(()))
    assert caught.value is error
    client.close.assert_called_once_with()


def test_service_interruption_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock(spec=ClientBitrixCRM)
    monkeypatch.setattr(service_module, "ClientBitrixCRM", Mock(return_value=client))
    client.add_item.side_effect = KeyboardInterrupt()
    client.close.side_effect = OSError("Ошибка закрытия")
    with pytest.raises(KeyboardInterrupt):
        LoadService(settings()).load(SyncPlan((PlannedOperation("a", AddItemCommand(4, {})),)))
    client.close.assert_called_once_with()
