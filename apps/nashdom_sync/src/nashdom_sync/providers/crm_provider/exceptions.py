class CrmProviderError(Exception):
    """Не удалось подготовить полный контекст CRM."""


class CrmMissingSemanticError(CrmProviderError):
    """Обязательное поле, справочник, тип или сотрудник не найден."""


class CrmAmbiguousSemanticError(CrmProviderError):
    """Семантическое соответствие неоднозначно."""


class CrmInvalidDataError(CrmProviderError):
    """Данные CRM нарушают обязательный контракт."""
