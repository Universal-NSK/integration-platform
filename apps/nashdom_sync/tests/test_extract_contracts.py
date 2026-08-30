from dataclasses import replace
from datetime import date
from typing import Optional

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedObject,
    ExtractedObjectTypeEnum,
)


def _extracted_object() -> ExtractedObject:
    return ExtractedObject(
        id=73232,
        title='Жилой комплекс "Пушкина, 16"',
        address="Город Барнаул, Улица Пушкина, д. 16",
        region_id=22,
        publication_date=date(2026, 8, 21),
        commissioning_period=CommissioningPeriod(
            year=2028,
            quarter=4,
            exact_date=date(2028, 12, 31),
        ),
        object_type=ExtractedObjectTypeEnum.RESIDENTIAL,
        developer_id=38039,
        company_group_id=None,
    )


def test_commissioning_period_accepts_matching_exact_date() -> None:
    period = CommissioningPeriod(
        year=2027,
        quarter=2,
        exact_date=date(2027, 6, 30),
    )

    assert str(period) == "2027, квартал 2"


@pytest.mark.parametrize(
    "year, quarter, exact_date",
    [
        (0, 1, None),
        (2027, 0, None),
        (2027, 5, None),
        (2027, 2, date(2028, 6, 30)),
        (2027, 2, date(2027, 9, 30)),
    ],
)
def test_commissioning_period_rejects_broken_invariants(
    year: int,
    quarter: int,
    exact_date: Optional[date],
) -> None:
    with pytest.raises(ValueError):
        CommissioningPeriod(
            year=year,
            quarter=quarter,
            exact_date=exact_date,
        )


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("id", 0),
        ("title", "  "),
        ("address", ""),
        ("region_id", -1),
        ("developer_id", 0),
        ("company_group_id", -1),
    ],
)
def test_extracted_object_rejects_broken_invariants(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError):
        replace(_extracted_object(), **{field_name: invalid_value})


def test_to_dict_serializes_value_object_date_and_enum_stably() -> None:
    result = _extracted_object().to_dict()

    assert result["publication_date"] == "2026-08-21"
    assert result["commissioning_period"] == "2028, квартал 4"
    assert result["object_type"] == "Жилое"
