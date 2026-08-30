import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, cast

import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
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
