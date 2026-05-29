from .services.webhook_handler import (
    process_github_webhook_task,
    process_stripe_webhook_task,
)
from .webhook_registry import register_webhook

# Register our webhook sources
register_webhook(source="github", task=process_github_webhook_task)
register_webhook(source="stripe", task=process_stripe_webhook_task)
