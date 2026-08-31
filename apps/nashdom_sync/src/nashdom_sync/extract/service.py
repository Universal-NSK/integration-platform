from typing import List, Set

from selenium.webdriver.remote.webdriver import WebDriver

from nashdom_sync.contracts import (
    ExtractedDeveloper,
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
        """Выполнить object/developer stages и явно остановить неполный Extract."""
        client = NashDomClient(driver)
        validator = SourceDataValidator()
        objects = self._extract_objects(client, validator, settings.nashdom)
        developer_ids = self._collect_developer_ids(objects)
        developers = self._extract_developers(client, validator, developer_ids)
        validator.validate_company_group_consistency(objects, developers)
        self._collect_company_group_ids(objects, developers)

        raise NotImplementedError(
            "Object-stage и developer-stage завершены, но извлечение групп компаний "
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

    @staticmethod
    def _extract_developers(
        client: NashDomClient,
        validator: SourceDataValidator,
        developer_ids: Set[int],
    ) -> List[ExtractedDeveloper]:
        developers = client.get_developers(developer_ids)
        validator.validate_developers(developers, developer_ids)
        return developers

    @staticmethod
    def _collect_company_group_ids(
        objects: List[ExtractedObject],
        developers: List[ExtractedDeveloper],
    ) -> Set[int]:
        return {
            company_group_id
            for company_group_id in (
                [extracted_object.company_group_id for extracted_object in objects]
                + [developer.company_group_id for developer in developers]
            )
            if company_group_id is not None
        }
