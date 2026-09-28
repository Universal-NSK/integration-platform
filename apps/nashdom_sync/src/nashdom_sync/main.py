"""Точка входа приложения синхронизации NashDom."""

from pathlib import Path

from runtime_files import RuntimePaths

from nashdom_sync.orchestrator import SyncOrchestrator


def main() -> None:
    """Определить runtime-пути и передать управление оркестратору."""
    paths = RuntimePaths.from_project(start=Path(__file__))
    SyncOrchestrator().run(paths)
