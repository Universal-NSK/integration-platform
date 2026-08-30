class ExtractError(Exception):
    """Ошибка этапа извлечения данных."""


class NashDomClientError(ExtractError):
    """Нарушен контракт взаимодействия с NashDom."""


class NashDomUnavailableError(NashDomClientError):
    """NashDom временно недоступен извне."""


class NashDomNormalizationError(ExtractError):
    """Исходные данные NashDom нельзя привести к контракту приложения."""


class SourceDataValidationError(ExtractError):
    """Нормализованный набор исходных данных нарушает ограничения."""
