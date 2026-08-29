class ConfigurationError(Exception):
    """Ошибка конфигурации синхронизации."""


class ConfigurationOverlapError(ConfigurationError):
    """Один параметр определён в обоих файлах настроек."""

    def __init__(self, parameter_path: str) -> None:
        super().__init__(
            f"Параметр {parameter_path} определён одновременно в sync.toml и sync.paths.toml"
        )
