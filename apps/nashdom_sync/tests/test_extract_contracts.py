from dataclasses import replace
from datetime import date
from typing import Optional

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
    ExtractResult,
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


def _extracted_developer() -> ExtractedDeveloper:
    return ExtractedDeveloper(
        id=306,
        short_name="2МЕН ГРУПП",
        full_name="2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
        inn="7701651356",
        kpp="720301001",
        ogrn="1067746424899",
        region_id=72,
        legal_address="Тюменская область, Город Тюмень, Улица Республики дом 143А",
        fact_address=("Тюменская обл, г.о. город Тюмень, г. Тюмень, ул. Республики, д.143А"),
        contact_name="Шулепов Петр Владимирович",
        phone="+79091697719",
        email="2men-group@mail.ru",
        url="2mengroup.ru",
        company_group_id=5776,
    )


def _extracted_company_group() -> ExtractedCompanyGroup:
    return ExtractedCompanyGroup(
        id=5776,
        name="2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
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


def test_extracted_developer_accepts_valid_values() -> None:
    developer = _extracted_developer()

    assert developer.id == 306
    assert developer.url == "2mengroup.ru"
    assert developer.company_group_id == 5776


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("id", 0),
        ("id", True),
        ("region_id", -1),
        ("company_group_id", 0),
    ],
)
def test_extracted_developer_rejects_invalid_positive_ids(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError):
        replace(_extracted_developer(), **{field_name: invalid_value})


@pytest.mark.parametrize(
    "field_name",
    [
        "short_name",
        "full_name",
        "inn",
        "kpp",
        "ogrn",
        "legal_address",
        "fact_address",
        "contact_name",
        "phone",
        "email",
    ],
)
def test_extracted_developer_rejects_empty_required_text(field_name: str) -> None:
    with pytest.raises(ValueError):
        replace(_extracted_developer(), **{field_name: "  "})


def test_extracted_developer_accepts_optional_none_values() -> None:
    developer = replace(
        _extracted_developer(),
        url=None,
        company_group_id=None,
    )

    assert developer.url is None
    assert developer.company_group_id is None


def test_extracted_developer_accepts_nonempty_url_and_rejects_empty_url() -> None:
    assert replace(_extracted_developer(), url="example.test").url == "example.test"

    with pytest.raises(ValueError):
        replace(_extracted_developer(), url="  ")


def test_extracted_developer_to_dict_is_stable() -> None:
    result = _extracted_developer().to_dict()

    assert result == {
        "id": 306,
        "short_name": "2МЕН ГРУПП",
        "full_name": "2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
        "inn": "7701651356",
        "kpp": "720301001",
        "ogrn": "1067746424899",
        "region_id": 72,
        "legal_address": ("Тюменская область, Город Тюмень, Улица Республики дом 143А"),
        "fact_address": ("Тюменская обл, г.о. город Тюмень, г. Тюмень, ул. Республики, д.143А"),
        "contact_name": "Шулепов Петр Владимирович",
        "phone": "+79091697719",
        "email": "2men-group@mail.ru",
        "url": "2mengroup.ru",
        "company_group_id": 5776,
    }


def test_extracted_company_group_accepts_valid_values() -> None:
    company_group = _extracted_company_group()

    assert company_group.id == 5776
    assert company_group.name == "2МЕН ГРУПП ДЕВЕЛОПМЕНТ"


@pytest.mark.parametrize("invalid_id", [0, -1, True])
def test_extracted_company_group_rejects_invalid_id(invalid_id: object) -> None:
    with pytest.raises(ValueError):
        replace(_extracted_company_group(), id=invalid_id)


@pytest.mark.parametrize("invalid_name", ["", "  "])
def test_extracted_company_group_rejects_empty_name(invalid_name: str) -> None:
    with pytest.raises(ValueError):
        replace(_extracted_company_group(), name=invalid_name)


def test_extracted_company_group_to_dict_is_stable() -> None:
    assert _extracted_company_group().to_dict() == {
        "id": 5776,
        "name": "2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
    }


def test_extract_result_serializes_typed_company_groups() -> None:
    result = ExtractResult(
        objects=[_extracted_object()],
        developers=[_extracted_developer()],
        company_groups=[_extracted_company_group()],
    )

    assert result.to_dict()["company_groups"] == [{"id": 5776, "name": "2МЕН ГРУПП ДЕВЕЛОПМЕНТ"}]
