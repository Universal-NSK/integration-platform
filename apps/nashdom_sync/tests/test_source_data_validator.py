from dataclasses import replace
from datetime import date

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedObject,
    ExtractedObjectTypeEnum,
)
from nashdom_sync.extract import SourceDataValidationError, SourceDataValidator


def _object(object_id: int = 1, region_id: int = 22) -> ExtractedObject:
    return ExtractedObject(
        id=object_id,
        title=f"Объект {object_id}",
        address="Город Барнаул",
        region_id=region_id,
        publication_date=date(2026, 8, 21),
        commissioning_period=CommissioningPeriod(2028, 4),
        object_type=ExtractedObjectTypeEnum.RESIDENTIAL,
        developer_id=38039,
        company_group_id=None,
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
