"""Последовательный запуск синхронизации с выполнением и сохранением результата Load."""

import logging
from contextlib import suppress
from time import perf_counter
from typing import Optional

from platform_logging import LoggingConfig, configure_logging, log_event
from runtime_files import RuntimePaths

from nashdom_sync.extract import ExtractService
from nashdom_sync.load import LoadIncompleteError, LoadService
from nashdom_sync.providers.browser_provider import BrowserProvider
from nashdom_sync.providers.crm_context_cache import CrmContextCache
from nashdom_sync.providers.crm_provider import CrmProvider
from nashdom_sync.providers.settings_provider import SettingsProvider
from nashdom_sync.run_artifacts import RunArtifactStore, RunStage
from nashdom_sync.transform import TransformService


class SyncOrchestratorError(Exception):
    """Ошибка инфраструктуры оркестратора синхронизации."""


class LoggingInitializationError(SyncOrchestratorError):
    """Не удалось настроить логирование запуска."""


class SyncOrchestrator:
    """Владеет компонентами, браузером и артефактами одного запуска."""

    def run(self, paths: RuntimePaths) -> None:
        """Последовательно получить данные, выполнить план и сохранить результаты."""
        overall_started = perf_counter()
        run_dir = paths.create_run_dir("nashdom_sync")
        artifacts = RunArtifactStore.start(run_dir)
        current_stage = RunStage.INITIALIZATION
        stage_started = perf_counter()
        logger: Optional[logging.Logger] = None

        def emit(event: str, started: float, exception: Optional[Exception] = None) -> None:
            if logger is None:
                return
            details = {} if exception is None else {"exception_type": type(exception).__name__}
            log_event(
                logger,
                logging.INFO if exception is None else logging.ERROR,
                event,
                run_id=run_dir.name,
                stage=current_stage.value,
                duration_seconds=perf_counter() - started,
                **details,
            )

        try:
            settings_provider = SettingsProvider(paths)
            browser_provider = BrowserProvider()
            extract_service = ExtractService()
            transform_service = TransformService()
            settings = settings_provider.provide()
            try:
                configure_logging(
                    service_name="nashdom_sync",
                    logger_name="nashdom_sync",
                    run_dir=run_dir,
                    config=LoggingConfig(
                        level=settings.logging.level,
                        console=settings.logging.console,
                        log_payloads=settings.logging.log_payloads,
                        max_bytes=settings.logging.max_bytes,
                        backup_count=settings.logging.backup_count,
                    ),
                )
            except Exception as exc:
                raise LoggingInitializationError(
                    "Не удалось настроить логирование запуска"
                ) from exc
            logger = logging.getLogger("nashdom_sync")
            emit("sync_started", overall_started)
            emit("stage_started", stage_started)
            crm_provider = CrmProvider(settings.bitrix)
            load_service = (
                LoadService(settings.bitrix) if settings.execution.load_enabled else None
            )
            emit("stage_completed", stage_started)

            current_stage = RunStage.CRM_CONTEXT
            stage_started = perf_counter()
            artifacts.mark_stage(current_stage)
            emit("stage_started", stage_started)
            cache = CrmContextCache(paths.program_data_file("crm_context.json"))
            if not settings.execution.load_enabled and cache.exists():
                crm_context = cache.load()
                context_source = "cache"
            else:
                crm_context = crm_provider.provide(settings.region)
                context_source = "api"
            log_event(
                logger,
                logging.INFO,
                "crm_context_source",
                run_id=run_dir.name,
                stage=current_stage.value,
                duration_seconds=perf_counter() - stage_started,
                source=context_source,
            )
            artifacts.save_crm_context(crm_context)
            emit("stage_completed", stage_started)

            current_stage = RunStage.EXTRACT
            stage_started = perf_counter()
            artifacts.mark_stage(current_stage)
            emit("stage_started", stage_started)
            driver = browser_provider.provide(settings.browser)
            try:
                extract_result = extract_service.extract(driver, settings.extract)
            except BaseException:
                # Закрытие браузера не должно подменять исходную ошибку извлечения.
                with suppress(Exception):
                    driver.quit()
                raise
            else:
                driver.quit()
            artifacts.save_extract_result(extract_result)
            emit("stage_completed", stage_started)

            current_stage = RunStage.TRANSFORM
            stage_started = perf_counter()
            artifacts.mark_stage(current_stage)
            emit("stage_started", stage_started)
            transform_result = transform_service.transform(
                extract_result, crm_context, settings.region
            )
            artifacts.save_sync_plan(transform_result.plan)
            emit("stage_completed", stage_started)
            if load_service is None:
                log_event(
                    logger,
                    logging.INFO,
                    "load_skipped",
                    run_id=run_dir.name,
                    stage=current_stage.value,
                    duration_seconds=perf_counter() - overall_started,
                    reason="disabled_by_configuration",
                )
                artifacts.mark_completed()
                emit("sync_completed", overall_started)
                return

            current_stage = RunStage.LOAD
            stage_started = perf_counter()
            artifacts.mark_stage(current_stage)
            emit("stage_started", stage_started)
            load_result = load_service.load(transform_result.plan)
            artifacts.save_load_result(load_result)
            if not load_result.is_successful:
                raise LoadIncompleteError("Не все операции плана синхронизации выполнены успешно")
            emit("stage_completed", stage_started)
            artifacts.mark_completed()
            emit("sync_completed", overall_started)
        except Exception as exc:
            # Каждая диагностическая попытка независима и сохраняет первичную ошибку.
            with suppress(Exception):
                emit("sync_failed", overall_started, exc)
            with suppress(Exception):
                artifacts.mark_failed(current_stage, type(exc).__name__)
            raise
