"""Ошибки контракта и неполного выполнения стадии Load."""


class LoadError(Exception):
    """Базовая ошибка стадии Load."""


class LoadInvariantError(LoadError):
    """Нарушен внутренний контракт Transform → Load."""


class LoadIncompleteError(LoadError):
    """План обработан и результат сохранён, но не все операции успешны."""
