import logging
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def close_gateway_logging_handlers() -> Iterator[None]:
    yield

    logger = logging.getLogger("bitrix_gateway")
    for handler in list(logger.handlers):
        if getattr(handler, "_platform_logging_owned", False) is True:
            logger.removeHandler(handler)
            handler.close()
