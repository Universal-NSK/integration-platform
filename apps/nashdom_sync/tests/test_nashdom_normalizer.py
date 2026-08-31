import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, cast

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
)
from nashdom_sync.extract import NashDomDataNormalizer, NashDomNormalizationError

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PUBLICATION_PATHS = (("publicationDate",), ("objPublDt",))


def _fixture(name: str) -> Dict[str, Any]:
    raw = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(Dict[str, Any], raw)


def _raw_developer_306() -> Dict[str, Any]:
    return {
        "devId": 306,
        "devShortCleanNm": "2МЕН ГРУПП",
        "devFullCleanNm": "2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
        "devInn": "7701651356",
        "devKpp": "720301001",
        "devOgrn": "1067746424899",
        "devOrgRegRegionCd": 72,
        "devLegalAddr": (
            "Тюменская область, Город Тюмень, Улица Республики дом 143А"
        ),
        "devFactAddr": (
            "Тюменская обл, г.о. город Тюмень, г. Тюмень, "
            "ул. Республики, д.143А"
        ),
        "devEmplMainFullNm": "Шулепов Петр Владимирович",
        "devPhoneNum": "+79091697719",
        "devEmail": "2men-group@mail.ru",
        "devSite": "2mengroup.ru",
        "companyGroupId": 5776,
    }


def _raw_developer_16750() -> Dict[str, Any]:
    return {
        "devId": 16750,
        "devShortCleanNm": "CЗ ФЕМИЛИ РЕЗОРТ НЕБУГ",
        "devFullCleanNm": (
            "СПЕЦИАЛИЗИРОВАННЫЙ ЗАСТРОЙЩИК ФЕМИЛИ РЕЗОРТ НЕБУГ"
        ),
        "devInn": "2308288843",
        "devKpp": "230801001",
        "devOgrn": "1222300064931",
        "devOrgRegRegionCd": 23,
        "devLegalAddr": (
            "Краснодарский край, город Краснодар, улица Северная дом д191 "
            "помещение помещ38офис12"
        ),
        "devFactAddr": (
            "Краснодарский край, Краснодар, Северная, д.д191, "
            "пом.помещ38офис12"
        ),
        "devEmplMainFullNm": "Овчинников Михаил Юрьевич",
        "devPhoneNum": "+79889574354",
        "devEmail": "metrix.maisky@yandex.ru",
        "devSite": "metriks.ru",
    }


def test_normalizes_xhr_fixture_to_expected_object() -> None:
    result = NashDomDataNormalizer().normalize_objects(
        [_fixture("nashdom_xhr_object.json")]
    )

    assert result == [
        ExtractedObject(
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
    ]


def test_normalizes_ssr_fixture_to_equivalent_canonical_object() -> None:
    normalizer = NashDomDataNormalizer()
    ssr_object = normalizer.normalize_objects([_fixture("nashdom_ssr_object.json")])[0]
    xhr_object = normalizer.normalize_objects([_fixture("nashdom_xhr_object.json")])[0]

    assert ssr_object.id == xhr_object.id
    assert ssr_object.title == xhr_object.title
    assert ssr_object.address == xhr_object.address
    assert ssr_object.region_id == xhr_object.region_id
    assert ssr_object.publication_date == xhr_object.publication_date
    assert str(ssr_object.commissioning_period) == str(xhr_object.commissioning_period)
    assert ssr_object.commissioning_period.exact_date is None
    assert xhr_object.commissioning_period.exact_date == date(2028, 12, 31)
    assert ssr_object.object_type == xhr_object.object_type
    assert ssr_object.developer_id == xhr_object.developer_id
    assert ssr_object.company_group_id == xhr_object.company_group_id


def test_xhr_null_title_falls_back_to_normalized_address() -> None:
    raw_object = _fixture("nashdom_xhr_object.json")
    raw_object["objAddr"] = "  Город Барнаул, Улица Пушкина, д. 16  "
    raw_object["objCommercNm"] = None

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.title == "Город Барнаул, Улица Пушкина, д. 16"
    assert result.title == result.address


def test_ssr_null_title_falls_back_to_address() -> None:
    raw_object = _fixture("nashdom_ssr_object.json")
    raw_object["objCommercNm"] = None

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.title == result.address


def test_missing_title_falls_back_to_address() -> None:
    raw_object = _fixture("nashdom_xhr_object.json")
    del raw_object["objCommercNm"]

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.title == result.address


def test_whitespace_only_title_falls_back_to_address() -> None:
    raw_object = _fixture("nashdom_xhr_object.json")
    raw_object["objCommercNm"] = " \t\r\n "

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.title == result.address


@pytest.mark.parametrize("invalid_title", [123, [], {}])
def test_invalid_title_type_is_normalization_error(invalid_title: object) -> None:
    raw_object = _fixture("nashdom_xhr_object.json")
    raw_object["objCommercNm"] = invalid_title

    with pytest.raises(NashDomNormalizationError, match="Название объекта должно быть строкой"):
        NashDomDataNormalizer().normalize_objects([raw_object])


def test_non_empty_title_preserves_commercial_name() -> None:
    raw_object = _fixture("nashdom_xhr_object.json")
    raw_object["objCommercNm"] = "  Коммерческое название  "

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.title == "Коммерческое название"
    assert result.title != result.address


def test_resolver_returns_single_source_value() -> None:
    result = NashDomDataNormalizer._resolve_value(  # pyright: ignore[reportPrivateUsage]
        {"objPublDt": "2026-08-21"},
        _PUBLICATION_PATHS,
        "дата публикации",
        value_normalizer=NashDomDataNormalizer._normalize_publication_date,  # pyright: ignore[reportPrivateUsage]
    )

    assert result == "2026-08-21"


def test_resolver_accepts_multiple_semantically_equal_values() -> None:
    result = NashDomDataNormalizer._resolve_value(  # pyright: ignore[reportPrivateUsage]
        {
            "publicationDate": "21.08.2026",
            "objPublDt": "2026-08-21",
        },
        _PUBLICATION_PATHS,
        "дата публикации",
        value_normalizer=NashDomDataNormalizer._normalize_publication_date,  # pyright: ignore[reportPrivateUsage]
    )

    assert result == "21.08.2026"


def test_resolver_rejects_conflicting_values() -> None:
    with pytest.raises(NashDomNormalizationError, match="противоречивые значения"):
        NashDomDataNormalizer._resolve_value(  # pyright: ignore[reportPrivateUsage]
            {
                "publicationDate": "21.08.2026",
                "objPublDt": "2026-08-22",
            },
            _PUBLICATION_PATHS,
            "дата публикации",
            value_normalizer=NashDomDataNormalizer._normalize_publication_date,  # pyright: ignore[reportPrivateUsage]
        )


def test_resolver_rejects_missing_required_value() -> None:
    with pytest.raises(NashDomNormalizationError, match="обязательное поле"):
        NashDomDataNormalizer._resolve_value(  # pyright: ignore[reportPrivateUsage]
            {},
            _PUBLICATION_PATHS,
            "дата публикации",
        )


def test_resolver_returns_none_for_missing_optional_value() -> None:
    result = NashDomDataNormalizer._resolve_value(  # pyright: ignore[reportPrivateUsage]
        {},
        (("developer", "companyGroup"),),
        "ID группы компаний",
        required=False,
    )

    assert result is None


def test_unknown_commissioning_format_is_normalization_error() -> None:
    raw_object = _fixture("nashdom_ssr_object.json")
    raw_object["objReady100PercDt"] = "конец 2028 года"

    with pytest.raises(NashDomNormalizationError, match="Неизвестный формат периода"):
        NashDomDataNormalizer().normalize_objects([raw_object])


def test_normalizes_confirmed_ssr_company_group_path() -> None:
    raw_object = _fixture("nashdom_ssr_object.json")
    developer = cast(Dict[str, Any], raw_object["developer"])
    developer["companyGroup"] = 9315

    result = NashDomDataNormalizer().normalize_objects([raw_object])[0]

    assert result.company_group_id == 9315


def test_normalizes_real_developer_examples_to_exact_canonical_mapping() -> None:
    result = NashDomDataNormalizer().normalize_developers(
        [_raw_developer_306(), _raw_developer_16750()]
    )

    assert result == [
        ExtractedDeveloper(
            id=306,
            short_name="2МЕН ГРУПП",
            full_name="2МЕН ГРУПП ДЕВЕЛОПМЕНТ",
            inn="7701651356",
            kpp="720301001",
            ogrn="1067746424899",
            region_id=72,
            legal_address=(
                "Тюменская область, Город Тюмень, Улица Республики дом 143А"
            ),
            fact_address=(
                "Тюменская обл, г.о. город Тюмень, г. Тюмень, "
                "ул. Республики, д.143А"
            ),
            contact_name="Шулепов Петр Владимирович",
            phone="+79091697719",
            email="2men-group@mail.ru",
            url="2mengroup.ru",
            company_group_id=5776,
        ),
        ExtractedDeveloper(
            id=16750,
            short_name="CЗ ФЕМИЛИ РЕЗОРТ НЕБУГ",
            full_name=(
                "СПЕЦИАЛИЗИРОВАННЫЙ ЗАСТРОЙЩИК ФЕМИЛИ РЕЗОРТ НЕБУГ"
            ),
            inn="2308288843",
            kpp="230801001",
            ogrn="1222300064931",
            region_id=23,
            legal_address=(
                "Краснодарский край, город Краснодар, улица Северная дом д191 "
                "помещение помещ38офис12"
            ),
            fact_address=(
                "Краснодарский край, Краснодар, Северная, д.д191, "
                "пом.помещ38офис12"
            ),
            contact_name="Овчинников Михаил Юрьевич",
            phone="+79889574354",
            email="metrix.maisky@yandex.ru",
            url="metriks.ru",
            company_group_id=None,
        ),
    ]
    assert result[1].short_name.startswith("CЗ")


@pytest.mark.parametrize("site_state", ["missing", "null"])
def test_missing_or_null_developer_site_normalizes_to_none(site_state: str) -> None:
    raw_developer = _raw_developer_306()
    if site_state == "missing":
        del raw_developer["devSite"]
    else:
        raw_developer["devSite"] = None

    result = NashDomDataNormalizer().normalize_developers([raw_developer])[0]

    assert result.url is None


@pytest.mark.parametrize("invalid_site", [123, [], {}, "  "])
def test_invalid_optional_developer_site_is_normalization_error(
    invalid_site: object,
) -> None:
    raw_developer = _raw_developer_306()
    raw_developer["devSite"] = invalid_site

    with pytest.raises(NashDomNormalizationError, match="URL застройщика"):
        NashDomDataNormalizer().normalize_developers([raw_developer])


def test_missing_required_developer_field_is_normalization_error() -> None:
    raw_developer = _raw_developer_306()
    del raw_developer["devInn"]

    with pytest.raises(NashDomNormalizationError, match="обязательное поле"):
        NashDomDataNormalizer().normalize_developers([raw_developer])


def test_invalid_required_developer_type_is_normalization_error() -> None:
    raw_developer = _raw_developer_306()
    raw_developer["devOrgRegRegionCd"] = "72"

    with pytest.raises(NashDomNormalizationError, match="целым числом"):
        NashDomDataNormalizer().normalize_developers([raw_developer])
