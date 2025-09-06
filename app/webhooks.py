from .webhook_registry import register_webhook
from .dependencies import WebhookVerifier
from .services.webhook_handler import process_github_webhook_task, process_stripe_webhook_task

# Create verifier instances
verify_github = WebhookVerifier(source="github")
verify_stripe = WebhookVerifier(source="stripe")

# Register our webhook sources
register_webhook(
    source="github",
    verifier=verify_github,
    task=process_github_webhook_task
)

register_webhook(
    source="stripe",
    verifier=verify_stripe,
    task=process_stripe_webhook_task
)
