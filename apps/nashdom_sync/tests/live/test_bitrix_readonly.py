import json
import os
from datetime import datetime, timezone
from pathlib import Path
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


def backup_leads_and_companies(client: ClientBitrixCRM, output_dir: Path) -> Path:
    """Сохранить доступные лиды и компании со всеми полями API и их метаданными."""

    started_at = datetime.now(timezone.utc)
    lead_fields = client.get_item_fields(1)
    company_fields = client.get_item_fields(4)
    # Звёздочка включает также fm; клиент самостоятельно обходит все страницы.
    leads = client.list_items(1, select=["*"])
    companies = client.list_items(4, select=["*"])
    payload = {
        "schema_version": 1,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"leads": len(leads), "companies": len(companies)},
        "fields": {"leads": lead_fields, "companies": company_fields},
        "leads": leads,
        "companies": companies,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / ("bitrix_backup_" + started_at.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    temporary_path = output_path.with_suffix(".json.partial")
    # При ошибке записи неполный файл не выдаётся за готовый JSON-бэкап.
    with temporary_path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temporary_path.rename(output_path)
    print("Бэкап: {}; лидов: {}; компаний: {}".format(output_path, len(leads), len(companies)))
    return output_path


@pytest.mark.skipif(
    os.environ.get("RUN_BITRIX_BACKUP") != "1", reason="Требуется RUN_BITRIX_BACKUP=1"
)
def test_backup_leads_and_companies(live_client: ClientBitrixCRM) -> None:
    """Выполнить явно запрошенный экспорт без изменения данных CRM."""

    repo = Path(__file__).resolve().parents[4]
    output_dir = Path(os.environ.get("BITRIX_BACKUP_DIR", str(repo / "temp" / "bitrix_backups")))
    backup_leads_and_companies(live_client, output_dir.resolve())
