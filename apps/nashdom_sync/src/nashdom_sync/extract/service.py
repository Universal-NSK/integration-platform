import logging
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import List, Set

from platform_logging import log_event
from selenium.webdriver.remote.webdriver import WebDriver

from nashdom_sync.contracts import (
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractionSettings,
    ExtractResult,
    NashDomExtractSettings,
)
from nashdom_sync.extract.nashdom import NashDomClient
from nashdom_sync.extract.validator import SourceDataValidator

logger = logging.getLogger(__name__)


@dataclass
class _ExtractRunStats:
    region_count: int
    objects_per_region_limit: int
    objects_requested_limit: int

    objects_received: int = 0

    developer_ids_requested: int = 0
    developers_received: int = 0

    company_group_ids_requested: int = 0
    company_groups_received: int = 0

    objects_duration_seconds: float = 0.0
    developers_duration_seconds: float = 0.0
    company_groups_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0


class ExtractService:
    """Управляет последовательностью получения данных внутри Extract scope."""

    def extract(
        self,
        driver: WebDriver,
        settings: ExtractionSettings,
    ) -> ExtractResult:
        """Выполнить все стадии Extract и вернуть канонический результат."""
        total_started_at = perf_counter()

        stats = _ExtractRunStats(
            region_count=len(settings.nashdom.regions),
            objects_per_region_limit=settings.nashdom.objects_to_parse_count,
            objects_requested_limit=(
                len(settings.nashdom.regions) * settings.nashdom.objects_to_parse_count
            ),
        )

        log_event(
            logger,
            logging.INFO,
            "extract_started",
            region_count=stats.region_count,
            region_codes=[region.code for region in settings.nashdom.regions],
            objects_per_region_limit=stats.objects_per_region_limit,
            objects_requested_limit=stats.objects_requested_limit,
        )
        stage = "objects"
        stage_started_at = perf_counter()
        try:
            client = NashDomClient(driver)
            validator = SourceDataValidator()

            stage_started_at = perf_counter()
            objects = self._extract_objects(client, validator, settings.nashdom)
            stats.objects_duration_seconds = perf_counter() - stage_started_at
            stats.objects_received = len(objects)
            log_event(
                logger,
                logging.INFO,
                "objects_extracted",
                objects_requested_limit=stats.objects_requested_limit,
                objects_received=stats.objects_received,
                duration_seconds=stats.objects_duration_seconds,
            )

            stage = "developers"
            stage_started_at = perf_counter()
            developer_ids = self._collect_developer_ids(objects)
            stats.developer_ids_requested = len(developer_ids)
            stage_started_at = perf_counter()
            developers = self._extract_developers(client, validator, developer_ids)
            stats.developers_duration_seconds = perf_counter() - stage_started_at
            stats.developers_received = len(developers)
            log_event(
                logger,
                logging.INFO,
                "developers_extracted",
                developer_ids_requested=stats.developer_ids_requested,
                developers_received=stats.developers_received,
                duration_seconds=stats.developers_duration_seconds,
            )

            stage = "company_group_consistency"
            validator.validate_company_group_consistency(objects, developers)

            stage = "company_groups"
            stage_started_at = perf_counter()
            company_group_ids = self._collect_company_group_ids(objects, developers)
            stats.company_group_ids_requested = len(company_group_ids)
            stage_started_at = perf_counter()
            company_groups = self._extract_company_groups(
                client,
                validator,
                company_group_ids,
            )
            stats.company_groups_duration_seconds = perf_counter() - stage_started_at
            stats.company_groups_received = len(company_groups)
            log_event(
                logger,
                logging.INFO,
                "company_groups_extracted",
                company_group_ids_requested=stats.company_group_ids_requested,
                company_groups_received=stats.company_groups_received,
                duration_seconds=stats.company_groups_duration_seconds,
            )

            result = ExtractResult(
                objects=objects,
                developers=developers,
                company_groups=company_groups,
            )
        except Exception as exc:
            failed_at = perf_counter()
            stats.total_duration_seconds = failed_at - total_started_at
            if stage == "objects":
                stats.objects_duration_seconds = failed_at - stage_started_at
            elif stage == "developers":
                stats.developers_duration_seconds = failed_at - stage_started_at
            elif stage == "company_groups":
                stats.company_groups_duration_seconds = failed_at - stage_started_at
            log_event(
                logger,
                logging.ERROR,
                "extract_failed",
                stage=stage,
                **asdict(stats),
                elapsed_seconds=stats.total_duration_seconds,
                exception_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        stats.total_duration_seconds = perf_counter() - total_started_at
        log_event(logger, logging.INFO, "extract_completed", **asdict(stats))
        return result

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
    def _extract_company_groups(
        client: NashDomClient,
        validator: SourceDataValidator,
        company_group_ids: Set[int],
    ) -> List[ExtractedCompanyGroup]:
        company_groups = client.get_company_groups(company_group_ids)
        validator.validate_company_groups(company_groups, company_group_ids)
        return company_groups

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
