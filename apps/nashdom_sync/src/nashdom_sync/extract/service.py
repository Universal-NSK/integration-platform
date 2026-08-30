from typing import List, Set

from selenium.webdriver.remote.webdriver import WebDriver

from nashdom_sync.contracts import (
    ExtractedObject,
    ExtractionSettings,
    ExtractResult,
    NashDomExtractSettings,
)
from nashdom_sync.extract.nashdom import NashDomClient
from nashdom_sync.extract.validator import SourceDataValidator


class ExtractService:
    """Управляет последовательностью получения данных внутри Extract scope."""

    def extract(
        self,
        driver: WebDriver,
        settings: ExtractionSettings,
    ) -> ExtractResult:
        """Выполнить доступный object-stage и явно остановить неполный Extract."""
        client = NashDomClient(driver)
        validator = SourceDataValidator()
        objects = self._extract_objects(client, validator, settings.nashdom)
        self._collect_developer_ids(objects)

        raise NotImplementedError(
            "Object-stage завершён, но извлечение застройщиков и групп компаний "
            "ещё не реализовано"
        )

    @staticmethod
    def _extract_objects(
        client: NashDomClient,
        validator: SourceDataValidator,
        settings: NashDomExtractSettings,
    ) -> List[ExtractedObject]:
        objects = client.get_objects(settings)
        validator.validate_objects(
            objects,
            {region.code for region in settings.regions},
        )
        return objects

    @staticmethod
    def _collect_developer_ids(objects: List[ExtractedObject]) -> Set[int]:
        return {extracted_object.developer_id for extracted_object in objects}
