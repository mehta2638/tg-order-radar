import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.correlation import get_correlation_id


def add_correlation_id(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    current_correlation_id = get_correlation_id()
    if current_correlation_id is not None:
        event_dict["correlation_id"] = current_correlation_id
    return event_dict


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level.upper(),
    )
    structlog.configure(
        processors=[
            add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level.upper()),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
