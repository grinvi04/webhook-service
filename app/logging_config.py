import logging
import sys
from logging.config import dictConfig

class JsonFormatter(logging.Formatter):
    """Formats logs as a JSON string."""

    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        if record.stack_info:
            log_record['stack_info'] = self.formatStack(record.stack_info)
        return str(log_record)


def setup_logging():
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'json': {
                'class': 'app.logging_config.JsonFormatter',
            },
        },
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'stream': sys.stdout,
                'formatter': 'json',
            },
        },
        'root': {
            'level': 'INFO',
            'handlers': ['stdout'],
        },
    }
    dictConfig(config)
