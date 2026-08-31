from dataclasses import replace
from datetime import date
from typing import Optional

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
)
from nashdom_sync.extract import SourceDataValidationError, SourceDataValidator


def _object(
    object_id: int = 1,
    region_id: int = 22,
    developer_id: int = 38039,
    company_group_id: Optional[int] = None,
) -> ExtractedObject:
    return ExtractedObject(
        id=object_id,
        title=f"Объект {object_id}",
        address="Город Барнаул",
        region_id=region_id,
        publication_date=date(2026, 8, 21),
        commissioning_period=CommissioningPeriod(2028, 4),
        object_type=ExtractedObjectTypeEnum.RESIDENTIAL,
        developer_id=developer_id,
        company_group_id=company_group_id,
    )


def _developer(
    developer_id: int = 38039,
    company_group_id: Optional[int] = None,
) -> ExtractedDeveloper:
    return ExtractedDeveloper(
        id=developer_id,
        short_name=f"Застройщик {developer_id}",
        full_name=f"Полное имя застройщика {developer_id}",
        inn="7701651356",
        kpp="720301001",
        ogrn="1067746424899",
        region_id=72,
        legal_address="Юридический адрес",
        fact_address="Фактический адрес",
        contact_name="Иванов Иван Иванович",
        phone="+70000000000",
        email="developer@example.test",
        url=None,
        company_group_id=company_group_id,
    )


def test_duplicate_object_ids_fail() -> None:
    objects = [_object(1), replace(_object(2), id=1)]

    with pytest.raises(SourceDataValidationError, match="повторяются ID объектов: 1"):
        SourceDataValidator().validate_objects(objects, {22})


def test_unexpected_region_fails() -> None:
    with pytest.raises(SourceDataValidationError, match="незапрошенных регионов: 54"):
        SourceDataValidator().validate_objects([_object(region_id=54)], {22})


def test_empty_object_list_is_valid() -> None:
    SourceDataValidator().validate_objects([], {22})


def test_exact_developer_set_is_valid() -> None:
    SourceDataValidator().validate_developers(
        [_developer(306), _developer(16750)],
        {306, 16750},
    )


def test_duplicate_developer_ids_fail() -> None:
    with pytest.raises(
        SourceDataValidationError,
        match="повторяются ID застройщиков: 306",
    ):
        SourceDataValidator().validate_developers(
            [_developer(306), _developer(306)],
            {306},
        )


def test_unexpected_developer_id_fails() -> None:
    with pytest.raises(
        SourceDataValidationError,
        match="незапрошенных застройщиков: 999",
    ):
        SourceDataValidator().validate_developers([_developer(999)], {306})


def test_missing_developer_id_fails() -> None:
    with pytest.raises(
        SourceDataValidationError,
        match="не вернул запрошенных застройщиков: 16750",
    ):
        SourceDataValidator().validate_developers([_developer(306)], {306, 16750})


def test_empty_expected_and_empty_developers_are_valid() -> None:
    SourceDataValidator().validate_developers([], set())


@pytest.mark.parametrize(
    "object_group_id, developer_group_id",
    [
        (5776, 5776),
        (None, 5776),
        (5776, None),
    ],
)
def test_compatible_company_group_sources_are_valid(
    object_group_id: Optional[int],
    developer_group_id: Optional[int],
) -> None:
    SourceDataValidator().validate_company_group_consistency(
        [_object(company_group_id=object_group_id)],
        [_developer(company_group_id=developer_group_id)],
    )


def test_conflicting_object_and_developer_company_groups_fail() -> None:
    with pytest.raises(SourceDataValidationError, match="группой 9999.*группой 5776"):
        SourceDataValidator().validate_company_group_consistency(
            [_object(company_group_id=5776)],
            [_developer(company_group_id=9999)],
        )


def test_conflicting_company_groups_across_same_developer_objects_fail() -> None:
    with pytest.raises(
        SourceDataValidationError,
        match="разные группы компаний: 38039: 5776, 9999",
    ):
        SourceDataValidator().validate_company_group_consistency(
            [
                _object(object_id=1, company_group_id=5776),
                _object(object_id=2, company_group_id=9999),
            ],
            [_developer(company_group_id=5776)],
        )
