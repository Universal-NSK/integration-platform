# platform-logging

`platform_logging` configures Python's standard `logging` package for one Integration
Platform service namespace. It always writes a UTF-8 rotating file under
`RuntimePaths.program_data_dir("logs") / service_name` and can add the same structured
formatter to the console.

```python
import logging

from platform_logging import (
    LoggingConfig,
    configure_logging,
    log_event,
    log_payload,
    with_context,
)

config = LoggingConfig(
    level="INFO",
    console=True,
    log_payloads=True,
    max_bytes=10_000_000,
    backup_count=5,
)
session = configure_logging("bitrix_gateway", "bitrix_gateway", paths, config)

logger = logging.getLogger("bitrix_gateway.dispatch")
job_logger = with_context(logger, job_id="a812", method="crm.company.add")
log_event(job_logger, logging.INFO, "job_started", queue_wait="6ms", queue_size=1)
log_payload(
    job_logger,
    logging.INFO,
    "request_payload",
    payload,
    enabled=session.config.log_payloads,
)
```

The package configures only the requested logger namespace with `propagate = False`;
it does not configure the root logger or capture unrelated libraries. Reconfiguring the
same namespace creates a fresh collision-safe session file and replaces and closes only
handlers previously created by `platform_logging`.

Payload and response logging is explicit and preserves complete JSON data. Callers may
log business payloads and responses, but must never pass webhook URLs, secret
configuration, or full Bitrix request URLs to any logging helper.
