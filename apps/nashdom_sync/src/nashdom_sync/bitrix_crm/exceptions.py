class BitrixClientError(Exception):
    """Базовая ошибка клиента Bitrix CRM."""


class BitrixGatewayError(BitrixClientError):
    """Недоступен Gateway либо нарушен контракт его ответа."""


class BitrixRequestFailedError(BitrixClientError):
    """Gateway сообщил об определённой неудаче операции."""


class BitrixRequestUnknownError(BitrixClientError):
    """Результат операции неизвестен; автоматически повторять её нельзя."""
