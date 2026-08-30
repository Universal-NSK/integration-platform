"""Взаимодействие с NashDom и нормализация его данных."""

from nashdom_sync.extract.nashdom.client import NashDomClient
from nashdom_sync.extract.nashdom.normalizer import NashDomDataNormalizer

__all__ = ["NashDomClient", "NashDomDataNormalizer"]
