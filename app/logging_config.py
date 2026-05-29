import logging
import sys

import structlog


def setup_logging():
    """
    Configures logging to use structlog for structured, JSON-formatted logs.
    """
    # Define the processor chain for structlog
    shared_processors = [
        # Add structlog's context variables to the event dictionary
        structlog.contextvars.merge_contextvars,
        # Add log level, logger name, etc.
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        # Add a timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso"),
        # Perform string formatting of the main message
        structlog.stdlib.PositionalArgumentsFormatter(),
        # If the log record contains an exception, render it
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Add call site information (function name, line number)
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            # This processor is last to ensure all context is captured before rendering
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        # Use a logger factory that integrates with Python's standard logging
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Use a wrapper class that provides standard logging methods (info, error, etc.)
        wrapper_class=structlog.stdlib.BoundLogger,
        # Cache the logger factory for performance
        cache_logger_on_first_use=True,
    )

    # Configure the underlying standard logging formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        # The foreign_pre_chain is used for logs originating from standard logging
        foreign_pre_chain=shared_processors,
        # The final processor that renders the log entry to a JSON string
        processor=structlog.processors.JSONRenderer(),
    )

    # Configure the standard logging handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Get the root logger and add the configured handler
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Suppress noisy loggers from libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
