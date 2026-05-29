from prometheus_client import Counter, Histogram

CUSTOMER_WEBHOOK_TOTAL = Counter(
    "customer_webhook_total",
    "Total number of webhooks received per customer and source",
    ["customer_id", "source"],
)

WEBHOOK_PROCESSING_DURATION = Histogram(
    "webhook_processing_duration_seconds",
    "Webhook processing duration in seconds",
    ["customer_id", "source"],
)

CUSTOMER_WEBHOOK_ERRORS_TOTAL = Counter(
    "customer_webhook_errors_total",
    "Total number of webhook processing errors per customer and source",
    ["customer_id", "source", "error_type"],
)
