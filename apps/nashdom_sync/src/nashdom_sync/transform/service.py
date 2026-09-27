import logging
from time import perf_counter

from platform_logging import log_event

from nashdom_sync.contracts import CrmContext, ExtractResult, RegionSettings
from nashdom_sync.contracts.transform import TransformResult
from nashdom_sync.transform.transformer import SyncPlanTransformer
from nashdom_sync.transform.validator import SyncPlanValidator

logger = logging.getLogger(__name__)


class TransformService:
    """Orchestrate pure plan construction and validation."""

    def transform(
        self,
        extract_result: ExtractResult,
        crm_context: CrmContext,
        region_settings: RegionSettings,
    ) -> TransformResult:
        started = perf_counter()
        counts = dict(
            objects=len(extract_result.objects),
            developers=len(extract_result.developers),
            company_groups=len(extract_result.company_groups),
        )
        log_event(logger, logging.INFO, "transform_started", **counts)
        stage = "building"
        try:
            plan = SyncPlanTransformer().transform(extract_result, crm_context, region_settings)
            stage = "validation"
            SyncPlanValidator(crm_context.structure).validate(plan)
            result = TransformResult(plan)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "transform_failed",
                stage=stage,
                exception_type=type(exc).__name__,
                duration_seconds=perf_counter() - started,
                **counts,
            )
            raise
        log_event(
            logger,
            logging.INFO,
            "transform_completed",
            **counts,
            new_leads=sum(op.operation_id.startswith("lead:") for op in plan.operations),
            new_companies=sum(op.operation_id.startswith("company:") for op in plan.operations),
            new_groups=sum(op.operation_id.startswith("group:") for op in plan.operations),
            operations=len(plan.operations),
            duration_seconds=perf_counter() - started,
        )
        return result
