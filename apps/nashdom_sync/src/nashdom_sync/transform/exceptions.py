class TransformError(Exception):
    """Базовая ошибка этапа Transform."""


class TransformInputError(TransformError):
    """Входные данные не позволяют построить однозначный план."""


class SyncPlanValidationError(TransformError):
    """Построенный план имеет некорректную структуру."""
