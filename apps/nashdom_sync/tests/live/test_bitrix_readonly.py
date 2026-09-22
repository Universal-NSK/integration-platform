import os
from typing import Iterator

import pytest
from nashdom_sync.bitrix_crm import ClientBitrixCRM

pytestmark = [
    pytest.mark.bitrix_live,
    pytest.mark.skipif(os.environ.get("RUN_BITRIX_LIVE") != "1", reason="Live Bitrix отключён"),
]


@pytest.fixture
def live_client(request: pytest.FixtureRequest) -> Iterator[ClientBitrixCRM]:
    # Одного окружения недостаточно: требуется также явный выбор маркера
    if str(request.config.getoption("markexpr")).strip() != "bitrix_live":
        pytest.skip("Требуется явный выбор -m bitrix_live")
    if os.environ.get("RUN_BITRIX_LIVE") != "1":
        pytest.skip("Требуется RUN_BITRIX_LIVE=1")
    url = os.environ.get("BITRIX_GATEWAY_URL")
    if not url:
        pytest.skip("Требуется BITRIX_GATEWAY_URL; production secrets автоматически не читаются")
    client = ClientBitrixCRM(gateway_url=url, timeout=30.0)
    try:
        yield client
    finally:
        client.close()


def test_live_profile(live_client: ClientBitrixCRM) -> None:
    assert live_client.profile()


def test_live_owner_types(live_client: ClientBitrixCRM) -> None:
    assert live_client.list_owner_types()


def test_live_company_fields(live_client: ClientBitrixCRM) -> None:
    assert "title" in live_client.get_item_fields(4)
