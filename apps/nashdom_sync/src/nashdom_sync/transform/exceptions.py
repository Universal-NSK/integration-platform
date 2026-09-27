class TransformError(Exception):
    """Base error of the Transform stage."""


class TransformInputError(TransformError):
    """Inputs cannot produce an unambiguous plan."""


class SyncPlanValidationError(TransformError):
    """The constructed plan is structurally invalid."""
