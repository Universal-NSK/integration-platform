import logging
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def close_platform_logging_handlers() -> Iterator[None]:
    yield

    for candidate in list(logging.Logger.manager.loggerDict.values()):
        if not isinstance(candidate, logging.Logger):
            continue
        for handler in list(candidate.handlers):
            if getattr(handler, "_platform_logging_owned", False) is True:
                candidate.removeHandler(handler)
                handler.close()
