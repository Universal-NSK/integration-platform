# pyright: reportPrivateUsage=false
import logging
from dataclasses import FrozenInstanceError, asdict
from typing import Any, Dict, List, Tuple, Type, cast
from unittest.mock import Mock, call

import pytest
from nashdom_sync.bitrix_crm import ClientBitrixCRM
from nashdom_sync.bitrix_crm.exceptions import (
    BitrixGatewayError,
    BitrixRequestFailedError,
)
from nashdom_sync.contracts.crm import CrmEmployee, ExistingCrmEntity
from nashdom_sync.contracts.settings import BitrixClientSettings, RegionSettings
from nashdom_sync.providers.crm_provider import (
    CrmAmbiguousSemanticError,
    CrmInvalidDataError,
    CrmMissingSemanticError,
    CrmProvider,
    CrmProviderError,
)
from nashdom_sync.providers.crm_provider.fields import (
    COMPANY_GROUP_FIELDS,
    DEVELOPER_FIELDS,
    LEAD_FIELDS,
    FieldSpec,
)


def metadata(specs: Dict[str, FieldSpec]) -> Dict[str, Any]:
    # Ключи намеренно отличаются от известных UF_CRM: разрешение обязано идти по title.
    return {f"resolved_{key}": {"title": spec.title} for key, spec in specs.items()}


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> Tuple[CrmProvider, Mock, Mock]:
    client = Mock(spec=ClientBitrixCRM)
    constructor = Mock(return_value=client)
    monkeypatch.setattr("nashdom_sync.providers.crm_provider.provider.ClientBitrixCRM", constructor)
    provider = CrmProvider(BitrixClientSettings(gateway_url="http://gateway.invalid", timeout=3))
    provider._client = client
    client.list_owner_types.return_value = [{"ID": "1050", "NAME": "Группа компаний"}]

    def get_fields(entity: int) -> Dict[str, Any]:
        return {
            1: metadata(LEAD_FIELDS),
            4: metadata(DEVELOPER_FIELDS),
            1050: metadata(COMPANY_GROUP_FIELDS),
        }[entity]

    def statuses(entity: str) -> List[Dict[str, Any]]:
        return {
            "SOURCE": [{"NAME": "наш.дом.рф", "STATUS_ID": "SRC", "ID": "999"}],
            "INDUSTRY": [{"NAME": "Застройщик", "STATUS_ID": "DEV"}],
            "COMPANY_TYPE": [{"NAME": "Партнер", "STATUS_ID": "PARTNER"}],
        }[entity]

    def items(entity: int, select: List[str]) -> List[Dict[str, Any]]:
        return [{"id": entity + 10, select[1]: "42.00"}]

    client.get_item_fields.side_effect = get_fields
    client.list_statuses.side_effect = statuses
    client.list_requisite_presets.return_value = [{"NAME": "Организация", "ID": "1"}]
    client.list_address_types.return_value = [
        {"NAME": "Фактический адрес", "ID": 1},
        {"NAME": "Юридический адрес", "ID": 6},
    ]
    client.list_items.side_effect = items
    client.search_users.return_value = [
        {
            "ID": "7",
            "LAST_NAME": "Иванов",
            "NAME": "Иван",
            "SECOND_NAME": "Иванович",
            "ACTIVE": True,
            "USER_TYPE": "employee",
        }
    ]
    return provider, client, constructor


def region() -> RegionSettings:
    return RegionSettings(
        default_assigned_by_name="Иванов Иван Иванович",
        assignment={1: "Иванов Иван Иванович"},
    )


@pytest.mark.parametrize(
    "raw,reason",
    [
        ({"new": {"title": "Поле"}, "old": {"upperName": "UF"}}, None),
        ({"new": {"title": "Переименовано", "upperName": "UF"}}, "title_missing"),
        (
            {"new": {"title": "Поле", "upperName": "UF"}, "other": {"title": "Поле"}},
            "title_ambiguous",
        ),
    ],
)
def test_resolve_field(
    setup: Tuple[CrmProvider, Mock, Mock],
    caplog: pytest.LogCaptureFixture,
    raw: Dict[str, Any],
    reason: Any,
) -> None:
    provider, _, _ = setup
    with caplog.at_level(logging.WARNING):
        assert provider._resolve_fields(raw, {"binding": FieldSpec("Поле", "UF")}) == {
            "binding": "new"
        }
    if reason is None:
        assert not caplog.records
    else:
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert record.message == "crm_field_upper_name_fallback"
        assert reason in str(record.__dict__)


@pytest.mark.parametrize(
    "raw,fallback,error",
    [
        ({}, "UF", CrmMissingSemanticError),
        (
            {"a": {"title": "Поле"}, "b": {"title": "Поле"}},
            "UF",
            CrmAmbiguousSemanticError,
        ),
        (
            {"a": {"upperName": "UF"}, "b": {"upperName": "UF"}},
            "UF",
            CrmAmbiguousSemanticError,
        ),
        ({}, None, CrmMissingSemanticError),
        (
            {"a": {"title": "Поле"}, "b": {"title": "Поле"}},
            None,
            CrmAmbiguousSemanticError,
        ),
        (
            {
                "a": {"title": "Поле"},
                "b": {"title": "Поле"},
                "outside": {"upperName": "UF"},
            },
            "UF",
            CrmAmbiguousSemanticError,
        ),
        (
            {
                "a": {"title": "Поле", "upperName": "UF"},
                "b": {"title": "Поле", "upperName": "UF"},
            },
            "UF",
            CrmAmbiguousSemanticError,
        ),
        ({"a": None}, "UF", CrmInvalidDataError),
    ],
)
def test_resolver_errors(
    setup: Tuple[CrmProvider, Mock, Mock],
    raw: Dict[str, Any],
    fallback: Any,
    error: Type[CrmProviderError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(error):
        setup[0]._resolve_fields(raw, {"binding": FieldSpec("Поле", fallback)})
    assert not caplog.records


def test_bindings_and_defaults(setup: Tuple[CrmProvider, Mock, Mock]) -> None:
    structure = setup[0]._build_structure()
    fields = structure.entity_fields
    for specs, binding in (
        (LEAD_FIELDS, fields.lead),
        (DEVELOPER_FIELDS, fields.developer),
        (COMPANY_GROUP_FIELDS, fields.company_group),
    ):
        for key in specs:
            assert getattr(binding, key) == f"resolved_{key}"
    assert fields.lead.company_group_bitrix_id == "parentId1050"
    assert fields.lead.title == fields.developer.title == fields.company_group.title == "title"
    assert (
        fields.lead.assigned_by_id
        == fields.developer.assigned_by_id
        == fields.company_group.assigned_by_id
        == "assignedById"
    )
    assert fields.lead.source_id == fields.company_group.source_id == "sourceId"
    assert fields.lead.company_id == "companyId"
    assert fields.developer.company_type == "typeId"
    assert fields.developer.industry == "industry"
    assert fields.developer.multifield == "fm"
    assert asdict(fields.requisite) == dict(
        zip(
            (
                "entity_type_id",
                "entity_id_to_bind",
                "preset_id",
                "card_name",
                "details_name",
                "full_name",
                "inn",
                "kpp",
                "ogrn",
            ),
            (
                "ENTITY_TYPE_ID",
                "ENTITY_ID",
                "PRESET_ID",
                "NAME",
                "RQ_COMPANY_NAME",
                "RQ_COMPANY_FULL_NAME",
                "RQ_INN",
                "RQ_KPP",
                "RQ_OGRN",
            ),
        )
    )
    assert asdict(fields.address) == {
        "address_type_id": "TYPE_ID",
        "entity_type_id_to_bind": "ENTITY_TYPE_ID",
        "entity_id_to_bind": "ENTITY_ID",
        "address": "ADDRESS_2",
    }
    assert asdict(fields.multifield) == {
        "value_type": "valueType",
        "value": "value",
        "type_id": "typeId",
    }


@pytest.mark.parametrize("source", [42, "42", 42.0, "42.00"])
def test_existing_normalization(setup: Tuple[CrmProvider, Mock, Mock], source: Any) -> None:
    provider, client, _ = setup
    client.list_items.side_effect = None
    client.list_items.return_value = [{"id": "7", "external": source}]
    assert provider._load_existing_entities(4, "external") == (ExistingCrmEntity(42, 7),)
    client.list_items.assert_called_once_with(4, select=["id", "external"])


@pytest.mark.parametrize(
    "records",
    [
        [{"id": 1, "s": 3}, {"id": 2, "s": "3.00"}],
        [{"id": 1, "s": 3}, {"id": 1, "s": 3}],
        [{"s": 1}],
        [{"id": 1}],
        [{"id": True, "s": 1}],
        [{"id": 1.0, "s": 1}],
        [{"id": 0, "s": 1}],
        [{"id": "bad", "s": 1}],
        *[
            [{"id": 1, "s": value}]
            for value in (
                None,
                True,
                0,
                -1,
                1.5,
                "1.5",
                "",
                "nan",
                float("nan"),
                float("inf"),
                cast(List[Any], []),
                2**53 * 1.0,
            )
        ],
    ],
)
def test_existing_invalid(setup: Tuple[CrmProvider, Mock, Mock], records: Any) -> None:
    provider, client, _ = setup
    client.list_items.side_effect = None
    client.list_items.return_value = records
    with pytest.raises(CrmInvalidDataError):
        provider._load_existing_entities(1, "s")


def test_managers_deduplicate_and_normalize(
    setup: Tuple[CrmProvider, Mock, Mock],
) -> None:
    provider, client, _ = setup
    assert provider._build_managers(region()) == (CrmEmployee("Иванов Иван Иванович", 7),)
    client.search_users.assert_called_once_with("Иванов Иван Иванович")
    name = "  ИВАНОВ   Иван\tИванович "
    assert provider._resolve_manager(name) == CrmEmployee(name, 7)
    client.search_users.return_value = [{"ID": 8, "LAST_NAME": "Петров", "NAME": "Петр"}]
    assert provider._resolve_manager("Петров Петр") == CrmEmployee("Петров Петр", 8)


@pytest.mark.parametrize(
    "candidates,error",
    [
        ([], CrmMissingSemanticError),
        ([{"ID": 1, "NAME": "Другой"}], CrmMissingSemanticError),
        (
            [{"ID": 1, "NAME": "Иван"}, {"ID": 2, "NAME": "Иван"}],
            CrmAmbiguousSemanticError,
        ),
        ([{"ID": 1, "NAME": "Иван", "ACTIVE": "N"}], CrmMissingSemanticError),
        ([{"ID": 1, "NAME": "Иван", "USER_TYPE": "extranet"}], CrmMissingSemanticError),
        ([{"ID": False, "NAME": "Иван"}], CrmInvalidDataError),
        ([{"ID": 1, "NAME": 5}], CrmInvalidDataError),
    ],
)
def test_manager_errors(
    setup: Tuple[CrmProvider, Mock, Mock],
    candidates: Any,
    error: Type[CrmProviderError],
) -> None:
    setup[1].search_users.return_value = candidates
    with pytest.raises(error):
        setup[0]._resolve_manager("Иван")


@pytest.mark.parametrize(
    "method",
    [
        "list_owner_types",
        "list_statuses",
        "list_requisite_presets",
        "list_address_types",
    ],
)
@pytest.mark.parametrize("ambiguous", [False, True])
def test_semantic_errors(
    setup: Tuple[CrmProvider, Mock, Mock], method: str, ambiguous: bool
) -> None:
    provider, client, _ = setup
    operation = getattr(client, method)
    records = operation("SOURCE") if method == "list_statuses" else operation()
    operation.side_effect = None
    operation.return_value = records * 2 if ambiguous else []
    error = CrmAmbiguousSemanticError if ambiguous else CrmMissingSemanticError
    with pytest.raises(error):
        if method == "list_owner_types":
            provider._resolve_entity_type_ids()
        else:
            provider._build_references()


def test_provide_complete_and_repeatable(setup: Tuple[CrmProvider, Mock, Mock]) -> None:
    provider, client, constructor = setup
    result = provider.provide(region())
    constructor.assert_called_once_with(gateway_url="http://gateway.invalid", timeout=3)
    assert asdict(result.structure.entity_types) == {
        "lead": 1,
        "company": 4,
        "company_group": 1050,
        "requisite": 8,
    }
    assert result.references.source_id == "SRC"
    assert result.references.developer_industry_id == "DEV"
    assert result.references.developer_company_type_id == "PARTNER"
    assert result.references.organization_requisite_preset_id == 1
    assert result.references.address_types.actual == 1
    assert result.references.address_types.legal == 6
    assert asdict(result.references.building_type) == {
        "residential": "Жилое",
        "non_residential": "Нежилое",
    }
    assert asdict(result.references.multifield) == {
        "value_type": "WORK",
        "phone_type_id": "PHONE",
        "email_type_id": "EMAIL",
        "web_type_id": "WEB",
    }
    assert result.existing.leads == (ExistingCrmEntity(42, 11),)
    assert result.existing.developers == (ExistingCrmEntity(42, 14),)
    assert result.existing.company_groups == (ExistingCrmEntity(42, 1060),)
    assert result.managers == (CrmEmployee("Иванов Иван Иванович", 7),)
    assert client.list_items.call_args_list == [
        call(1, select=["id", "resolved_source_building_id"]),
        call(4, select=["id", "resolved_source_developer_id"]),
        call(1050, select=["id", "resolved_source_company_group_id"]),
    ]
    with pytest.raises(FrozenInstanceError):
        result.managers = ()  # pyright: ignore[reportAttributeAccessIssue]
    client.close.assert_called_once_with()
    assert provider.provide(region()) == result
    assert constructor.call_count == client.close.call_count == 2


@pytest.mark.parametrize(
    "method",
    [
        "list_owner_types",
        "get_item_fields",
        "list_statuses",
        "list_items",
        "search_users",
    ],
)
def test_provide_failure_closes_client(setup: Tuple[CrmProvider, Mock, Mock], method: str) -> None:
    provider, client, _ = setup
    getattr(client, method).side_effect = CrmInvalidDataError("invalid mandatory block")
    with pytest.raises(CrmInvalidDataError, match="mandatory block"):
        provider.provide(region())
    client.close.assert_called_once_with()


@pytest.mark.parametrize("error", [BitrixGatewayError, BitrixRequestFailedError])
@pytest.mark.parametrize(
    "method",
    [
        "list_owner_types",
        "get_item_fields",
        "list_statuses",
        "list_items",
        "search_users",
    ],
)
def test_client_failure_is_domain_error(
    setup: Tuple[CrmProvider, Mock, Mock], error: Type[Exception], method: str
) -> None:
    provider, client, _ = setup
    cause = error("transport error")
    getattr(client, method).side_effect = cause
    with pytest.raises(CrmProviderError) as caught:
        provider.provide(region())
    assert not isinstance(caught.value, CrmInvalidDataError)
    assert caught.value.__cause__ is cause
    if error is BitrixGatewayError:
        assert str(caught.value) == "CRM: недоступен Gateway или нарушен контракт ответа"
    client.close.assert_called_once_with()


def test_managers_include_assignment_names(setup: Tuple[CrmProvider, Mock, Mock]) -> None:
    provider, client, _ = setup
    client.search_users.side_effect = [
        [{"ID": "1", "LAST_NAME": "Иванов", "NAME": "Иван"}],
        [{"ID": "2", "LAST_NAME": "Петров", "NAME": "Петр"}],
    ]
    settings = RegionSettings(
        default_assigned_by_name="Иванов Иван",
        assignment={1: "Петров Петр", 2: "Иванов Иван", 3: "Петров Петр"},
    )
    assert provider._build_managers(settings) == (
        CrmEmployee("Иванов Иван", 1),
        CrmEmployee("Петров Петр", 2),
    )
    assert client.search_users.call_args_list == [call("Иванов Иван"), call("Петров Петр")]


@pytest.mark.parametrize(
    "method,records",
    [
        ("list_owner_types", [{"NAME": "Группа компаний", "ID": True}]),
        ("list_statuses", [{"NAME": "наш.дом.рф", "ID": "42"}]),
        ("list_requisite_presets", [{"NAME": "Организация", "ID": 0}]),
        (
            "list_address_types",
            [
                {"NAME": "Фактический адрес", "ID": "bad"},
                {"NAME": "Юридический адрес", "ID": 6},
            ],
        ),
    ],
)
def test_semantic_invalid_ids(
    setup: Tuple[CrmProvider, Mock, Mock], method: str, records: List[Dict[str, Any]]
) -> None:
    provider, client, _ = setup
    operation = getattr(client, method)
    if method == "list_statuses":
        original = operation.side_effect

        def statuses(entity: str) -> List[Dict[str, Any]]:
            return records if entity == "SOURCE" else original(entity)

        operation.side_effect = statuses
    else:
        operation.return_value = records
    with pytest.raises(CrmInvalidDataError):
        if method == "list_owner_types":
            provider._resolve_entity_type_ids()
        else:
            provider._build_references()
